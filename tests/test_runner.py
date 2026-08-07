"""Tests for mcp_cocktail.runner module."""

from pathlib import Path
from mcp_cocktail.config import CocktailConfig, ArmConfig, TrialDefaults
from mcp_cocktail.runner import create_trial


def test_create_trial(tmp_path: Path):
    cfg = CocktailConfig(
        name="test-env",
        description="Test description",
        arms=[
            ArmConfig(id="arm-a", name="CLI Arm", type="cli", command="mycli"),
            ArmConfig(id="arm-b", name="MCP Arm", type="mcp", mcp_server="mymcp"),
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
    assert "arm-a" in briefs
    assert "arm-b" in briefs
    assert res["scene_strategy"] == "instant_reload"

    trial_dir = tmp_path / "docs" / "trials" / "T-001"
    assert trial_dir.exists()
    assert (trial_dir / "brief-arm-arm-a.md").exists()
    assert (trial_dir / "brief-arm-arm-b.md").exists()
    assert (trial_dir / "trial-meta.json").exists()
    assert (trial_dir / "trial-tasks.json").exists()


def test_create_trial_compare_visual(tmp_path: Path):
    cfg = CocktailConfig(
        name="test-env",
        description="Test description",
        arms=[ArmConfig(id="arm-a", name="CLI Arm", type="cli", command="mycli")],
        root_dir=tmp_path,
    )

    res = create_trial(
        trial_id="T-002",
        task_description="Create prefab",
        config=cfg,
        compare_visual=True,
    )

    assert res["scene_strategy"] == "temp_scene"
    brief_text = res["briefs"]["arm-a"]
    assert "Assets/Scenes/Trial_T-002_Arm_arm-a.unity" in brief_text
