"""Durable operational evidence shared by doctor and execution adapters."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


OBSERVATIONS_FILE = ".agents/health-observations.json"


@contextmanager
def _journal_lock(path: Path):
    """Serialize read-modify-replace writers across processes."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    stream = open(lock_path, "a+b")
    try:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            if stream.tell() == 0 and stream.read(1) == b"":
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
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


def _timestamp(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            return 0.0
    return 0.0


def load_operational_observations(workspace_root: Path) -> list[dict[str, Any]]:
    """Read the append-style journal, tolerating absent/corrupt legacy files."""
    try:
        payload = json.loads((workspace_root / OBSERVATIONS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    observations = payload.get("observations", []) if isinstance(payload, dict) else []
    if isinstance(observations, list):
        return [item for item in observations if isinstance(item, dict)]
    # Compatibility with the first latest-per-arm draft.
    if isinstance(observations, dict):
        return [item for item in observations.values() if isinstance(item, dict)]
    return []


def append_operational_observation(
    workspace_root: Path, observation: dict[str, Any], *, max_entries: int = 500
) -> None:
    """Append one observation with an atomic replace.

    The schema is deliberately dictionary-based so trial execution can emit
    richer fields without coupling to doctor:
    arm, capability, layer, operation, outcome, observed_at, and optional
    latency_ms/project_identity/classification/detail.
    """
    required = {"arm", "capability", "layer", "operation", "outcome", "observed_at"}
    missing = required.difference(observation)
    if missing:
        raise ValueError(f"operational observation missing: {', '.join(sorted(missing))}")
    if observation["outcome"] not in {"succeeded", "failed", "timed_out", "cancelled"}:
        raise ValueError(f"invalid operational outcome: {observation['outcome']}")
    if observation["layer"] not in {"transport", "target_operation"}:
        raise ValueError(f"invalid operational layer: {observation['layer']}")

    path = workspace_root / OBSERVATIONS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with _journal_lock(path):
        observations = load_operational_observations(workspace_root)
        observations.append(dict(observation))
        observations = observations[-max_entries:]
        payload = {"version": 1, "observations": observations}
        fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def latest_operational_observation(
    workspace_root: Path,
    arm: str,
    capability: str | None = None,
    layer: str | None = None,
    project_identity: str | None = None,
    not_after: float | None = None,
) -> dict[str, Any] | None:
    def same_project(item: dict[str, Any]) -> bool:
        if project_identity is None:
            return True
        observed = item.get("project_identity")
        if not isinstance(observed, str) or not observed:
            return False
        try:
            return os.path.normcase(os.path.realpath(observed)) == os.path.normcase(
                os.path.realpath(project_identity)
            )
        except Exception:
            return observed == project_identity

    matching = [
        item for item in load_operational_observations(workspace_root)
        if item.get("arm") == arm
        and (capability is None or item.get("capability") == capability)
        and (layer is None or item.get("layer") == layer)
        and same_project(item)
        and (not_after is None or _timestamp(item.get("observed_at")) <= not_after)
    ]
    if not matching:
        return None
    return max(matching, key=lambda item: _timestamp(item.get("observed_at")))
