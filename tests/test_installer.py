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


def _cocktail_hooks(settings_file: Path) -> list[dict]:
    return [
        hook
        for entry in load_json_file(settings_file)["hooks"]["PreToolUse"]
        for hook in entry.get("hooks", [])
        if "cocktail check" in hook.get("command", "")
    ]


def test_install_replaces_a_hook_carried_by_a_different_matcher(tmp_path: Path):
    """Field log Finding 6: setup appended a second PreToolUse entry instead of
    repairing the first, and every tool call produced two identical reminders."""
    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash|PowerShell|Edit|Write|mcp__unity-editor-mcp__.*",
                            "hooks": [{"type": "command", "command": "python -m mcp_cocktail check"}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    ok, msg = install_hook(harness="claude", target_path=str(settings_file))
    assert ok
    assert "Replaced 1 existing" in msg
    assert len(_cocktail_hooks(settings_file)) == 1, "duplicate hook -> duplicate context injection"


def test_install_preserves_unrelated_hooks(tmp_path: Path):
    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {"matcher": "Bash", "hooks": [{"type": "command", "command": "some-other-linter"}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    install_hook(harness="claude", target_path=str(settings_file))
    commands = [
        h.get("command")
        for entry in load_json_file(settings_file)["hooks"]["PreToolUse"]
        for h in entry.get("hooks", [])
    ]
    assert "some-other-linter" in commands
    assert len(_cocktail_hooks(settings_file)) == 1


def test_traps_path_is_portable(tmp_path: Path, monkeypatch):
    """An absolute path bakes one machine's drive layout into the file the
    README tells teams to commit."""
    monkeypatch.chdir(tmp_path)
    traps = tmp_path / ".agents" / "traps.json"
    traps.parent.mkdir(parents=True)
    traps.write_text("{}", encoding="utf-8")

    settings_file = tmp_path / ".claude" / "settings.json"
    install_hook(harness="claude", target_path=str(settings_file), custom_traps=str(traps))

    command = _cocktail_hooks(settings_file)[0]["command"]
    assert command == 'mcp-cocktail check --traps "$CLAUDE_PROJECT_DIR/.agents/traps.json"'
    assert str(tmp_path) not in command


def test_traps_path_outside_project_stays_absolute(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "shared" / "traps.json"
    external.parent.mkdir(parents=True)
    external.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(project)

    settings_file = project / ".claude" / "settings.json"
    install_hook(harness="claude", target_path=str(settings_file), custom_traps=str(external))
    assert str(external) in _cocktail_hooks(settings_file)[0]["command"]


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
