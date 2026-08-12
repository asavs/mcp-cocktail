"""Tests for mcp_cocktail.preflight module."""

import json
from pathlib import Path

from mcp_cocktail.config import ArmConfig, CocktailConfig
from mcp_cocktail.installer import PRESETS_DIR
from mcp_cocktail.preflight import (
    detect_tool_version,
    detect_unity_project,
    parse_version,
    run_preflight,
    satisfies,
)


def test_parse_version_anchors_on_the_number_not_the_layout():
    """Tools disagree wildly about how to print a version."""
    assert parse_version("v22.23.0") == (22, 23, 0)
    assert parse_version("npm 10.9.8") == (10, 9, 8)
    assert parse_version("go version go1.26.5 windows/amd64") == (1, 26, 5)
    assert parse_version("1.0.0-beta.3") == (1, 0, 0)
    assert parse_version("no digits here") == ()


def test_satisfies_compares_at_the_precision_the_requirement_asks_for():
    """'>=22' against 22.14.0 is met -- reading it as 22 < 22.14 would block
    every arm whose requirement is coarser than the installed version."""
    assert satisfies("v22.14.0", ">=22")
    assert satisfies("v24.0.0", ">=24")
    assert not satisfies("v22.23.0", ">=24")
    assert satisfies("1.0.0-beta.3", ">=1.0")
    assert not satisfies("6000.0.1f1", ">=7000")
    assert satisfies("6000.0.1f1", ">=2022.3")


def test_unparseable_requirement_passes_rather_than_blocks():
    """Refusing to install over a spec we cannot read is a worse error than
    proceeding: it would strand an arm on our parser's limits, not the user's."""
    assert satisfies("1.2.3", "whatever-nonsense")
    assert satisfies("unknown", ">=22")


def test_absent_tool_is_none_not_a_crash():
    assert detect_tool_version("nonexistent_binary_xyz_123") is None


def test_unity_project_version_is_read_from_the_marker(tmp_path: Path):
    assert detect_unity_project(tmp_path) is None

    (tmp_path / "ProjectSettings").mkdir()
    (tmp_path / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 6000.5.5f1\nm_EditorVersionWithRevision: 6000.5.5f1 (abc)\n",
        encoding="utf-8",
    )
    assert detect_unity_project(tmp_path) == "6000.5.5f1"


def test_preflight_separates_blocked_from_installable(tmp_path: Path):
    """The question doctor cannot answer: not 'is it running' but 'could I
    even have this'. An arm needing Node 24 on a Node 18 box reports OFFLINE
    identically to one nobody installed yet."""
    config = CocktailConfig(
        name="t", description="", root_dir=tmp_path,
        arms=[
            ArmConfig(id="impossible", name="Impossible", type="cli",
                      requires={"tools": {"nonexistent_binary_xyz_123": ">=1"}}),
            ArmConfig(id="unconstrained", name="Unconstrained", type="cli"),
        ],
    )

    readiness, _ = run_preflight(config)
    by_id = {r.arm_id: r for r in readiness}

    assert not by_id["impossible"].installable
    assert by_id["impossible"].blockers[0].name == "nonexistent_binary_xyz_123"
    # No requirements is not the same claim as requirements met.
    assert by_id["unconstrained"].requirements == []


def test_unity_requirement_uses_the_workspace_project_version(tmp_path: Path):
    (tmp_path / "ProjectSettings").mkdir()
    (tmp_path / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 2021.3.1f1\n", encoding="utf-8")

    config = CocktailConfig(
        name="t", description="", root_dir=tmp_path,
        arms=[ArmConfig(id="needs6", name="Needs 6", type="mcp", requires={"unity": ">=6000.0"})],
    )

    readiness, unity_version = run_preflight(config)
    assert unity_version == "2021.3.1f1"
    assert not readiness[0].installable


def test_shipped_preset_requirements_are_machine_checkable():
    """The point of moving these out of prose: code can read them."""
    config = CocktailConfig.load(PRESETS_DIR / "unity" / "manifest.json")
    declared = [a for a in config.arms if a.requires]

    assert len(declared) >= 8, "most arms should declare what they need"
    for arm in declared:
        for tool, spec in (arm.requires.get("tools") or {}).items():
            assert str(spec).startswith(">="), f"{arm.id}/{tool} spec {spec!r} is not checkable"
