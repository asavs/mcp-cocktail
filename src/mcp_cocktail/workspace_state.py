"""Non-destructive workspace inventory and change detection for trial isolation.

An inventory records every regular file beneath a root (including untracked files and
Unity ``.meta`` files), its digest, and whether Git tracks it.  Comparing inventories
reports changes but never reverts, deletes, or moves user data.  This is intentionally
an evidence/safety primitive rather than an automatic rollback mechanism.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class FileRecord:
    path: str
    size: int
    mtime_ns: int
    sha256: str
    tracked: bool
    unity_meta: bool


@dataclass
class WorkspaceInventory:
    root: str
    captured_at: str
    files: list[FileRecord]
    git_available: bool
    inaccessible: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "root": self.root,
            "captured_at": self.captured_at,
            "git_available": self.git_available,
            "files": [asdict(item) for item in self.files],
            "inaccessible": list(self.inaccessible),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkspaceInventory":
        if value.get("schema_version") != 1:
            raise ValueError("Unsupported workspace inventory schema")
        return cls(
            root=value["root"],
            captured_at=value["captured_at"],
            git_available=bool(value["git_available"]),
            files=[FileRecord(**item) for item in value["files"]],
            inaccessible=tuple(value.get("inaccessible", [])),
        )


@dataclass(frozen=True)
class WorkspaceDelta:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    modified: tuple[str, ...]
    inaccessible: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return not (self.added or self.removed or self.modified or self.inaccessible)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "added": list(self.added),
            "removed": list(self.removed),
            "modified": list(self.modified),
            "inaccessible": list(self.inaccessible),
        }


def _tracked_files(root: Path) -> tuple[set[str], bool]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return set(), False
    return {
        item.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        for item in result.stdout.split(b"\0") if item
    }, True


def capture_workspace_inventory(
    root: Path | str,
    exclude_dirs: Iterable[str] = (".git", "Library", "Temp", "Logs", "obj"),
) -> WorkspaceInventory:
    """Hash durable workspace files without modifying them.

    Unity's generated caches are excluded by default. Files that disappear or
    are locked during a live-Editor scan are recorded as inaccessible instead
    of aborting the safety snapshot.
    """
    root_path = Path(root).resolve()
    excluded = set(exclude_dirs)
    tracked, git_available = _tracked_files(root_path)
    records: list[FileRecord] = []
    inaccessible: list[str] = []
    for directory, dirnames, filenames in os.walk(str(root_path)):
        dirnames[:] = sorted(name for name in dirnames if name not in excluded)
        for filename in sorted(filenames):
            path = Path(directory) / filename
            # Do not follow a file symlink outside the workspace while taking a
            # snapshot. The link itself is not a regular-file artifact.
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root_path).as_posix()
            digest = hashlib.sha256()
            try:
                with path.open("rb") as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(block)
                stat = path.stat()
            except (FileNotFoundError, PermissionError, OSError):
                inaccessible.append(relative)
                continue
            records.append(FileRecord(
                path=relative,
                size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                sha256=digest.hexdigest(),
                tracked=relative in tracked,
                unity_meta=relative.endswith(".meta"),
            ))
    return WorkspaceInventory(
        root=str(root_path),
        captured_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        files=records,
        git_available=git_available,
        inaccessible=tuple(sorted(inaccessible)),
    )


def compare_inventories(before: WorkspaceInventory, after: WorkspaceInventory) -> WorkspaceDelta:
    """Return path-level changes; compare content hashes rather than timestamps."""
    if Path(before.root) != Path(after.root):
        raise ValueError("Cannot compare inventories from different roots")
    old = {item.path: item for item in before.files}
    new = {item.path: item for item in after.files}
    return WorkspaceDelta(
        added=tuple(sorted(new.keys() - old.keys())),
        removed=tuple(sorted(old.keys() - new.keys())),
        modified=tuple(sorted(path for path in old.keys() & new.keys()
                              if old[path].sha256 != new[path].sha256)),
        inaccessible=tuple(sorted(set(before.inaccessible) | set(after.inaccessible))),
    )


def _atomic_write_document(path: Path | str, document: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(target))
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_inventory(path: Path | str, inventory: WorkspaceInventory) -> None:
    """Atomically persist an inventory without implying it can be restored."""
    _atomic_write_document(path, inventory.to_dict())


def write_delta(path: Path | str, delta: WorkspaceDelta) -> None:
    """Atomically persist non-destructive change evidence for an external harness."""
    _atomic_write_document(path, delta.to_dict())


def read_inventory(path: Path | str) -> WorkspaceInventory:
    return WorkspaceInventory.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
