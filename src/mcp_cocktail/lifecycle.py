"""Executable, harness-neutral lifecycle for a published Cocktail trial plan."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mcp_cocktail.trial_state import (
    Artifact,
    Evidence,
    LeaseBusyError,
    MutationLease,
    OperationalObservation,
    StageAttempt,
    StageOutcome,
    TrialStateStore,
    UNITY_SHARED_RESOURCE,
    utc_now,
)
from mcp_cocktail.workspace_state import (
    capture_workspace_inventory,
    compare_inventories,
    read_inventory,
    write_delta,
    write_inventory,
)


class LifecycleError(RuntimeError):
    pass


class TrialLifecycle:
    """State machine callable from any harness without granting it implicit trust."""

    def __init__(self, workspace_root: Path | str, trial_id: str):
        self.workspace_root = Path(workspace_root).resolve()
        self.trial_id = trial_id
        self.trial_dir = self.workspace_root / "docs" / "trials" / trial_id
        if not (self.trial_dir / ".plan-complete").is_file():
            raise LifecycleError(f"Trial {trial_id!r} is absent or was not completely published")
        self.tasks = json.loads((self.trial_dir / "trial-tasks.json").read_text("utf-8"))
        self.tasks_by_stage = {item["stage_id"]: item for item in self.tasks}
        self.store = TrialStateStore(
            self.trial_dir / "trial-state.json", trial_id, self.workspace_root
        )

    def inspect(self) -> dict[str, Any]:
        lease = MutationLease(self.workspace_root, "inspect").holder()
        state = self.store.sync_evidence_journal()
        return {"trial_id": self.trial_id, "state": state, "lease": lease}

    def acquire(self, owner: str, ttl_seconds: int = 600) -> dict[str, Any]:
        lease = MutationLease(
            self.workspace_root, owner, trial_id=self.trial_id, ttl_seconds=ttl_seconds
        ).acquire()
        return lease.holder() or {}

    def _lease(self, owner: str, token: str) -> MutationLease:
        return MutationLease.attach(
            self.workspace_root, owner, token,
            resource=UNITY_SHARED_RESOURCE, trial_id=self.trial_id,
        )

    def renew(self, owner: str, token: str) -> dict[str, Any]:
        return self._lease(owner, token).renew()

    def recover(self, expected_token: str, recovered_by: str) -> dict[str, Any]:
        return MutationLease(
            self.workspace_root, recovered_by, trial_id=self.trial_id
        ).recover_stale(expected_token, recovered_by)

    def release(self, owner: str, token: str) -> None:
        lease = self._lease(owner, token)
        running = [
            stage["id"] for stage in self.store.read()["stages"]
            if stage.get("running", {}).get("lease_token") == token
        ]
        if running:
            raise LifecycleError(
                f"Cannot release the mutation lease while stages are running: {', '.join(running)}"
            )
        lease.release()

    def _task(self, stage_id: str) -> dict[str, Any]:
        try:
            return self.tasks_by_stage[stage_id]
        except KeyError as exc:
            raise LifecycleError(f"Unknown stage: {stage_id}") from exc

    def begin(self, stage_id: str, arm: str, owner: str, token: str) -> dict[str, Any]:
        task = self._task(stage_id)
        lease = None
        if task.get("requires_mutation_lease"):
            lease = self._lease(owner, token)
            lease.renew()
        admitted = self.store.begin_stage(
            stage_id, arm, lease_owner=owner if lease else None,
            lease_token=token if lease else None,
        )
        try:
            admitted_stage = next(item for item in admitted["stages"] if item["id"] == stage_id)
            attempt_index = admitted_stage["running"]["attempt_index"]
            before = capture_workspace_inventory(
                self.workspace_root,
                exclude_dirs=(".git", ".agents", "trials", "Library", "Temp", "Logs", "obj"),
            )
            write_inventory(
                self.trial_dir / f"inventory-before-{stage_id}-attempt-{attempt_index}.json",
                before,
            )
            if lease is not None:
                lease.renew()
        except Exception:
            self.store.cancel_begin(stage_id, arm)
            raise
        return admitted

    def finish(
        self,
        stage_id: str,
        arm: str,
        owner: str,
        token: str,
        outcome: str,
        *,
        error: str | None = None,
        evidence: list[dict[str, Any]] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        task = self._task(stage_id)
        lease = None
        if task.get("requires_mutation_lease"):
            lease = self._lease(owner, token)
            lease.renew()
        if outcome == StageOutcome.SUCCEEDED.value and not evidence:
            raise LifecycleError("A succeeded stage requires target-operation evidence")
        state = self.store.claim_finish(stage_id, arm, token if lease else None)
        stage = next((item for item in state["stages"] if item["id"] == stage_id), None)
        attempt_index = stage["running"]["attempt_index"]
        before_path = self.trial_dir / f"inventory-before-{stage_id}-attempt-{attempt_index}.json"
        if not before_path.exists():
            self.store.cancel_finish(stage_id, arm, token if lease else None)
            raise LifecycleError(f"Stage {stage_id!r} has no pre-operation inventory")
        try:
            after = capture_workspace_inventory(
                self.workspace_root,
                exclude_dirs=(".git", ".agents", "trials", "Library", "Temp", "Logs", "obj"),
            )
            after_path = self.trial_dir / f"inventory-after-{stage_id}-attempt-{attempt_index}.json"
            write_inventory(after_path, after)
            delta = compare_inventories(read_inventory(before_path), after)
            delta_data = asdict(delta)
            delta_path = self.trial_dir / f"inventory-delta-{stage_id}-attempt-{attempt_index}.json"
            write_delta(delta_path, delta)
            if lease is not None:
                lease.renew()
        except Exception:
            self.store.cancel_finish(stage_id, arm, token if lease else None)
            raise
        finished_at = utc_now()
        attempt = StageAttempt(
            arm=arm,
            outcome=outcome,
            started_at=stage["running"]["started_at"],
            finished_at=finished_at,
            error=error,
            evidence=[Evidence(**item) for item in (evidence or [])],
            artifacts=[Artifact(**item) for item in (artifacts or [])],
        )
        updated = self.store.record_attempt(
            stage_id, attempt, lease_token=token if lease else None
        )
        observation_outcome = (
            "succeeded" if outcome == StageOutcome.SUCCEEDED.value
            else "cancelled" if outcome == StageOutcome.SKIPPED.value
            else "timed_out" if error and "timeout" in error.casefold()
            else "failed"
        )
        final_state = self.store.record_observation(OperationalObservation(
            arm=arm,
            capability=stage["capability"],
            layer="target_operation",
            operation=stage_id,
            outcome=observation_outcome,
            observed_at=finished_at,
            classification="execution_adapter_report",
            detail=error,
            project_identity=str(self.workspace_root),
        ))
        return {"state": final_state, "workspace_delta": delta_data}
