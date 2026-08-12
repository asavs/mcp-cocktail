import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_cocktail.config import ArmConfig, CocktailConfig
from mcp_cocktail.lifecycle import LifecycleError, TrialLifecycle
from mcp_cocktail.runner import plan_trial
from mcp_cocktail.trial_state import LeaseBusyError


def planned(tmp_path: Path) -> TrialLifecycle:
    config = CocktailConfig(
        name="unity", description="", root_dir=tmp_path,
        arms=[ArmConfig(
            id="coplay", name="Coplay", type="mcp",
            capabilities=["editor-automation"],
        )],
    )
    plan_trial("T-LIFE", "mutate safely", config)
    return TrialLifecycle(tmp_path, "T-LIFE")


def test_lifecycle_enforces_lease_and_records_stage_evidence(tmp_path: Path):
    lifecycle = planned(tmp_path)
    holder = lifecycle.acquire("adapter-a")

    with pytest.raises(LeaseBusyError):
        lifecycle.begin("arm-coplay", "coplay", "adapter-b", "wrong")

    lifecycle.begin("arm-coplay", "coplay", "adapter-a", holder["token"])
    (tmp_path / "Assets").mkdir()
    (tmp_path / "Assets" / "result.txt").write_text("done", encoding="utf-8")
    result = lifecycle.finish(
        "arm-coplay", "coplay", "adapter-a", holder["token"], "succeeded",
        evidence=[{"kind": "readback", "summary": "visible and parsed"}],
        artifacts=[{"uri": "Assets/result.txt", "producer_arm": "coplay"}],
    )
    lifecycle.release("adapter-a", holder["token"])

    stage = result["state"]["stages"][0]
    assert stage["outcome"] == "succeeded"
    assert stage["attempts"][0]["evidence"][0]["kind"] == "readback"
    assert "Assets/result.txt" in result["workspace_delta"]["added"]
    observations = json.loads(
        (tmp_path / ".agents" / "health-observations.json").read_text("utf-8")
    )["observations"]
    assert observations[-1]["outcome"] == "succeeded"


def test_open_circuit_prevents_begin(tmp_path: Path):
    lifecycle = planned(tmp_path)
    holder = lifecycle.acquire("adapter")
    state_path = lifecycle.trial_dir / "trial-state.json"
    state = json.loads(state_path.read_text("utf-8"))
    state["circuits"]["coplay:editor-automation"] = {
        "state": "open", "arm": "coplay", "capability": "editor-automation",
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(ValueError, match="Circuit is open"):
        lifecycle.begin("arm-coplay", "coplay", "adapter", holder["token"])

    lifecycle.release("adapter", holder["token"])


def test_running_stage_pins_lease_and_duplicate_finish_is_rejected(tmp_path: Path):
    lifecycle = planned(tmp_path)
    holder = lifecycle.acquire("adapter")
    lifecycle.begin("arm-coplay", "coplay", "adapter", holder["token"])

    with pytest.raises(LifecycleError, match="while stages are running"):
        lifecycle.release("adapter", holder["token"])

    lifecycle.finish(
        "arm-coplay", "coplay", "adapter", holder["token"], "failed", error="tool error"
    )
    with pytest.raises(ValueError, match="not running"):
        lifecycle.finish(
            "arm-coplay", "coplay", "adapter", holder["token"], "failed", error="again"
        )
    lifecycle.release("adapter", holder["token"])


def test_journal_failure_leaves_retryable_outbox(tmp_path: Path):
    lifecycle = planned(tmp_path)
    holder = lifecycle.acquire("adapter")
    lifecycle.begin("arm-coplay", "coplay", "adapter", holder["token"])

    with patch("mcp_cocktail.trial_state.append_operational_observation", side_effect=OSError("disk")):
        result = lifecycle.finish(
            "arm-coplay", "coplay", "adapter", holder["token"], "failed", error="tool error"
        )
    assert result["state"]["journal_pending"]

    assert lifecycle.inspect()["state"]["journal_pending"] == []
    lifecycle.release("adapter", holder["token"])
