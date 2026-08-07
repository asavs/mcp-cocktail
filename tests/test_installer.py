"""Tests for mcp_cocktail.installer module."""

import json
from pathlib import Path
from mcp_cocktail.installer import install_hook, uninstall_hook, load_settings


def test_install_and_uninstall_hook(tmp_path: Path):
    settings_file = tmp_path / ".claude" / "settings.json"

    ok, msg = install_hook(target_path=str(settings_file))
    assert ok
    assert settings_file.exists()

    data = load_settings(settings_file)
    assert "hooks" in data
    assert "PreToolUse" in data["hooks"]
    pre = data["hooks"]["PreToolUse"]
    assert len(pre) == 1
    assert pre[0]["hooks"][0]["command"] == "mcp-cocktail check"

    # Second install - idempotent update
    ok2, msg2 = install_hook(target_path=str(settings_file))
    assert ok2
    data2 = load_settings(settings_file)
    assert len(data2["hooks"]["PreToolUse"][0]["hooks"]) == 1

    # Uninstall
    ok3, msg3 = uninstall_hook(target_path=str(settings_file))
    assert ok3
    data3 = load_settings(settings_file)
    assert len(data3["hooks"]["PreToolUse"]) == 0
