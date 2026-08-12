"""Tests for mcp_cocktail.runner module."""

from pathlib import Path
from mcp_cocktail.config import CocktailConfig, ArmConfig, TrialDefaults
from mcp_cocktail.installer import PRESETS_DIR
from mcp_cocktail.runner import create_trial


def test_create_trial(tmp_path: Path):
    cfg = CocktailConfig(
        name="test-env",
        description="Test description",
        arms=[
            ArmConfig(id="unity-cli", name="Unity CLI", type="cli", command="mycli"),
            ArmConfig(id="official-mcp", name="Official MCP", type="mcp", mcp_server="mymcp"),
        ],
        trial_defaults=TrialDefaults(concurrency="serial", scene_strategy="instant_reload", timeout_seconds=180),
        root_dir=tmp_path,
    )

    res = create_trial(
        trial_id="T-001",
        task_description="Create a test hierarchy and verify state readback",
        config=cfg,
    )

    briefs = res["briefs"]
    assert len(briefs) == 2
    assert "unity-cli" in briefs
    assert "official-mcp" in briefs
    assert res["scene_strategy"] == "instant_reload"

    trial_dir = tmp_path / "docs" / "trials" / "T-001"
    assert trial_dir.exists()
    assert (trial_dir / "brief-unity-cli.md").exists()
    assert (trial_dir / "brief-official-mcp.md").exists()
    assert (trial_dir / "trial-meta.json").exists()
    assert (trial_dir / "trial-tasks.json").exists()


def test_create_trial_compare_visual(tmp_path: Path):
    cfg = CocktailConfig(
        name="test-env",
        description="Test description",
        arms=[ArmConfig(id="unity-cli", name="Unity CLI", type="cli", command="mycli")],
        root_dir=tmp_path,
    )

    res = create_trial(
        trial_id="T-002",
        task_description="Create prefab",
        config=cfg,
        compare_visual=True,
    )

    assert res["scene_strategy"] == "temp_scene"
    brief_text = res["briefs"]["unity-cli"]
    assert "Assets/Scenes/Trial_T-002_unity-cli.unity" in brief_text


def test_capability_filter_excludes_arms_that_do_a_different_job(tmp_path: Path):
    """rage-cli installs and launches Unity for CI; the other CLI arms drive an
    Editor that is already running. Handing both the same task measures nothing
    -- one of them cannot perform it -- and the scorecard reads as a defeat
    rather than a category error."""
    config = CocktailConfig(
        name="unity", description="", root_dir=tmp_path,
        arms=[
            ArmConfig(id="bridge", name="Bridge", type="cli", capabilities=["editor-automation", "cli"]),
            ArmConfig(id="installer", name="Installer", type="cli", capabilities=["project-lifecycle", "ci"]),
        ],
    )

    res = create_trial("T-1", "do a thing", config, capability="editor-automation")
    assert set(res["briefs"]) == {"bridge"}

    everything = create_trial("T-2", "do a thing", config)
    assert set(everything["briefs"]) == {"bridge", "installer"}


def test_explicit_arms_still_win_over_the_capability_filter(tmp_path: Path):
    config = CocktailConfig(
        name="unity", description="", root_dir=tmp_path,
        arms=[ArmConfig(id="installer", name="Installer", type="cli", capabilities=["project-lifecycle"])],
    )

    res = create_trial("T-3", "task", config, arms_override=["installer"], capability="editor-automation")
    assert set(res["briefs"]) == {"installer"}, "naming an arm outright is an instruction, not a hint"


def test_shipped_preset_separates_lifecycle_from_editor_automation():
    config = CocktailConfig.load(PRESETS_DIR / "unity" / "manifest.json")
    by_id = {a.id: a for a in config.arms}

    assert "project-lifecycle" in by_id["rage-cli"].capabilities
    assert "editor-automation" not in by_id["rage-cli"].capabilities
    for arm_id in ("akiojin-cli", "youngwoo-cli", "hatayama-loop"):
        assert "editor-automation" in by_id[arm_id].capabilities

    untagged = [a.id for a in config.arms if not a.capabilities]
    assert not untagged, f"arms with no capabilities declared: {untagged}"


def test_fabricated_arm_is_gone():
    """smithery-toolkit-mcp was invented in 0437026: its port sat in the 8084
    gap of a counted sequence, and no such project exists on Smithery, npm or
    GitHub. A survey entry nobody can obtain is not a survey entry."""
    config = CocktailConfig.load(PRESETS_DIR / "unity" / "manifest.json")
    ids = {a.id for a in config.arms}

    assert "smithery-toolkit-mcp" not in ids
    assert all("smithery" not in a.id for a in config.arms)
