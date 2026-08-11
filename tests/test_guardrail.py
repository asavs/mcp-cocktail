"""Tests for mcp_cocktail.guardrail module."""

import io
import json

from mcp_cocktail.config import TrapRule, TrapsConfig
from mcp_cocktail.guardrail import (
    build_hook_output,
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


def test_guardrail_selftest():
    res = selftest()
    assert res == 0


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
