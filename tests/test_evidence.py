"""Operational evidence journal tests."""

from datetime import datetime, timezone

from mcp_cocktail.config import ArmConfig, CocktailConfig
from mcp_cocktail.doctor import (
    ArmHealthResult, apply_recent_health_observation, capability_health_results,
)
from mcp_cocktail.evidence import append_operational_observation, load_operational_observations


def observation(arm: str, outcome: str, stamp: str) -> dict:
    return {
        "arm": arm,
        "capability": "editor-read",
        "layer": "target_operation",
        "operation": "read_console",
        "outcome": outcome,
        "observed_at": stamp,
    }


def test_journal_appends_without_losing_previous_observations(tmp_path):
    append_operational_observation(tmp_path, observation("a", "succeeded", "2026-08-12T19:00:00Z"))
    append_operational_observation(tmp_path, observation("b", "timed_out", "2026-08-12T19:00:01Z"))
    assert [item["arm"] for item in load_operational_observations(tmp_path)] == ["a", "b"]


def test_corrupt_journal_is_tolerated_and_replaced_atomically(tmp_path):
    path = tmp_path / ".agents" / "health-observations.json"
    path.parent.mkdir()
    path.write_text("not json", encoding="utf-8")
    assert load_operational_observations(tmp_path) == []
    append_operational_observation(tmp_path, observation("a", "failed", "2026-08-12T19:00:00Z"))
    assert load_operational_observations(tmp_path)[0]["arm"] == "a"


def test_recent_execution_timeout_overrides_transport_only(tmp_path):
    now = datetime(2026, 8, 12, 19, 0, 30, tzinfo=timezone.utc).timestamp()
    item = observation("coplay", "timed_out", "2026-08-12T19:00:00Z")
    item["project_identity"] = str(tmp_path)
    append_operational_observation(tmp_path, item)
    shallow = ArmHealthResult("coplay", "Coplay", "TRANSPORT_ONLY", "initialize worked", {})
    result = apply_recent_health_observation(shallow, tmp_path, now=now)
    assert result.status == "DEGRADED"
    assert "30s ago" in result.message


def test_newer_transport_success_does_not_erase_target_timeout(tmp_path):
    now = datetime(2026, 8, 12, 19, 0, 30, tzinfo=timezone.utc).timestamp()
    failed = observation("coplay", "timed_out", "2026-08-12T19:00:00Z")
    failed["project_identity"] = str(tmp_path)
    append_operational_observation(tmp_path, failed)
    transport = observation("coplay", "succeeded", "2026-08-12T19:00:20Z")
    transport.update({"layer": "transport", "operation": "initialize"})
    append_operational_observation(tmp_path, transport)

    shallow = ArmHealthResult("coplay", "Coplay", "TRANSPORT_ONLY", "initialize worked", {})
    assert apply_recent_health_observation(shallow, tmp_path, now=now).status == "DEGRADED"


def test_operational_probe_is_not_overridden_by_older_failure(tmp_path):
    append_operational_observation(tmp_path, observation("coplay", "failed", "2026-08-12T19:00:00Z"))
    operational = ArmHealthResult("coplay", "Coplay", "OPERATIONAL", "target answered", {})
    assert apply_recent_health_observation(operational, tmp_path).status == "OPERATIONAL"


def test_capability_health_requires_fresh_same_project_evidence(tmp_path):
    config = CocktailConfig(
        name="unity", description="", root_dir=tmp_path,
        arms=[ArmConfig(id="coplay", name="Coplay", type="mcp", capabilities=["editmode-tests"])],
    )
    item = observation("coplay", "succeeded", "2026-08-12T19:00:00Z")
    item.update({"capability": "editmode-tests", "project_identity": str(tmp_path)})
    append_operational_observation(tmp_path, item)
    now = datetime(2026, 8, 12, 19, 0, 30, tzinfo=timezone.utc).timestamp()

    base = [ArmHealthResult("coplay", "Coplay", "TRANSPORT_ONLY", "MCP initialized", {})]
    result = capability_health_results(config, base, "editmode-tests", now=now)[0]

    assert result.status == "EXECUTION_REPORTED"
    assert result.details["age_seconds"] == 30


