"""Generic PreToolUse guardrail and trap detection engine for mcp-cocktail."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from mcp_cocktail.config import TrapRule, TrapsConfig

READ_VERB = re.compile(
    r"^(?:git\s+(?:diff|log|status|show|check-attr|branch)|grep|rg|cat|head|tail|type|Get-Content|"
    r"ls|dir|Get-ChildItem|Test-Path|which|where|echo|findstr)\b",
    re.I,
)

TARGET_KEYS = ("command", "file_path", "path", "code")


def split_segments(command: str) -> list[str]:
    """Split shell command on `&&`, `||`, `|`, `;` respecting string quotes."""
    segments = []
    curr = []
    in_quote = None

    for char in command:
        if in_quote:
            curr.append(char)
            if char == in_quote:
                in_quote = None
        elif char in ('"', "'"):
            in_quote = char
            curr.append(char)
        elif char in (";", "|", "&"):
            if curr:
                seg = "".join(curr).strip()
                if seg:
                    segments.append(seg)
                curr = []
        else:
            curr.append(char)

    if curr:
        seg = "".join(curr).strip()
        if seg:
            segments.append(seg)

    return segments


def is_read_only(command: str) -> bool:
    """True when every segment of a shell command merely inspects."""
    segments = split_segments(command)
    return bool(segments) and all(READ_VERB.match(s) for s in segments)


def get_command_text(tool_input: dict[str, Any]) -> str:
    """Extract string payload across relevant target input keys."""
    parts = []
    for key in TARGET_KEYS:
        val = tool_input.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
    return "\n".join(parts)


def evaluate_rules(
    tool_name: str,
    tool_input: dict[str, Any],
    traps: TrapsConfig,
    state: dict[str, float],
    now: float | None = None,
) -> list[str]:
    """Evaluate active rules against a tool call and return messages to fire."""
    if now is None:
        now = time.time()

    cmd_text = get_command_text(tool_input)
    messages = []

    for rule in traps.rules:
        if rule.tool_matcher and not re.search(rule.tool_matcher, tool_name, re.I):
            continue

        if rule.target_matcher and not re.search(rule.target_matcher, cmd_text, re.I):
            continue

        if rule.read_only_ignore and is_read_only(cmd_text):
            continue

        last_fired = state.get(rule.id, 0.0)
        if rule.cooldown_seconds > 0 and (now - last_fired) < rule.cooldown_seconds:
            continue

        state[rule.id] = now
        msg = rule.message
        if rule.home_url:
            msg += f"\nReference: {rule.home_url}"
        messages.append(msg)

    return messages


def build_hook_output(messages: list[str]) -> dict[str, Any]:
    """Wrap fired trap messages in the PreToolUse hook envelope.

    Claude Code only reads `hookSpecificOutput.additionalContext` on exit 0;
    any other top-level key is written to the debug log and never reaches the
    model. See https://code.claude.com/docs/en/hooks.
    """
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": "\n\n".join(messages),
        }
    }


def get_state_path(session_id: str) -> Path:
    base = Path(os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp")
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "nosession")
    return base / f"mcp-cocktail-trap-check-{safe}.json"


def load_state(path: Path) -> dict[str, float]:
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_state(path: Path, state: dict[str, float]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass


def run_guardrail(traps_path: Path | str | None = None) -> int:
    """PreToolUse hook main execution entrypoint."""
    for stream in (sys.stdout, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore
        except (AttributeError, OSError):
            pass

    try:
        raw_in = sys.stdin.read()
        if not raw_in.strip():
            return 0
        data = json.loads(raw_in)
    except Exception:
        return 0

    tool_name = data.get("tool_name") or data.get("name", "")
    tool_input = data.get("tool_input") or data.get("input", {})
    session_id = os.environ.get("CLAUDE_SESSION_ID") or data.get("session_id", "nosession")

    traps = TrapsConfig.load(traps_path)
    state_file = get_state_path(session_id)
    state = load_state(state_file)

    now = time.time()
    fired_messages = evaluate_rules(tool_name, tool_input, traps, state, now)

    if fired_messages:
        save_state(state_file, state)
        print(json.dumps(build_hook_output(fired_messages), ensure_ascii=False))

    return 0


def selftest() -> int:
    """Built-in selftest for rule evaluation logic."""
    test_rules = TrapsConfig(
        version="1.0",
        domain="test",
        rules=[
            TrapRule(
                id="r1",
                tool_matcher="Bash|PowerShell",
                target_matcher="unity command",
                read_only_ignore=True,
                message="TRAP R1",
            ),
            TrapRule(
                id="r2",
                tool_matcher="mcp__.*",
                target_matcher="eval",
                read_only_ignore=False,
                message="TRAP R2",
            ),
        ],
    )

    state: dict[str, float] = {}
    now = 1000.0

    hits = evaluate_rules("Bash", {"command": "unity command --foo"}, test_rules, state, now)
    assert "TRAP R1" in hits, f"Expected R1 hit, got {hits}"

    hits = evaluate_rules("Bash", {"command": "git diff unity command"}, test_rules, state, now)
    assert not hits, f"Expected read-only ignore, got {hits}"

    hits = evaluate_rules("mcp__unity__eval", {"code": "eval()"}, test_rules, state, now)
    assert "TRAP R2" in hits, f"Expected R2 hit, got {hits}"

    print("Guardrail selftest PASSED.")
    return 0
