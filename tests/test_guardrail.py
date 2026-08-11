"""Tests for mcp_cocktail.guardrail module."""

import io
import json

from mcp_cocktail.config import TrapRule, TrapsConfig
from mcp_cocktail.guardrail import (
    build_hook_output,
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