def test_capability_success_cannot_override_current_offline_arm(tmp_path):
    config = CocktailConfig(
        name="unity", description="", root_dir=tmp_path,
        arms=[ArmConfig(id="coplay", name="Coplay", type="mcp", capabilities=["tests"])],
    )
    item = observation("coplay", "succeeded", "2026-08-12T19:00:00Z")
    item.update({"capability": "tests", "project_identity": str(tmp_path)})
    append_operational_observation(tmp_path, item)
    base = [ArmHealthResult("coplay", "Coplay", "OFFLINE", "server is down", {})]
    now = datetime(2026, 8, 12, 19, 0, 30, tzinfo=timezone.utc).timestamp()

    result = capability_health_results(config, base, "tests", now=now)[0]

    assert result.status == "OFFLINE"
    assert result.details["base_status"] == "OFFLINE"


def test_wrong_project_capability_observations_are_ignored_even_when_newer(tmp_path):
    config = CocktailConfig(
        name="unity", description="", root_dir=tmp_path,
        arms=[ArmConfig(id="coplay", name="Coplay", type="mcp", capabilities=["tests"])],
    )
    correct = observation("coplay", "succeeded", "2026-08-12T19:00:00Z")
    correct.update({"capability": "tests", "project_identity": str(tmp_path)})
    wrong = observation("coplay", "timed_out", "2026-08-12T19:00:20Z")
    wrong.update({"capability": "tests", "project_identity": str(tmp_path / "other")})
    append_operational_observation(tmp_path, correct)
    append_operational_observation(tmp_path, wrong)
    base = [ArmHealthResult("coplay", "Coplay", "TRANSPORT_ONLY", "up", {})]
    now = datetime(2026, 8, 12, 19, 0, 30, tzinfo=timezone.utc).timestamp()

    result = capability_health_results(config, base, "tests", now=now)[0]

    assert result.status == "EXECUTION_REPORTED"
    assert result.details["observation"]["project_identity"] == str(tmp_path)


def test_capability_only_becomes_operational_from_independent_doctor_probe(tmp_path):
    config = CocktailConfig(
        name="unity", description="", root_dir=tmp_path,
        arms=[ArmConfig(id="coplay", name="Coplay", type="mcp", capabilities=["tests"])],
    )
    item = observation("coplay", "succeeded", "2026-08-12T19:00:00Z")
    item.update({
        "capability": "tests", "project_identity": str(tmp_path),
        "operation": "doctor", "classification": "OPERATIONAL",
    })
    append_operational_observation(tmp_path, item)
    base = [ArmHealthResult("coplay", "Coplay", "OPERATIONAL", "live target probe", {})]
    now = datetime(2026, 8, 12, 19, 0, 30, tzinfo=timezone.utc).timestamp()

    assert capability_health_results(config, base, "tests", now=now)[0].status == "OPERATIONAL"


def test_future_capability_evidence_does_not_earn_operational(tmp_path):
    config = CocktailConfig(
        name="unity", description="", root_dir=tmp_path,
        arms=[ArmConfig(id="coplay", name="Coplay", type="mcp", capabilities=["tests"])],
    )
    future = observation("coplay", "succeeded", "2026-08-12T20:00:00Z")
    future.update({"capability": "tests", "project_identity": str(tmp_path)})
    append_operational_observation(tmp_path, future)
    base = [ArmHealthResult("coplay", "Coplay", "TRANSPORT_ONLY", "up", {})]
    now = datetime(2026, 8, 12, 19, 0, 0, tzinfo=timezone.utc).timestamp()

    result = capability_health_results(config, base, "tests", now=now)[0]

    assert result.status == "CAPABILITY_UNKNOWN"
