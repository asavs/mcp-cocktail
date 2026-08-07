"""Tests for mcp_cocktail.runner module."""

from pathlib import Path
from mcp_cocktail.config import CocktailConfig, ArmConfig, TrialDefaults
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
