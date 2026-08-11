"""Tests for mcp_cocktail.doctor module."""

import json
from pathlib import Path

from mcp_cocktail.config import CocktailConfig, ArmConfig
from mcp_cocktail.doctor import (
    check_arm_binding,
    extract_json_path,
    run_doctor,
    probe_cli_arm,
    probe_mcp_arm,
    resolve_probe_binary,
)

PRESETS_DIR = Path(__file__).resolve().parents[1] / "examples"


def test_probe_cli_arm_offline():
    arm = ArmConfig(id="nonexistent-cli", name="Fake CLI", type="cli", command="nonexistent_binary_xyz_123")
    res = probe_cli_arm(arm)
    assert res.status == "OFFLINE"


def test_probe_mcp_arm_offline():
    arm = ArmConfig(id="fake-mcp", name="Fake MCP", type="mcp", health_check="http://127.0.0.1:59999/health")
    res = probe_mcp_arm(arm)
    assert res.status == "OFFLINE"
    # Routed through the HTTP probe, not the PATH gate.
    assert "unreachable at http://127.0.0.1:59999/health" in res.message


def test_shell_wrapped_url_never_reaches_the_http_probe():
    """Why bare URLs are mandatory in presets.

    probe_mcp_arm dispatches on hc.startswith("http"), so a URL wrapped in a
    shell command silently falls through to the PATH gate and reports a
    misleading 'not found in PATH' instead of the real connection verdict.
    """
    wrapped = ArmConfig(id="wrapped", name="Wrapped", type="mcp", mcp_server="SomeRegistryKey",
                        health_check="curl -s http://127.0.0.1:59999/health")
    wrapped_res = probe_mcp_arm(wrapped)
    assert "unreachable at" not in wrapped_res.message
    assert wrapped_res.status != "SOCKET_BOUND_ONLY"

    bare = ArmConfig(id="bare", name="Bare", type="mcp", mcp_server="SomeRegistryKey",
                     health_check="http://127.0.0.1:59999/health")
    assert "unreachable at" in probe_mcp_arm(bare).message


def test_failed_health_check_is_offline_not_ready():
    """A health check that runs and fails must not fall through to
    'executable found in PATH'. Surfaced by repairing the probe binary
    resolver: once the health_check's own binary is resolvable, a failing
    check reached the trailing READY and green-lit a dead arm."""
    arm = ArmConfig(id="failing", name="Failing", type="cli",
                    health_check="python -c \"import sys; sys.exit(3)\"")
    res = probe_cli_arm(arm)
    assert res.status == "OFFLINE"
    assert "exit 3" in res.message


def test_silent_success_still_counts_as_ready():
    arm = ArmConfig(id="quiet", name="Quiet", type="cli", health_check="python -c \"pass\"")
    assert probe_cli_arm(arm).status == "READY"


def test_probe_binary_comes_from_the_health_check_not_the_arm_identity():
    """Regression: official-unity-mcp declares health_check 'unity status --json'
    but has no `command`, so the probe resolved mcp_server='unity-editor-mcp' --
    a harness registry key -- and reported OFFLINE while the arm was serving
    140 tools."""
    mcp_arm = ArmConfig(id="official-unity-mcp", name="Official Unity MCP", type="mcp",
                        mcp_server="unity-editor-mcp", health_check="unity status --json")
    assert resolve_probe_binary(mcp_arm) == "unity"

    # An explicit command still wins when no shell health_check names a binary.
    no_hc = ArmConfig(id="some-cli", name="Some CLI", type="cli", command="unity-cli-rust")
    assert resolve_probe_binary(no_hc) == "unity-cli-rust"

    # A URL health_check names no binary; fall back to identity.
    http_arm = ArmConfig(id="coplay-mcp", name="Coplay", type="mcp", mcp_server="UnityMCP",
                         health_check="http://127.0.0.1:8080/mcp")
    assert resolve_probe_binary(http_arm) == "UnityMCP"


UNITY_STATUS = json.dumps({
    "success": True,
    "data": {"count": 1, "instances": [
        {"port": 7800, "project": r"C:\work\gabe", "version": "6000.5.5f1", "pid": 1416, "state": "ready"}
    ]},
})


def test_extract_json_path_maps_over_lists():
    payload = json.loads(UNITY_STATUS)
    assert extract_json_path(payload, "data.instances[].project") == [r"C:\work\gabe"]
    assert extract_json_path(payload, "data.instances[].port") == [7800]
    assert extract_json_path(payload, "data.nope[].project") == []


def test_binding_check_flags_an_arm_serving_another_project(tmp_path):
    """Field log Finding 3: the MCP arm was registered at user scope against
    HelloUnity while all work was in gabe, and every liveness check said
    'Connected'. Bound is not the same claim as bound to your thing."""
    arm = ArmConfig(id="unity", name="Unity", type="cli", command="unity",
                    health_check="unity status --json",
                    binding_path="data.instances[].project")

    elsewhere = check_arm_binding(arm, UNITY_STATUS, tmp_path / "other-project")
    assert elsewhere is not None
    assert elsewhere.status == "BOUND_ELSEWHERE"
    assert r"C:\work\gabe" in elsewhere.message

    # Correctly bound -> no complaint.
    assert check_arm_binding(arm, UNITY_STATUS, Path(r"C:\work\gabe")) is None

    # No binding_path declared, or unparseable output -> check does not apply.
    silent = ArmConfig(id="unity", name="Unity", type="cli", health_check="unity status --json")
    assert check_arm_binding(silent, UNITY_STATUS, tmp_path) is None
    assert check_arm_binding(arm, "not json", tmp_path) is None


def test_unity_preset_declares_a_binding_for_project_scoped_arms():
    arms = {a.id: a for a in CocktailConfig.load(PRESETS_DIR / "unity" / ".agents" / "manifest.json").arms}
    for arm_id in ("official-unity-cli", "official-unity-mcp"):
        assert arms[arm_id].binding_path == "data.instances[].project"


def test_shipped_presets_state_urls_bare():
    """Regression: every arm in the Unity preset wrapped its URL in `curl -s`,
    so 11/11 arms took probe_cli_arm and the HTTP + stdio branches were dead
    code. SOCKET_BOUND_ONLY (P4) was unreachable."""
    manifests = sorted(PRESETS_DIR.glob("*/.agents/manifest.json"))
    assert manifests, "expected at least one shipped preset"

    for manifest in manifests:
        for arm in CocktailConfig.load(manifest).arms:
            hc = (arm.health_check or "").strip()
            if "http://" in hc or "https://" in hc:
                assert hc.startswith(("http://", "https://")), (
                    f"{manifest.parent.parent.name}/{arm.id}: health_check wraps a URL in a shell "
                    f"command ({hc!r}); doctor will take the PATH gate instead of the HTTP probe"
                )


def test_run_doctor():
    cfg = CocktailConfig(
        name="doctor-test",
        description="Doctor testing",
        arms=[
            ArmConfig(id="python-cli", name="Python CLI", type="cli", command="python"),
            ArmConfig(id="fake-mcp", name="Fake MCP", type="mcp", health_check="http://127.0.0.1:59999/health"),
        ],
    )

    results = run_doctor(cfg)
    assert len(results) == 2
    assert results[0].status == "READY"
    assert results[1].status == "OFFLINE"
