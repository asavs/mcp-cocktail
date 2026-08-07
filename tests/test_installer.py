"""Tests for mcp_cocktail.installer module."""

import json
from pathlib import Path
from mcp_cocktail.installer import (
    install_hook,
    uninstall_hook,
    load_json_file,
    detect_current_active_harness,
)


def test_install_and_uninstall_hook(tmp_path: Path):
    settings_file = tmp_path / ".claude" / "settings.json"

    ok, msg = install_hook(harness="claude", target_path=str(settings_file))
    assert ok
    assert settings_file.exists()

    data = load_json_file(settings_file)
    assert "hooks" in data
    assert "PreToolUse" in data["hooks"]
    pre = data["hooks"]["PreToolUse"]
    assert len(pre) == 1
    assert pre[0]["hooks"][0]["command"] == "mcp-cocktail check"

    # Second install - idempotent update
    ok2, msg2 = install_hook(harness="claude", target_path=str(settings_file))
    assert ok2
    data2 = load_json_file(settings_file)
    assert len(data2["hooks"]["PreToolUse"][0]["hooks"]) == 1

    # Uninstall
    ok3, msg3 = uninstall_hook(harness="claude", target_path=str(settings_file))
    assert ok3
    data3 = load_json_file(settings_file)
    assert len(data3["hooks"]["PreToolUse"]) == 0


def test_detect_current_active_harness(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OMP_SESSION_ID", "sess_123")
    assert detect_current_active_harness(tmp_path) == "omp"

    monkeypatch.delenv("OMP_SESSION_ID", raising=False)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "sess_456")
    assert detect_current_active_harness(tmp_path) == "claude"
