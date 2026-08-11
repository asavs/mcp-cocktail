"""Tests for mcp_cocktail.doctor module."""

from pathlib import Path

from mcp_cocktail.config import CocktailConfig, ArmConfig
from mcp_cocktail.doctor import run_doctor, probe_cli_arm, probe_mcp_arm

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
    assert "not found in PATH" in probe_mcp_arm(wrapped).message

    bare = ArmConfig(id="bare", name="Bare", type="mcp", mcp_server="SomeRegistryKey",
                     health_check="http://127.0.0.1:59999/health")
    assert "unreachable at" in probe_mcp_arm(bare).message


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
