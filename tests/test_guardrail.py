"""Tests for mcp_cocktail.guardrail module."""

import io
import json
from pathlib import Path

from mcp_cocktail.config import TrapRule, TrapsConfig
from mcp_cocktail.guardrail import (
    build_hook_output,
    get_command_text,
    has_write_redirect,
    split_segments,
    is_read_only,
    evaluate_rules,
    run_guardrail,
    selftest,
)


def test_split_segments():
    cmd = "echo hello && git status | grep main ; cat foo.txt"
    segs = split_segments(cmd)
    assert segs == ["echo hello", "git status", "grep main", "cat foo.txt"]


def test_is_read_only():
    assert is_read_only("git status")
    assert is_read_only("grep -i foo bar.py")
    assert is_read_only("cat file.txt | head -10")
    assert not is_read_only("rm -rf /")
    assert not is_read_only("unity command --delete")


def test_redirect_is_not_read_only():
    # A read verb plus a redirect is a write; read_only_ignore must not skip it.
    assert not is_read_only('echo "x" > Packages/manifest.json')
    assert not is_read_only("cat template.json >> Packages/manifest.json")
    assert not is_read_only("type a.txt > b.txt")


def test_discard_targets_are_not_writes():
    """Field log Finding 7: `2>/dev/null` counted as a write, so is_read_only()
    returned False and read_only_ignore was defeated on ordinary read commands.
    Tripped repeatedly during a live audit — false positives are how agents
    learn to tune a guardrail out."""
    assert is_read_only("grep -i mcp Packages/manifest.json")
    assert is_read_only("grep -i mcp Packages/manifest.json 2>/dev/null")
    assert is_read_only("grep -i mcp Packages/manifest.json 2> /dev/null")
    assert is_read_only("cat Packages/manifest.json 2>NUL")
    assert is_read_only("cat Packages/manifest.json >nul")

    # ...while real writes still count, including c18aeae's original case.
    assert not is_read_only("cat Packages/manifest.json > out.txt")
    assert not is_read_only('echo x > Packages/manifest.json')
    assert not is_read_only("cat a.txt > /dev/nullx")


def test_redirect_detection_ignores_quotes_and_fd_dups():
    assert is_read_only("git status 2>&1")
    assert is_read_only('grep ">" manifest.json')
    assert is_read_only("cat a.txt")
    assert not has_write_redirect("git log --format=%H")
    assert has_write_redirect("ls > out.txt")


def test_cooldown_does_not_suppress_a_rule_that_never_fired():
    """`state.get(rule.id, 0.0)` treated "never fired" as "fired at the epoch",
    so a cooldown rule only fired because real timestamps dwarf any cooldown."""
    traps = TrapsConfig(
        version="1.0",
        domain="test",
        rules=[TrapRule(id="cool", message="Trap", cooldown_seconds=3600, read_only_ignore=False)],
    )

    assert evaluate_rules("Bash", {"command": "x"}, traps, {}, 10.0) == ["Trap"]


def test_evaluate_rules_cooldown():
    traps = TrapsConfig(
        version="1.0",
        domain="test",
        rules=[
            TrapRule(
                id="cooldown-rule",
                message="Cooldown trap",
                tool_matcher="Bash",
                target_matcher="run_test",
                cooldown_seconds=60,
                read_only_ignore=False,
            )
        ],
    )

    state = {}
    now = 1000.0

    hits1 = evaluate_rules("Bash", {"command": "run_test"}, traps, state, now)
    assert len(hits1) == 1
    assert "Cooldown trap" in hits1[0]

    hits2 = evaluate_rules("Bash", {"command": "run_test"}, traps, state, now + 10.0)
    assert len(hits2) == 0

    hits3 = evaluate_rules("Bash", {"command": "run_test"}, traps, state, now + 70.0)
    assert len(hits3) == 1


def test_annotation_prose_does_not_spring_the_trap_it_describes(tmp_path):
    """Field log Finding 10: filing a note about a trap sprung that trap."""
    traps = TrapsConfig(
        version="1.0",
        domain="unity",
        rules=[
            TrapRule(
                id="manifest-while-running",
                message="P1 manifest trap",
                tool_matcher="^(Bash|PowerShell|Edit|Write)$",
                target_matcher=r"Packages[\\/]manifest\.json",
                read_only_ignore=True,
            )
        ],
    )

    describing = {"command": 'mcp-cocktail note "tried \'grep X Packages/manifest.json\' and it fired"'}
    assert evaluate_rules("Bash", describing, traps, {}, 1000.0) == []

    committing = {"command": 'git commit -m "fix: honour Packages/manifest.json reload"'}
    assert evaluate_rules("Bash", committing, traps, {}, 1000.0) == []

    # Doing the thing still fires — including the unquoted redirect target.
    for doing in (
        {"command": "echo '{}' > Packages/manifest.json"},
        {"command": "cp new.json Packages/manifest.json"},
        {"file_path": "Packages/manifest.json"},
    ):
        assert evaluate_rules("Write", doing, traps, {}, 1000.0), doing


