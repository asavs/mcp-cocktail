"""Durable execution state and coordination primitives for Cocktail trials.

This module deliberately does not launch agents.  It defines the portable contract
an in-process runner, a shell harness, or a remote agent adapter can share:

* :class:`TrialStage` records which arm performed each capability and preserves
  artifacts and verification evidence without crediting a composite run to one arm.
* :class:`TrialStateStore` persists that model with locked, atomic read/modify/write
  transactions and records operational observations for Doctor/circuit breakers.
* :class:`MutationLease` provides one explicitly-owned mutation slot per trial.

Files are JSON so other harnesses do not need to import this Python package.  Writes
use a sibling temporary file and ``os.replace``; a short-lived exclusive lock prevents
concurrent writers from losing one another's updates.
"""

from __future__ import annotations

import json
import os
import socket
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from mcp_cocktail.evidence import append_operational_observation


SCHEMA_VERSION = 1
UNITY_SHARED_RESOURCE = "unity-editor-workspace"


class StageOutcome(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class ObservationOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


@dataclass
class Evidence:
    """One independently inspectable claim supporting a stage result."""

    kind: str
    summary: str
    uri: Optional[str] = None
    observed_at: Optional[str] = None
    verifier_arm: Optional[str] = None


@dataclass
class Artifact:
    """A produced file/object and the arm and stage that created it."""

    uri: str
    kind: str = "file"
    digest: Optional[str] = None
    producer_arm: Optional[str] = None


@dataclass
class StageAttempt:
    """An arm's bounded attempt at one capability stage."""

    arm: str
    outcome: str
    started_at: str
    finished_at: Optional[str] = None
    error: Optional[str] = None
    evidence: list[Evidence] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)

    def __post_init__(self) -> None:
        allowed = {item.value for item in StageOutcome} - {StageOutcome.PENDING.value}
        if self.outcome not in allowed:
            raise ValueError(f"Invalid attempt outcome: {self.outcome!r}")


@dataclass
class TrialStage:
    """A capability-sized unit with explicit primary and fallback ownership."""

    id: str
    capability: str
    assigned_arm: str
    fallback_arms: list[str] = field(default_factory=list)
    outcome: str = StageOutcome.PENDING.value
    attempts: list[StageAttempt] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.outcome not in {item.value for item in StageOutcome}:
            raise ValueError(f"Invalid stage outcome: {self.outcome!r}")
        if not self.id or not self.capability or not self.assigned_arm:
            raise ValueError("Stage id, capability, and assigned_arm are required")
        if self.assigned_arm in self.fallback_arms:
            raise ValueError("The assigned arm cannot also be a fallback")
        if len(set(self.fallback_arms)) != len(self.fallback_arms):
            raise ValueError("Fallback arms must be unique")


@dataclass
class OperationalObservation:
    """A full-stack operation result consumable by health/status derivation.

    ``layer`` identifies what was actually proven (for example ``transport`` or
    ``target_operation``); it must not be inferred from a successful outcome.
    """

    arm: str
    capability: str
    layer: str
    operation: str
    outcome: str
    observed_at: str
    latency_ms: Optional[int] = None
    project_identity: Optional[str] = None
    classification: Optional[str] = None
    detail: Optional[str] = None

    def __post_init__(self) -> None:
        if self.outcome not in {item.value for item in ObservationOutcome}:
            raise ValueError(f"Invalid observation outcome: {self.outcome!r}")
        if self.layer not in {"transport", "target_operation"}:
            raise ValueError(f"Invalid observation layer: {self.layer!r}")
        if not self.arm or not self.capability or not self.layer or not self.operation:
            raise ValueError("Observation arm, capability, layer, and operation are required")


class LeaseBusyError(RuntimeError):
    """Raised when another owner holds a trial mutation lease or state lock."""


class LeaseOwnershipError(RuntimeError):
    """Raised when a lease token does not exactly match the current holder."""


class LeaseNotExpiredError(RuntimeError):
    """Raised when explicit stale recovery is requested before proven expiry."""


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _observed_timestamp(value: str) -> float:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError):
        return 0.0


