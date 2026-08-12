"""Tests for mcp_cocktail.runner module."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from mcp_cocktail.config import CocktailConfig, ArmConfig, TrialDefaults
from mcp_cocktail.installer import PRESETS_DIR
import pytest

from mcp_cocktail.runner import (
    ExecutionUnavailableError,
    EmptyTrialPlanError,
    InvalidTrialIdError,
    TrialAlreadyExistsError,
    create_trial,
    plan_trial,
)


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
    state = json.loads((trial_dir / "trial-state.json").read_text(encoding="utf-8"))
    assert {stage["assigned_arm"] for stage in state["stages"]} == {"unity-cli", "official-mcp"}
    assert all("stage_id" in task for task in json.loads((trial_dir / "trial-tasks.json").read_text("utf-8")))
    assert (trial_dir / ".plan-complete").exists()
    meta = json.loads((trial_dir / "trial-meta.json").read_text(encoding="utf-8"))
    assert meta["lifecycle"]["phase"] == "planned"
    assert meta["lifecycle"]["executed"] is False
    assert res["executed"] is False


def test_plan_does_not_promise_reset_or_rollback(tmp_path: Path):
    cfg = CocktailConfig(
        name="test-env",
        description="",
        arms=[ArmConfig(id="unity-cli", name="Unity CLI", type="cli")],
        root_dir=tmp_path,
    )

    brief = plan_trial("T-SAFE", "Mutate a scene", cfg)["briefs"]["unity-cli"]

    assert "Cocktail does not reset the Editor" in brief
    assert "roll back files" in brief
    assert "will reset scene state" not in brief


def test_legacy_exec_mode_fails_before_writing_a_plan(tmp_path: Path):
    cfg = CocktailConfig(
        name="test-env",
        description="",
        arms=[ArmConfig(id="a", name="A", type="cli")],
        root_dir=tmp_path,
    )

    with pytest.raises(ExecutionUnavailableError, match="execution is not available"):
        create_trial("T-NOEXEC", "task", cfg, exec_mode="auto")

    assert not (tmp_path / "docs" / "trials" / "T-NOEXEC").exists()


@pytest.mark.parametrize(
    "trial_id",
    ["", ".", "..", "../escape", "..\\escape", "nested/T-1", "nested\\T-1", "/absolute", "T.1"],
)
def test_trial_id_must_be_one_safe_directory_name(tmp_path: Path, trial_id: str):
    cfg = CocktailConfig(name="test", description="", arms=[], root_dir=tmp_path)

    with pytest.raises(InvalidTrialIdError, match="Paths and '\\.\\.' are not allowed"):
        plan_trial(trial_id, "task", cfg)

    assert not (tmp_path / "docs").exists()


def test_existing_trial_is_never_silently_overwritten(tmp_path: Path):
    cfg = CocktailConfig(
        name="test",
        description="",
        arms=[ArmConfig(id="a", name="A", type="cli")],
        root_dir=tmp_path,
    )
    plan_trial("T-EXISTS", "original", cfg)
    meta_path = tmp_path / "docs" / "trials" / "T-EXISTS" / "trial-meta.json"
    original = meta_path.read_bytes()

    with pytest.raises(TrialAlreadyExistsError, match="refusing to overwrite"):
        plan_trial("T-EXISTS", "replacement", cfg)

    assert meta_path.read_bytes() == original
    assert json.loads(original)["task_description"] == "original"


def test_concurrent_planners_cannot_share_a_trial_id(tmp_path: Path):
    cfg = CocktailConfig(
        name="test",
        description="",
        arms=[ArmConfig(id="a", name="A", type="cli")],
        root_dir=tmp_path,
    )

    def attempt(description: str):
        try:
            return ("planned", plan_trial("T-RACE", description, cfg))
        except TrialAlreadyExistsError as exc:
            return ("exists", str(exc))

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ["first candidate", "second candidate"]))

    assert sorted(outcome[0] for outcome in outcomes) == ["exists", "planned"]
    trial_dir = tmp_path / "docs" / "trials" / "T-RACE"
    meta = json.loads((trial_dir / "trial-meta.json").read_text(encoding="utf-8"))
    tasks = json.loads((trial_dir / "trial-tasks.json").read_text(encoding="utf-8"))
    assert meta["task_description"] in {"first candidate", "second candidate"}
    assert meta["task_description"] in tasks[0]["task"]
    assert not list(trial_dir.glob("*.tmp"))


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


def test_gui_arm_brief_requires_exclusive_input_and_visual_state_readback(tmp_path: Path):
    config = CocktailConfig(
        name="unity",
        description="",
        arms=[
            ArmConfig(
                id="computer-use",
                name="Unity via Computer Use",
                type="gui",
                capabilities=["editor-gui-automation", "visual-inspection"],
            )
        ],
        root_dir=tmp_path,
    )

    result = create_trial("T-GUI", "Create a GameObject", config)
    brief = result["briefs"]["computer-use"]

    assert "exclusive mouse and keyboard control" in brief
    assert "MUST run serially" in brief
    assert "before-and-after screenshots" in brief
    assert "Hierarchy plus Inspector" in brief
    assert "shared global state" in brief
    assert "Do not fall back to CLI, MCP" in brief
    assert "Do not close or restart the Editor" in brief
    assert "If the Editor stops responding, stop the arm" in brief
    assert "Console and Package Manager" in brief
    assert "availability is not proof that Unity is responsive" in brief

    task_file = tmp_path / "docs" / "trials" / "T-GUI" / "trial-tasks.json"
    payloads = json.loads(task_file.read_text(encoding="utf-8"))
    assert payloads[0]["arm_type"] == "gui"
    assert payloads[0]["requires_exclusive_input"] is True
    assert payloads[0]["shared_resources"] == ["unity-editor-workspace"]
    assert payloads[0]["requires_mutation_lease"] is True
    assert payloads[0]["timeout_seconds"] == config.trial_defaults.timeout_seconds


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


def test_unfiltered_plan_records_evidence_under_each_arms_declared_task_capability(tmp_path: Path):
    config = CocktailConfig(
        name="unity", description="", root_dir=tmp_path,
        arms=[
            ArmConfig(
                id="coplay", name="Coplay", type="mcp",
                capabilities=["editor-automation", "mcp"],
            ),
            ArmConfig(id="gui", name="GUI", type="gui", capabilities=["visual-inspection"]),
        ],
    )

    create_trial("T-CAPS", "bounded task", config)
    state = json.loads(
        (tmp_path / "docs" / "trials" / "T-CAPS" / "trial-state.json").read_text("utf-8")
    )
    tasks = json.loads(
        (tmp_path / "docs" / "trials" / "T-CAPS" / "trial-tasks.json").read_text("utf-8")
    )

    assert [stage["capability"] for stage in state["stages"]] == [
        "editor-automation", "visual-inspection",
    ]
    assert [task["evidence_capability"] for task in tasks] == [
        "editor-automation", "visual-inspection",
    ]


def test_explicit_arms_still_win_over_the_capability_filter(tmp_path: Path):
    config = CocktailConfig(
        name="unity", description="", root_dir=tmp_path,
        arms=[ArmConfig(id="installer", name="Installer", type="cli", capabilities=["project-lifecycle"])],
    )

    res = create_trial("T-3", "task", config, arms_override=["installer"], capability="editor-automation")
    assert set(res["briefs"]) == {"installer"}, "naming an arm outright is an instruction, not a hint"


def test_empty_or_unknown_arm_selection_writes_nothing(tmp_path: Path):
    config = CocktailConfig(
        name="unity", description="", root_dir=tmp_path,
        arms=[ArmConfig(id="reader", name="Reader", type="cli", capabilities=["read"])],
    )

    with pytest.raises(EmptyTrialPlanError, match="no arms"):
        plan_trial("T-EMPTY", "task", config, capability="compile")
    with pytest.raises(EmptyTrialPlanError, match="Unknown arm"):
        plan_trial("T-UNKNOWN", "task", config, arms_override=["missing"])

    assert not (tmp_path / "docs" / "trials" / "T-EMPTY").exists()
    assert not (tmp_path / "docs" / "trials" / "T-UNKNOWN").exists()


def test_shipped_preset_separates_lifecycle_from_editor_automation():
    config = CocktailConfig.load(PRESETS_DIR / "unity" / "manifest.json")
    by_id = {a.id: a for a in config.arms}

    assert "project-lifecycle" in by_id["rage-cli"].capabilities
    assert "editor-automation" not in by_id["rage-cli"].capabilities
    for arm_id in ("akiojin-cli", "youngwoo-cli", "hatayama-loop"):
        assert "editor-automation" in by_id[arm_id].capabilities

    untagged = [a.id for a in config.arms if not a.capabilities]
    assert not untagged, f"arms with no capabilities declared: {untagged}"


def test_shipped_preset_includes_computer_use_as_a_distinct_gui_arm():
    config = CocktailConfig.load(PRESETS_DIR / "unity" / "manifest.json")
    arm = next(a for a in config.arms if a.id == "computer-use")

    assert arm.type == "gui"
    assert arm.capabilities == ["editor-gui-automation", "visual-inspection"]
    assert arm.probe == "none"
    assert arm.health_check is None


def test_fabricated_arm_is_gone():
    """smithery-toolkit-mcp was invented in 0437026: its port sat in the 8084
    gap of a counted sequence, and no such project exists on Smithery, npm or
    GitHub. A survey entry nobody can obtain is not a survey entry."""
    config = CocktailConfig.load(PRESETS_DIR / "unity" / "manifest.json")
    ids = {a.id for a in config.arms}

    assert "smithery-toolkit-mcp" not in ids
    assert all("smithery" not in a.id for a in config.arms)