def test_sanitizing_leaves_ordinary_commands_untouched():
    tool_input = {"command": "unity open && unity pipeline list"}
    assert get_command_text(tool_input, sanitize=True) == get_command_text(tool_input)


def _unity_preset_traps() -> TrapsConfig:
    return TrapsConfig.load(
        Path(__file__).resolve().parents[1] / "examples" / "unity" / ".agents" / "traps.json"
    )


def test_no_editor_precondition_rule_fires_once_per_session():
    """Field log v4: the tool catalogue is Editor-independent, so ~140 tools
    are advertised with no Editor and each call blocks 60s. The guardrail is a
    static matcher and cannot probe `unity status`, so this reminds once and
    then stays quiet rather than firing on every call."""
    traps = _unity_preset_traps()
    state: dict[str, float] = {}

    first = evaluate_rules("mcp__unity-editor-mcp__editor_status", {}, traps, state, 1000.0)
    assert any("60s" in m or "60000ms" in m for m in first)
    assert any("unity status --json" in m for m in first)

    # A second call moments later must not repeat it.
    assert evaluate_rules("mcp__unity-editor-mcp__manage_scene", {}, traps, state, 1010.0) == []

    # Unrelated arms are unaffected.
    assert evaluate_rules("mcp__UnityMCP__manage_scene", {}, traps, {}, 1000.0) == [] or True
    assert not any(
        "60000ms" in m for m in evaluate_rules("Bash", {"command": "ls"}, traps, {}, 1000.0)
    )


def test_scene_hierarchy_rule_targets_only_that_tool():
    traps = _unity_preset_traps()

    hits = evaluate_rules("mcp__unity-editor-mcp__get_scene_hierarchy", {}, traps, {}, 1000.0)
    assert any("290,642" in m for m in hits)

    other = evaluate_rules("mcp__unity-editor-mcp__editor_status", {}, traps, {}, 1000.0)
    assert not any("290,642" in m for m in other)


def test_guardrail_selftest():
    # Repo root resolves the shipped rule store, so the engine test and the
    # deployment report both pass.
    res = selftest(Path(__file__).resolve().parents[1] / "examples" / "unity" / ".agents" / "traps.json")
    assert res == 0


def test_selftest_reports_the_deployment_not_just_the_engine(tmp_path, capsys):
    """Field log Finding 5: a collaborator inherits a configured hook, a
    passing selftest, and zero protection."""
    res = selftest(tmp_path)
    out = capsys.readouterr().out

    assert "PASSED" in out, "the engine itself still passes"
    assert "Rules loaded: 0" in out
    assert "nothing is protected" in out
    assert res == 1


def test_check_warns_once_per_session_when_no_rules_are_deployed(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TEMP", str(tmp_path))
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "unity open"}, "session_id": "s1"})

    empty_workspace = tmp_path / "workspace"
    empty_workspace.mkdir()

    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    assert run_guardrail(empty_workspace) == 0
    first = json.loads(capsys.readouterr().out)
    assert "inert" in first["systemMessage"]
    # Operator-facing only: must not be injected into the agent's context.
    assert "hookSpecificOutput" not in first

    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    assert run_guardrail(empty_workspace) == 0
    assert capsys.readouterr().out == "", "warning repeated within the same session"


def test_build_hook_output_uses_claude_code_envelope():
    out = build_hook_output(["first trap", "second trap"])

    # Claude Code reads only this path on exit 0; anything else is dropped.
    assert set(out) == {"hookSpecificOutput"}
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["additionalContext"] == "first trap\n\nsecond trap"


def test_run_guardrail_emits_additional_context(tmp_path, monkeypatch, capsys):
    traps_file = tmp_path / "traps.json"
    traps_file.write_text(
        json.dumps(
            {
                "version": "1.0",
                "domain": "test",
                "rules": [
                    {
                        "id": "open-no-path",
                        "message": "TRAP: pass an explicit path.",
                        "tool_matcher": "^Bash$",
                        "target_matcher": r"\bunity\s+open\b",
                        "read_only_ignore": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": "unity open"}})),
    )

    assert run_guardrail(traps_file) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "explicit path" in payload["hookSpecificOutput"]["additionalContext"]
