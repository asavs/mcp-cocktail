"""Tests for mcp_cocktail.doctor module."""

from mcp_cocktail.config import CocktailConfig, ArmConfig
from mcp_cocktail.doctor import run_doctor, probe_cli_arm, probe_mcp_arm


def test_probe_cli_arm_offline():
    arm = ArmConfig(id="nonexistent-cli", name="Fake CLI", type="cli", command="nonexistent_binary_xyz_123")
    res = probe_cli_arm(arm)
    assert res.status == "OFFLINE"


def test_probe_mcp_arm_offline():
    arm = ArmConfig(id="fake-mcp", name="Fake MCP", type="mcp", health_check="curl -s http://127.0.0.1:59999/health")
    res = probe_mcp_arm(arm)
    assert res.status == "OFFLINE"


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
