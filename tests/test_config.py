"""Tests for mcp_cocktail.config module."""

import json
from pathlib import Path
from mcp_cocktail.config import CocktailConfig, TrapsConfig, ArmConfig, TrapRule


def test_cocktail_config_defaults(tmp_path: Path):
    cfg = CocktailConfig.load(tmp_path)
    assert cfg.name == "default"
    assert cfg.arms == []


def test_cocktail_config_load(tmp_path: Path):
    manifest = {
        "name": "test-env",
        "description": "Test ecosystem",
        "arms": [
            {
                "id": "arm-1",
                "name": "Arm One",
                "type": "cli",
                "command": "test-cli",
                "env": {"FOO": "BAR"},
            }
        ],
        "trial_defaults": {"concurrency": "parallel", "timeout_seconds": 120},
    }
    manifest_path = tmp_path / "mcp-cocktail.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    cfg = CocktailConfig.load(tmp_path)
    assert cfg.name == "test-env"
    assert len(cfg.arms) == 1
    assert cfg.arms[0].id == "arm-1"
    assert cfg.arms[0].env == {"FOO": "BAR"}
    assert cfg.trial_defaults.concurrency == "parallel"
    assert cfg.trial_defaults.timeout_seconds == 120


def test_traps_config_load(tmp_path: Path):
    traps_data = {
        "version": "1.0",
        "domain": "test",
        "rules": [
            {
                "id": "rule-1",
                "message": "Trap 1 warning",
                "tool_matcher": "Bash",
                "target_matcher": "danger-cmd",
            }
        ],
    }
    traps_path = tmp_path / "traps.json"
    traps_path.write_text(json.dumps(traps_data), encoding="utf-8")

    traps = TrapsConfig.load(tmp_path)
    assert traps.domain == "test"
    assert len(traps.rules) == 1
    assert traps.rules[0].id == "rule-1"
    assert traps.rules[0].message == "Trap 1 warning"
