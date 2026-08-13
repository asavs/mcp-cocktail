import json
import subprocess
from pathlib import Path

import pytest

from mcp_cocktail.workspace_state import (
    capture_workspace_inventory,
    compare_inventories,
    read_inventory,
    write_delta,
    write_inventory,
)


def test_inventory_includes_untracked_and_unity_meta_and_detects_changes(tmp_path: Path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "tracked.txt").write_text("one", encoding="utf-8")
    (tmp_path / "untracked.txt").write_text("keep me", encoding="utf-8")
    (tmp_path / "Assets").mkdir()
    (tmp_path / "Assets" / "Shrine.meta").write_text("guid: abc", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True)

    before = capture_workspace_inventory(tmp_path)
    by_path = {item.path: item for item in before.files}
    assert by_path["tracked.txt"].tracked is True
    assert by_path["untracked.txt"].tracked is False
    assert by_path["Assets/Shrine.meta"].unity_meta is True

    (tmp_path / "tracked.txt").write_text("two", encoding="utf-8")
    (tmp_path / "untracked.txt").unlink()
    (tmp_path / "new.txt").write_text("new", encoding="utf-8")
    after = capture_workspace_inventory(tmp_path)
    delta = compare_inventories(before, after)
    assert delta.modified == ("tracked.txt",)
    assert delta.removed == ("untracked.txt",)
    assert delta.added == ("new.txt",)


def test_inventory_round_trip_and_never_contains_git_internals(tmp_path: Path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "file.txt").write_text("contents", encoding="utf-8")
    inventory = capture_workspace_inventory(tmp_path)
    destination = tmp_path.parent / "inventory.json"
    write_inventory(destination, inventory)
    loaded = read_inventory(destination)
    assert loaded == inventory
    assert all(not item.path.startswith(".git/") for item in loaded.files)


def test_inventory_comparison_rejects_different_roots(tmp_path: Path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    with pytest.raises(ValueError, match="different roots"):
        compare_inventories(capture_workspace_inventory(left), capture_workspace_inventory(right))


def test_inventory_skips_unity_generated_caches_by_default(tmp_path: Path):
    (tmp_path / "Assets").mkdir()
    (tmp_path / "Assets" / "kept.meta").write_text("guid: a", encoding="utf-8")
    (tmp_path / "Library").mkdir()
    (tmp_path / "Library" / "huge-cache.bin").write_bytes(b"cache")

    inventory = capture_workspace_inventory(tmp_path)
    paths = {item.path for item in inventory.files}

    assert "Assets/kept.meta" in paths
    assert "Library/huge-cache.bin" not in paths


def test_delta_is_written_as_atomic_versioned_evidence(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    before = capture_workspace_inventory(root)
    (root / "new.meta").write_text("guid: abc", encoding="utf-8")
    delta = compare_inventories(before, capture_workspace_inventory(root))
    destination = tmp_path / "evidence" / "delta.json"
    write_delta(destination, delta)
    assert json.loads(destination.read_text("utf-8")) == {
        "schema_version": 1,
        "added": ["new.meta"],
        "removed": [],
        "modified": [],
        "inaccessible": [],
    }
    assert not list(destination.parent.glob("*.tmp"))
