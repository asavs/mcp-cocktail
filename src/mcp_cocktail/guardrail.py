"""Generic PreToolUse guardrail and trap detection engine for mcp-cocktail."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from mcp_cocktail.config import TrapRule, TrapsConfig, resolve_traps_path

# Reserved state key; rule ids never collide because they are matched literally.
NO_STORE_WARNED = "__mcp_cocktail_no_rule_store_warned__"

READ_VERB = re.compile(
    r"^(?:git\s+(?:diff|log|status|show|check-attr|branch)|grep|rg|cat|head|tail|type|Get-Content|"
    r"ls|dir|Get-ChildItem|Test-Path|which|where|echo|findstr)\b",
    re.I,
)

TARGET_KEYS = ("command", "file_path", "path", "code")

# Commands whose quoted arguments are prose to be recorded, not operands to be
# acted on. A trap describes a filesystem effect; writing *about* the trap has
# none, so the quoted payload must not be scanned for trap patterns.
ANNOTATION_VERB = re.compile(
    r"^(?:mcp-?cocktail\s+(?:note|upstream)"
    r"|git\s+commit"
    r"|gh\s+(?:issue|pr)\s+(?:create|comment)"
    r"|echo)\b",
    re.I,
)

QUOTED_LITERAL = re.compile(r"'[^']*'|\"[^\"]*\"")


def strip_annotation_payloads(command: str) -> str:
    """Blank the quoted prose of annotation commands before rule matching.

    `mcp-cocktail note "... Packages/manifest.json ..."` tripped the
    manifest-while-running trap: filing a finding about a trap sprung it.
    Unquoted text is untouched, so `echo x > Packages/manifest.json` still
    matches on the redirect target.
    """
    segments = split_segments(command)
    if not any(ANNOTATION_VERB.match(s) for s in segments):
        return command  # overwhelmingly the common case; leave it byte-identical

    return "\n".join(
        QUOTED_LITERAL.sub(" ", s) if ANNOTATION_VERB.match(s) else s for s in segments
    )


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
        elif char == "&" and curr and curr[-1] == ">":
            # File-descriptor duplication (`2>&1`), not a command separator.
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


# Redirect targets that discard rather than persist. Bare `nul` is the Windows
# device and is case-insensitive; `/dev/null` is not.
DISCARD_TARGETS = {"/dev/null", "nul", "nul:"}

_TOKEN_END = set(" \t;|&<>")


def _redirect_target(command: str, gt_index: int) -> str:
    """Read the destination token following a `>` at `gt_index`."""
    i = gt_index + 1
    while i < len(command) and command[i] == ">":
        i += 1
    while i < len(command) and command[i] in " \t":
        i += 1

    start = i
    while i < len(command) and command[i] not in _TOKEN_END:
        i += 1

    return command[start:i].strip("\"'")


def has_write_redirect(command: str) -> bool:
    """True when the command redirects output into a file that persists.

    Scanned over the whole command rather than per-segment, because
    `split_segments` breaks on `&` and would tear `2>&1` in half. Quoted `>`
    is literal text; `>&` duplicates a file descriptor; `>` onto a null device
    discards; `<` only reads. None of those are writes.
    """
    in_quote = None

    for i, char in enumerate(command):
        if in_quote:
            if char == in_quote:
                in_quote = None
        elif char in ('"', "'"):
            in_quote = char
        elif char == ">":
            target = _redirect_target(command, i)
            if not target:
                continue  # `2>&1` and friends: `&` terminates the token, nothing is written
            if target.casefold() in DISCARD_TARGETS:
                continue
            return True

    return False


def is_read_only(command: str) -> bool:
    """True when every segment of a shell command merely inspects."""
    if has_write_redirect(command):
        return False
    segments = split_segments(command)
    return bool(segments) and all(READ_VERB.match(s) for s in segments)


def get_command_text(tool_input: dict[str, Any], sanitize: bool = False) -> str:
    """Extract string payload across relevant target input keys.

    With `sanitize`, annotation prose is blanked — use that for rule matching.
    Read-only classification must use the raw text, since the shell still runs
    what the quotes contain.
    """
    parts = []
    for key in TARGET_KEYS:
        val = tool_input.get(key)
        if isinstance(val, str) and val.strip():
            text = val.strip()
            if sanitize and key == "command":
                text = strip_annotation_payloads(text)
            parts.append(text)
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

    raw_text = get_command_text(tool_input)
    match_text = get_command_text(tool_input, sanitize=True)
    messages = []

    for rule in traps.rules:
        if rule.tool_matcher and not re.search(rule.tool_matcher, tool_name, re.I):
            continue

        if rule.target_matcher and not re.search(rule.target_matcher, match_text, re.I):
            continue

        if rule.read_only_ignore and is_read_only(raw_text):
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


def describe_rule_store(traps_path: Path | str | None = None) -> str:
    """Human-readable account of which rule store resolved, and whether it exists."""
    target = Path(traps_path) if traps_path else Path.cwd()
    resolved = resolve_traps_path(target) if (traps_path is None or target.is_dir()) else target

    if not resolved.exists():
        return f"no rule store at {resolved}"

    return f"{resolved} ({len(TrapsConfig.load(resolved).rules)} rules)"


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

    # An inert guardrail is indistinguishable from a quiet one. Say so once per
    # session, to the operator rather than into the agent's context.
    if not traps.rules and not state.get(NO_STORE_WARNED):
        state[NO_STORE_WARNED] = 1.0
        save_state(state_file, state)
        resolved = describe_rule_store(traps_path)
        print(json.dumps({
            "systemMessage": f"mcp-cocktail: no trap rules loaded ({resolved}). "
                             f"The PreToolUse guardrail is installed but inert. "
                             f"Run `mcp-cocktail setup --preset <domain>` to populate a rule store.",
        }, ensure_ascii=False))
        return 0

    now = time.time()
    fired_messages = evaluate_rules(tool_name, tool_input, traps, state, now)

    if fired_messages:
        save_state(state_file, state)
        print(json.dumps(build_hook_output(fired_messages), ensure_ascii=False))

    return 0


def selftest(traps_path: Path | str | None = None) -> int:
    """Selftest the rule engine, then report the deployment it is protecting.

    The engine passing says nothing about whether any rules are loaded. A
    collaborator who inherits a configured hook, a passing selftest, and an
    empty workspace has zero protection and no signal that anything is wrong.
    """
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

    print("Guardrail engine selftest PASSED.")

    target = Path(traps_path) if traps_path else Path.cwd()
    resolved = resolve_traps_path(target) if (traps_path is None or target.is_dir()) else target
    rule_count = len(TrapsConfig.load(resolved).rules) if resolved.exists() else 0

    print(f"Rule store: {resolved}")
    print(f"Rules loaded: {rule_count}")

    if rule_count == 0:
        print("\nWARNING: the engine works but no rules are deployed here — nothing is protected.")
        print("Run `mcp-cocktail setup --preset <domain>` to populate a rule store.")
        return 1

    return 0