def _atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def _advisory_lock(path: Path, timeout_seconds: float = 5.0) -> Iterator[None]:
    """Hold a cross-process lock that the operating system releases on crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    deadline = time.monotonic() + timeout_seconds
    acquired = False
    try:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise LeaseBusyError(f"Timed out waiting for lease guard: {path}")
                time.sleep(0.02)
        yield
    finally:
        try:
            if acquired:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


@contextmanager
def _file_lock(path: Path, timeout_seconds: float = 5.0) -> Iterator[None]:
    """Crash-released OS lock; the harmless lock file may remain on disk."""
    deadline = time.monotonic() + timeout_seconds
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = open(path, "a+b")
    while True:
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                if stream.read(1) == b"":
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except (OSError, BlockingIOError):
            if time.monotonic() >= deadline:
                stream.close()
                raise LeaseBusyError(f"Timed out waiting for state lock: {path}")
            time.sleep(0.02)
    try:
        yield
    finally:
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


class TrialStateStore:
    """Atomic JSON store for stages, provenance, observations, and circuit state."""

    def __init__(
        self,
        path: Path | str,
        trial_id: Optional[str] = None,
        evidence_workspace: Path | str | None = None,
    ):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.trial_id = trial_id
        self.evidence_workspace = Path(evidence_workspace) if evidence_workspace else None

    def _empty(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "trial_id": self.trial_id,
            "updated_at": utc_now(),
            "stages": [],
            "observations": [],
            "journal_pending": [],
            "circuits": {},
        }

    def read(self) -> dict[str, Any]:
        """Read a consistent state document; a missing store is an empty trial."""
        if not self.path.exists():
            return self._empty()
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported trial state schema: {value.get('schema_version')!r}")
        return value

    def transaction(self, update: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        """Run ``update`` under a cross-process lock and atomically persist it."""
        with _file_lock(self.lock_path):
            state = self.read()
            update(state)
            state["updated_at"] = utc_now()
            _atomic_json_write(self.path, state)
            return state

    def add_stage(self, stage: TrialStage) -> dict[str, Any]:
        def update(state: dict[str, Any]) -> None:
            if any(item.get("id") == stage.id for item in state["stages"]):
                raise ValueError(f"Stage already exists: {stage.id}")
            known = {item.get("id") for item in state["stages"]}
            missing = set(stage.depends_on) - known
            if missing:
                raise ValueError(f"Unknown stage dependencies: {sorted(missing)}")
            state["stages"].append(asdict(stage))
        return self.transaction(update)

    def record_attempt(
        self, stage_id: str, attempt: StageAttempt, *, lease_token: str | None = None
    ) -> dict[str, Any]:
        """Append an attempt, preserving all cross-arm provenance."""
        def update(state: dict[str, Any]) -> None:
            stage = next((item for item in state["stages"] if item["id"] == stage_id), None)
            if stage is None:
                raise KeyError(stage_id)
            allowed = [stage["assigned_arm"]] + list(stage.get("fallback_arms", []))
            if attempt.arm not in allowed:
                raise ValueError(f"Arm {attempt.arm!r} is not assigned to stage {stage_id!r}")
            stages = {item["id"]: item for item in state["stages"]}
            blocked = [
                dependency for dependency in stage.get("depends_on", [])
                if stages[dependency].get("outcome") != StageOutcome.SUCCEEDED.value
            ]
            if blocked:
                raise ValueError(
                    f"Stage {stage_id!r} has incomplete dependencies: {blocked}"
                )
            if stage.get("outcome") == StageOutcome.SUCCEEDED.value:
                raise ValueError(f"Stage {stage_id!r} is already complete")
            running = stage.get("running")
            if not running or running.get("arm") != attempt.arm:
                raise ValueError(f"Stage {stage_id!r} is not running under arm {attempt.arm!r}")
            if running.get("lease_token") != lease_token:
                raise ValueError(f"Stage {stage_id!r} is owned by another lease")
            if not running.get("finishing"):
                raise ValueError(f"Stage {stage_id!r} has not claimed finalization")
            stage["attempts"].append(asdict(attempt))
            stage["outcome"] = attempt.outcome
            stage.pop("running", None)
        return self.transaction(update)

    def begin_stage(
        self, stage_id: str, arm: str, started_at: str | None = None, *,
        lease_owner: str | None = None, lease_token: str | None = None,
    ) -> dict[str, Any]:
        """Atomically admit a stage after dependencies and circuit checks."""
        def update(state: dict[str, Any]) -> None:
            stages = {item["id"]: item for item in state["stages"]}
            if stage_id not in stages:
                raise KeyError(stage_id)
            stage = stages[stage_id]
            allowed = [stage["assigned_arm"]] + list(stage.get("fallback_arms", []))
            if arm not in allowed:
                raise ValueError(f"Arm {arm!r} is not assigned to stage {stage_id!r}")
            blocked = [d for d in stage.get("depends_on", [])
                       if stages[d].get("outcome") != StageOutcome.SUCCEEDED.value]
            if blocked:
                raise ValueError(f"Stage {stage_id!r} has incomplete dependencies: {blocked}")
            circuit = state["circuits"].get(f"{arm}:{stage['capability']}", {})
            if circuit.get("state") == "open":
                raise ValueError(f"Circuit is open for {arm}:{stage['capability']}")
            if stage.get("outcome") == StageOutcome.RUNNING.value:
                raise ValueError(f"Stage {stage_id!r} is already running")
            if stage.get("outcome") == StageOutcome.SUCCEEDED.value:
                raise ValueError(f"Stage {stage_id!r} is already complete")
            stage["outcome"] = StageOutcome.RUNNING.value
            stage["running"] = {
                "arm": arm,
                "started_at": started_at or utc_now(),
                "attempt_index": len(stage.get("attempts", [])) + 1,
                "lease_owner": lease_owner,
                "lease_token": lease_token,
                "finishing": False,
            }
        return self.transaction(update)

    def claim_finish(self, stage_id: str, arm: str, lease_token: str | None) -> dict[str, Any]:
        """Allow exactly one worker holding the stage lease to finalize it."""
        def update(state: dict[str, Any]) -> None:
            stage = next((item for item in state["stages"] if item["id"] == stage_id), None)
            if stage is None:
                raise KeyError(stage_id)
            running = stage.get("running")
            if not running or running.get("arm") != arm:
                raise ValueError(f"Stage {stage_id!r} is not running under arm {arm!r}")
            if running.get("lease_token") != lease_token:
                raise ValueError(f"Stage {stage_id!r} is owned by another lease")
            if running.get("finishing"):
                raise ValueError(f"Stage {stage_id!r} is already being finalized")
            running["finishing"] = True
        return self.transaction(update)

    def cancel_finish(self, stage_id: str, arm: str, lease_token: str | None) -> dict[str, Any]:
        def update(state: dict[str, Any]) -> None:
            stage = next((item for item in state["stages"] if item["id"] == stage_id), None)
            if stage is None:
                raise KeyError(stage_id)
            running = stage.get("running")
            if (not running or running.get("arm") != arm
                    or running.get("lease_token") != lease_token):
                raise ValueError(f"Stage {stage_id!r} finalization ownership changed")
            running["finishing"] = False
        return self.transaction(update)

    def cancel_begin(self, stage_id: str, arm: str) -> dict[str, Any]:
        """Undo admission when pre-operation evidence could not be published.

        This is deliberately narrow: it cannot erase attempts or a stage owned by
        another arm. It exists so a failed inventory write does not strand a stage
        in ``running`` before an adapter was told it may mutate the workspace.
        """
        def update(state: dict[str, Any]) -> None:
            stages = {item["id"]: item for item in state["stages"]}
            if stage_id not in stages:
                raise KeyError(stage_id)
            stage = stages[stage_id]
            running = stage.get("running")
            if not running or running.get("arm") != arm:
                raise ValueError(f"Stage {stage_id!r} is not running under arm {arm!r}")
            if stage.get("attempts"):
                raise ValueError(f"Stage {stage_id!r} already has recorded attempts")
            stage["outcome"] = StageOutcome.PENDING.value
            stage.pop("running", None)
        return self.transaction(update)

    def record_observation(
        self, observation: OperationalObservation, failure_threshold: int = 2
    ) -> dict[str, Any]:
        """Append health evidence and update a capability-scoped circuit breaker.

        A successful *target_operation* closes the circuit. Failures at that layer
        open it at ``failure_threshold`` consecutive failures. Transport success does
        not erase a target failure, preventing a handshake from painting a dead Editor
        green.
        """
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be positive")

        def update(state: dict[str, Any]) -> None:
            data = asdict(observation)
            data["observation_id"] = uuid.uuid4().hex
            state["observations"].append(data)
            key = f"{observation.arm}:{observation.capability}"
            circuit = state["circuits"].setdefault(key, {
                "arm": observation.arm,
                "capability": observation.capability,
                "state": "closed",
                "consecutive_failures": 0,
                "updated_at": observation.observed_at,
            })
            # Journals can be delivered or merged out of order. Preserve the
            # observation, but never let older evidence change the live circuit.
            if _observed_timestamp(observation.observed_at) < _observed_timestamp(
                circuit.get("updated_at", "")
            ):
                return
            if observation.layer != "target_operation":
                return
            if observation.outcome == ObservationOutcome.SUCCEEDED.value:
                circuit["state"] = "closed"
                circuit["consecutive_failures"] = 0
            elif observation.outcome in {
                ObservationOutcome.FAILED.value,
                ObservationOutcome.TIMED_OUT.value,
            }:
                circuit["consecutive_failures"] += 1
                if circuit["consecutive_failures"] >= failure_threshold:
                    circuit["state"] = "open"
            circuit["updated_at"] = observation.observed_at
            circuit["last_outcome"] = observation.outcome
        state = self.transaction(update)
        if self.evidence_workspace is not None:
            # The shared journal has its own cross-process lock and atomic replace.
            # It is deliberately optional so a portable trial package is useful
            # outside the workspace where it was created.
            data = state["observations"][-1]
            try:
                append_operational_observation(self.evidence_workspace, data)
            except OSError:
                def queue_pending(current: dict[str, Any]) -> None:
                    pending = current.setdefault("journal_pending", [])
                    if not any(item.get("observation_id") == data["observation_id"] for item in pending):
                        pending.append(data)
                state = self.transaction(queue_pending)
        return state

    def sync_evidence_journal(self) -> dict[str, Any]:
        """Retry durable journal delivery for observations committed to trial state."""
        if self.evidence_workspace is None:
            return self.read()
        state = self.read()
        for item in list(state.get("journal_pending", [])):
            append_operational_observation(self.evidence_workspace, item)
            observation_id = item.get("observation_id")

            def acknowledge(current: dict[str, Any]) -> None:
                current["journal_pending"] = [
                    queued for queued in current.get("journal_pending", [])
                    if queued.get("observation_id") != observation_id
                ]
            state = self.transaction(acknowledge)
        return state


class MutationLease:
    """Exclusive, token-owned lease for a shared mutation resource.

    Lease files are not silently stolen when old. A caller may inspect ``holder()``
    and an operator can deliberately remove a stale file after checking the owner.
    This favors preservation of a shared Unity workspace over automatic recovery.

    The lease is rooted in the shared workspace, not a trial directory. Consequently
    different trials contending for ``unity-editor-workspace`` share the same lock path, while
    truly independent resources can proceed concurrently.
    """

    def __init__(
        self,
        workspace_root: Path | str,
        owner: str,
        *,
        resource: str = UNITY_SHARED_RESOURCE,
        trial_id: Optional[str] = None,
        ttl_seconds: int = 600,
    ):
        if not owner:
            raise ValueError("Mutation lease owner is required")
        if not resource or resource in {".", ".."} or any(char in resource for char in "/\\"):
            raise ValueError("Mutation lease resource must be one path-safe name")
        if ttl_seconds < 1:
            raise ValueError("Mutation lease ttl_seconds must be positive")
        self.resource = resource
        self.trial_id = trial_id
        self.path = Path(workspace_root) / ".agents" / "leases" / f"{resource}.json"
        self.guard_path = self.path.with_suffix(self.path.suffix + ".guard")
        self.audit_path = self.path.parent / "audit.jsonl"
        self.audit_guard_path = self.audit_path.with_suffix(".lock")
        self.owner = owner
        self.ttl_seconds = ttl_seconds
        self.token = uuid.uuid4().hex
        self._held = False

    def _holder_unlocked(self) -> Optional[dict[str, Any]]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            # A corrupt/partially-written lease is still a lease. Never interpret
            # unreadable ownership metadata as permission to mutate shared state.
            return {"owner": "unknown (unreadable lease)", "corrupt": True}

    def holder(self) -> Optional[dict[str, Any]]:
        """Return a guarded snapshot of current ownership metadata."""
        with _advisory_lock(self.guard_path):
            return self._holder_unlocked()

    def _require_token_unlocked(self, expected_token: str) -> dict[str, Any]:
        holder = self._holder_unlocked()
        if holder is None:
            raise LeaseOwnershipError("Mutation lease no longer exists")
        if not expected_token or holder.get("token") != expected_token:
            raise LeaseOwnershipError("Mutation lease token does not match current holder")
        return holder

    def _append_audit(self, evidence: dict[str, Any]) -> None:
        """Append recovery evidence durably; the audit is never rewritten."""
        with _advisory_lock(self.audit_guard_path):
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(evidence, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    @classmethod
    def attach(
        cls, workspace_root: Path | str, owner: str, token: str, *,
        resource: str = UNITY_SHARED_RESOURCE, trial_id: str | None = None,
    ) -> "MutationLease":
        lease = cls(workspace_root, owner, resource=resource, trial_id=trial_id)
        with _advisory_lock(lease.guard_path):
            try:
                holder = lease._require_token_unlocked(token)
            except LeaseOwnershipError as exc:
                # Preserve the distinction between a crashed/missing lease and
                # a live lease owned by somebody else.  Both remain hard
                # failures, but operators need the actual reason to recover
                # safely instead of debugging a fictitious token mismatch.
                raise LeaseBusyError(str(exc)) from exc
            if holder.get("owner") != owner:
                raise LeaseBusyError("Lease belongs to a different owner")
            if trial_id is not None and holder.get("trial_id") != trial_id:
                raise LeaseBusyError("Lease belongs to a different trial")
            lease.token = token
            lease._held = True
        return lease

    def acquire(self) -> "MutationLease":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "resource": self.resource,
            "trial_id": self.trial_id,
            "owner": self.owner,
            "token": self.token,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "acquired_at": utc_now(),
            "expires_at_epoch": time.time() + self.ttl_seconds,
        }
        with _advisory_lock(self.guard_path):
            holder = self._holder_unlocked()
            if holder is not None:
                raise LeaseBusyError(f"Mutation lease held by {holder.get('owner', 'unknown')}")
            # O_EXCL remains as defense against non-cooperating/legacy writers.
            descriptor = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        self._held = True
        return self

    def renew(
        self, expected_token: Optional[str] = None, ttl_seconds: Optional[int] = None
    ) -> dict[str, Any]:
        """Extend an attached lease after exact token verification."""
        if not self._held:
            raise LeaseBusyError("Cannot renew an unowned lease")
        token = self.token if expected_token is None else expected_token
        extension = self.ttl_seconds if ttl_seconds is None else ttl_seconds
        if extension < 1:
            raise ValueError("Mutation lease ttl_seconds must be positive")
        with _advisory_lock(self.guard_path):
            try:
                holder = self._require_token_unlocked(token)
            except LeaseOwnershipError as exc:
                raise LeaseBusyError("Mutation lease ownership changed") from exc
            holder["renewed_at"] = utc_now()
            holder["expires_at_epoch"] = time.time() + extension
            _atomic_json_write(self.path, holder)
            return holder

    def recover_stale(self, expected_token: str, recovered_by: str) -> dict[str, Any]:
        """Explicitly remove an expired lease after token proof and durable audit.

        Recovery never runs from :meth:`acquire`. An unreadable lease cannot prove its
        token or expiry and therefore cannot be recovered through this API.
        """
        if not recovered_by:
            raise ValueError("recovered_by is required")
        with _advisory_lock(self.guard_path):
            holder = self._require_token_unlocked(expected_token)
            expires_at = holder.get("expires_at_epoch")
            if not isinstance(expires_at, (int, float)) or time.time() < expires_at:
                raise LeaseNotExpiredError("Mutation lease has not proven expired")
            evidence = {
                "schema_version": SCHEMA_VERSION,
                "action": "stale_recovery",
                "observed_at": utc_now(),
                "resource": self.resource,
                "trial_id": holder.get("trial_id"),
                "owner": holder.get("owner"),
                "expected_token": expected_token,
                "expired_at_epoch": expires_at,
                "recovered_by": recovered_by,
            }
            # Audit first: a crash may leave an expired lease plus an audit record,
            # but can never remove ownership without durable evidence.
            self._append_audit(evidence)
            self.path.unlink()
            self._held = False
            return evidence

    def release(self) -> None:
        if not self._held:
            return
        with _advisory_lock(self.guard_path):
            try:
                self._require_token_unlocked(self.token)
            except LeaseOwnershipError:
                self._held = False
                raise
            self.path.unlink()
            self._held = False

    def __enter__(self) -> "MutationLease":
        return self.acquire()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.release()
