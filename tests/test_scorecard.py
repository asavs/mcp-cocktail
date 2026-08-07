"""Tests for mcp_cocktail.scorecard module."""

from pathlib import Path
from mcp_cocktail.config import CocktailConfig, ArmConfig
from mcp_cocktail.scorecard import (
    generate_scorecard,
    propose_rsi_guardrails,
    generate_upstream_bug_draft,
    generate_patch_task,
)
from mcp_cocktail.inbox import append_note


def test_generate_scorecard(tmp_path: Path):
    cfg = CocktailConfig(
        name="scorecard-test",
        description="Testing scorecard generation",
        arms=[ArmConfig(id="arm-a", name="Arm A", type="cli")],
        root_dir=tmp_path,
    )

    trial_dir = tmp_path / "docs" / "trials" / "T-001"
    trial_dir.mkdir(parents=True, exist_ok=True)
    report_file = trial_dir / "arm-arm-a.md"
    report_file.write_text(
        "# Report\nSteps: 3\nVerdict: Success\nCompleted task.", encoding="utf-8"
    )

    out = generate_scorecard(cfg, root_dir=tmp_path)
    assert "| `arm-a` | Arm A | 1 | 100.0% | 3.0 | 0 | Recommended |" in out
    assert (tmp_path / "docs" / "tooling-scorecard.md").exists()


def test_propose_rsi_guardrails(tmp_path: Path):
    inbox_file = tmp_path / "docs" / "findings-inbox.md"
    append_note("unity command silently rejects name=X argument", cost_mins=20, inbox_path=inbox_file)

    proposals = propose_rsi_guardrails(root_dir=tmp_path)
    assert len(proposals) == 1
    assert "rejects" in proposals[0]["source_line"]
    assert "TRAP" in proposals[0]["suggested_message"]


def test_generate_upstream_and_patch_tasks(tmp_path: Path):
    draft_path = generate_upstream_bug_draft("unity pipeline list invents fake row", "Unity CLI", root_dir=tmp_path)
    assert draft_path.exists()
    content = draft_path.read_text(encoding="utf-8")
    assert "Upstream Bug Draft" in content
    assert "Unity CLI" in content

    task_spec = generate_patch_task("CoplayDev set_property ignores value", "arm-c", "CoplayDev/unity-mcp")
    assert task_spec["name"].startswith("Fix_arm-c")
    assert "CoplayDev/unity-mcp" in task_spec["task"]
