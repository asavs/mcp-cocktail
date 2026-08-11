"""Tests for mcp_cocktail.installer module."""

import json
from pathlib import Path
import re

from mcp_cocktail.config import TrapsConfig
from mcp_cocktail.installer import (
    DEFAULT_HOOK_MATCHER,
    install_hook,
    uninstall_hook,
    load_json_file,
    detect_current_active_harness,
)


def _harness_would_invoke(matcher: str, tool_name: str) -> bool:
    """Model the harness-level tool-name filter applied before the hook runs."""
    if matcher in ("*", ""):
        return True
    return bool(re.match(f"(?:{matcher})$", tool_name))


def test_installed_matcher_reaches_every_shipped_rule(tmp_path: Path):
    """Every tool a rule declares must survive the harness matcher.

    Regression: the old default 'Bash|PowerShell|mcp__.*' stranded the P1
    manifest-while-running rule, whose tool_matcher declares Edit and Write.
    """
    settings_file = tmp_path / ".claude" / "settings.json"
    install_hook(harness="claude", target_path=str(settings_file))
    matcher = load_json_file(settings_file)["hooks"]["PreToolUse"][0]["matcher"]

    repo_root = Path(__file__).resolve().parents[1]
    traps = TrapsConfig.load(repo_root / "examples" / "unity" / ".agents" / "traps.json")
    assert traps.rules, "expected the Unity preset to ship rules"

    for tool in ("Bash", "PowerShell", "Edit", "Write", "mcp__UnityMCP__manage_gameobject"):
        assert _harness_would_invoke(matcher, tool), f"{matcher!r} strands rules targeting {tool}"


def test_default_matcher_subscribes_to_all_tools():
    assert DEFAULT_HOOK_MATCHER == "*"


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
