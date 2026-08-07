#!/usr/bin/env python3
"""PreToolUse hook: surface the known trap for a Unity tool at the moment it is reached for.

Why this exists
---------------
The tooling record is good and gets read too late. On a scoped task an agent finds it
unaided; in a long multi-goal session it is not opened until after the cost is paid. A
session-start pointer does not fix that — it is exactly the thing that already works.
So the trigger has to be the tool call itself.

Every rule below cites a finding that already exists in the record. This file adds no new
claims; it is a retrieval mechanism, not a second copy of the notes. If a rule and the
record disagree, the record is right and this file is stale.

Wiring
------
This file lives in the record's repo and is wired into the `.claude/settings.json` of
whatever Unity project you are working in — the record is not that project, and does not
want to be checked out inside it. Point the command at an absolute path:

    "hooks": {
      "PreToolUse": [
        {
          "matcher": "Bash|PowerShell|mcp__unity-editor-mcp__.*|mcp__UnityMCP__.*|mcp__unityMCP__.*",
          "hooks": [
            {
              "type": "command",
              "command": "python \"C:/Users/you/Projects/mcp-cocktail/tools/agent/unity-trap-check.py\"",
              "timeout": 10
            }
          ]
        }
      ]
    }

If the record is somewhere else, set `MCP_COCKTAIL_DIR`. Citations are emitted as absolute
paths, because a bare filename is unopenable from the project the hook actually fires in.

A hook added mid-session arms without a restart. This used to claim the opposite — that
hooks are captured in a startup snapshot (`setup_hooks_captured`), read out of the 2.1.222
binary and never run. Measured twice and false; first injection landed ~15 minutes into a
session that predated the config. See docs/trials/M-001-RESULT.md.

Contract
--------
stdin  : the PreToolUse event JSON — `tool_name`, `tool_input`, `session_id`, `cwd`.
stdout : `{"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                  "additionalContext": "..."}}` when a rule matches.
exit   : always 0. This hook never blocks a call and never denies one. It has no opinion
         about whether the call is allowed; it only makes sure the relevant finding is in
         context before the result comes back.

A hook that guesses wrong and blocks is worse than no hook. A hook that is noisy gets
tuned out, which is the same as not existing — hence `cooldown_s` per rule: narrow,
high-precision triggers fire every time; broad ones fire at most hourly.

Verify effects, not exit codes — including this file's. `--selftest` runs the rule set
against fixtures.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path


def _record_root() -> Path:
    """Where the record lives — derived from this file, never from the cwd.

    This hook fires inside whatever project is being worked on, which is almost never
    this one. A bare `UNITY-TOOLING-NOTES.md` in a message is unopenable from there, so
    every citation is emitted as an absolute path. `MCP_COCKTAIL_DIR` overrides.

    Deliberately duplicated in note.py rather than shared through an import: a hook that
    raises on import breaks the tool call it was meant to annotate.
    """
    env = os.environ.get("MCP_COCKTAIL_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[2]


NOTES = str(_record_root() / "UNITY-TOOLING-NOTES.md")

# (id, cooldown_s, tool-name regex or None, command regex or None, message)
# cooldown_s = 0  -> fire on every match (trigger is specific enough to always be relevant)
# cooldown_s > 0  -> fire at most that often per session (trigger is broad)
RULES: list[tuple[str, int, str | None, str | None, str]] = [
    # ---- P2: the confident wrong answer -------------------------------------------------
    (
        "cli-open-no-path", 0, r"^(Bash|PowerShell)$",
        r"\bunity\s+open\s*(?:$|[|;&\n])",
        "P2 — `unity open` with no path does NOT resolve the cwd. It launches a second, "
        "bare Editor on the project picker and reports no error. Pass an explicit path. "
        f"({NOTES}#p2--the-confident-wrong-answer)",
    ),
    (
        "cli-editors-running", 0, r"^(Bash|PowerShell)$",
        r"\bunity\s+editors\s+running\b",
        "P2 — `unity editors running` has misreported which instance has the project open, "
        "listing both PIDs. Cross-check against the process command lines: "
        "`Get-CimInstance Win32_Process -Filter \"Name='Unity.exe'\" | Select ProcessId, CommandLine`. "
        f"({NOTES}#p2--the-confident-wrong-answer)",
    ),
    (
        "cli-pipeline-list", 0, r"^(Bash|PowerShell)$",
        r"\bunity\s+pipeline\s+list\b",
        "P2 — `unity pipeline list` resolves the CURRENT DIRECTORY as the project and "
        "invents a row when there isn't one; it has also reported `isRunning: true` with no "
        "Editor process, nothing bound on :7800, and no Library/EditorInstance.json. "
        "`cd` to the project first, use `--json`, and read `pipelineServer.isReachable` — "
        "not `isRunning`, and never the human table (two boolean-ish columns; a loose grep "
        f"matches the wrong one). ({NOTES}#p2--the-confident-wrong-answer)",
    ),
    # ---- P1: reads-once-at-startup ------------------------------------------------------
    (
        "cli-auth-login", 0, r"^(Bash|PowerShell)$",
        r"\bunity\s+auth\s+login\b",
        "P1 — the Editor snapshots its cloud access token AT STARTUP. If an Editor is "
        "already running this login will never reach it; Project Settings > Services stays "
        "signed out and reads as 'I need Unity Hub'. It does not. Order is `unity auth "
        f"login` THEN launch the Editor. ({NOTES}#p1--reads-once-at-startup)",
    ),
    (
        "manifest-while-running", 0, r"^(Bash|PowerShell|Edit|Write)$",
        r"unity\s+pipeline\s+install|Packages[\\/]manifest\.json",
        "P1 — Unity does not resolve a `Packages/manifest.json` change made while it is "
        "running. You will get `hasPipelinePackage: true` with `isReachable: false` "
        "indefinitely. The Editor must be restarted, and its HTTP server binds late after "
        f"that. ({NOTES}#p1--reads-once-at-startup)",
    ),
    (
        "uv-install", 0, r"^(Bash|PowerShell)$",
        r"(winget\s+install\s+astral-sh\.uv|\buv\s+self\s+update\b|pip\s+install\s+uv\b)",
        "P1 — `uv` must be on the EDITOR's PATH at launch. Installing it while Unity is "
        "running leaves the MCP window reporting `uv not found in PATH` permanently, and "
        "its Refresh button does not help. Restart the Editor from a shell that already "
        f"has uv, or point the window at the binary. ({NOTES}#p1--reads-once-at-startup)",
    ),
    # ---- P3: termination is not completion ----------------------------------------------
    (
        "cli-mcp-configure", 0, r"^(Bash|PowerShell)$",
        r"\bunity\s+mcp\s+configure\b",
        "P3 — `unity mcp configure` does its work and then NEVER EXITS. The config lands "
        "correctly; the process just doesn't return. Give it a timeout and verify the side "
        f"effect (~/.claude.json) rather than waiting on exit. ({NOTES}#p3--termination-is-not-completion-and-completion-is-not-termination)",
    ),
    (
        "batch-runtests-quit", 0, r"^(Bash|PowerShell)$",
        r"-runTests\b(?=[\s\S]*-quit\b)|-quit\b(?=[\s\S]*-runTests\b)",
        "P3 — `-quit` together with `-runTests` makes the Editor compile, exit 0, run NO "
        "tests and write no results XML. Drop `-quit` and let the Test Framework own "
        "shutdown. Also: a direct `Unity.exe` call returns control while the batch Editor "
        "keeps importing — use `Start-Process -Wait`. "
        f"({NOTES}#p3--termination-is-not-completion-and-completion-is-not-termination)",
    ),
    (
        "yamlmerge", 0, r"^(Bash|PowerShell)$",
        r"UnityYAMLMerge",
        "P3 — UnityYAMLMerge blocks on a GUI in two ways and both hang git: a modal error "
        "dialog on unparseable input, and a fallback to whichever GUI merge tool is "
        "installed. Pass `-h --fallback none` for any non-interactive use, and bound it "
        "with a timeout — invoking it with no subcommand hangs regardless of `-h`. "
        f"({NOTES}#git--unityyamlmerge)",
    ),
    (
        "merge-driver-config", 0, r"^(Bash|PowerShell)$",
        r"git\s+config[^\n]*merge\.[A-Za-z0-9_-]*\.(driver|name|recursive)",
        "Merge-driver placeholders are `%O %B %A` — `$BASE`/`$REMOTE`/`$LOCAL` are "
        "`git mergetool` placeholders and produce a driver that runs and silently discards "
        "one side. Bare double quotes in a config value are stripped on write, so read it "
        "back with `git config --get`. Partial config is fatal: any `merge.<x>.*` key "
        f"without `.driver` kills every Unity-asset merge. ({NOTES}#git--unityyamlmerge)",
    ),
    # ---- Anti-capabilities: things that fail only after you have paid --------------------
    # ---- Authoring, from the arm-B sessions. The CLI/MCP surface is not where long
    # ---- sessions lose time; Unity's own semantics are. See docs/trials/M-001-RESULT.md Q5.
    (
        "import-globalscale", 0,
        r"^mcp__unity-editor-mcp__set_import_settings$",
        r"globalScale|useFileScale",
        "Do NOT resize a humanoid with `ModelImporter.globalScale`. It builds an Avatar that "
        "passes every static check — `isValid`, `isHuman`, all bones mapped, correct bind pose "
        "— and collapses the skeleton the instant a controller with real clips retargets onto "
        "it. The tell is `Animator.humanScale` (0.011 vs 6.109 for the same character). Import "
        "with `useFileScale = true` and scale the ROOT TRANSFORM instead, matched to hips "
        f"height rather than total height. ({NOTES}#humanoid-import-scale-the-root-never-globalscale)",
    ),
    (
        "collider-root-scale", 0,
        r"^mcp__unity-editor-mcp__(set_component_properties|set_serialized_field)$",
        r"skinWidth|stepOffset|CharacterController|CapsuleCollider|SpringBoneCollider",
        "On a scaled prefab root, collider properties do NOT all follow the scale. "
        "`height`/`radius`/`center` do — divide by the root scale. `skinWidth`, `stepOffset` "
        "and `SpringBoneCollider.radius` are raw world metres and do not. Getting it wrong is "
        "silent: the character floats or sinks. `skinWidth` especially — the character rests "
        "exactly that far above the ground. Set it, enter play mode, and measure where the "
        f"character actually settles. ({NOTES}#a-scaled-prefab-root-does-not-scale-every-collider-property)",
    ),
    (
        "empty-motion-slots", 0,
        r"^mcp__unity-editor-mcp__(create_animator_controller|add_animator_state|add_animator_layer)$",
        None,
        "A humanoid state whose blend tree has no motion assigned does not do nothing — it "
        "writes a DEGENERATE POSE. Hips go from +0.981 to -0.138 relative to the root on "
        "assignment, and the character stands buried ~1.1 m in the floor. It reads as a rigging "
        "or import bug. Assign a controller only once its states have real clips; check with "
        f"`hips.position.y - root.position.y` before and after. ({NOTES}#an-animator-controller-with-empty-motion-slots-writes-a-degenerate-pose)",
    ),
    (
        "bone-write-timing", 0,
        r"^mcp__unity-editor-mcp__eval(_file)?$",
        r"GetBoneTransform|HumanBodyBones|localRotation\s*=|bone\w*\.rotation\s*=",
        "Two traps on procedural bone writes, both silent. (1) The Animator evaluates BETWEEN "
        "`Update` and `LateUpdate`, so a bone write from `Update` is discarded whenever a "
        "controller is running — write in `LateUpdate`. (2) With NO controller the Animator "
        "never evaluates, so nothing restores the pose between frames and additive writes "
        "STACK: 60 additive 1-degree writes drifted a bone a measured 60 degrees in one second. "
        "Capture rest rotations in `Awake` and compose `offset * parentRotation * "
        "restLocalRotation`. The naive version is idempotent under a running controller, so it "
        f"breaks only when testing a character in isolation. ({NOTES}#procedural-bone-writes-must-compose-from-a-captured-rest-pose)",
    ),
    (
        "hierarchy-no-pagination", 0,
        r"^mcp__unity-editor-mcp__(get_scene_hierarchy|find_gameobjects)$", None,
        "ANTI-CAPABILITY — this tool has no depth, limit, or pagination parameter. On one "
        "measured production scene `get_scene_hierarchy` returned 290,642 characters / "
        "7,883 lines and blew the client's token limit outright. Any scene with terrain or "
        "a large prop count can do this. Scope the question another way — `search`, "
        f"`find_assets`, or a specific path — before calling it on a scene you have not "
        f"already measured. ({NOTES}#log)",
    ),
    (
        "component-props-unsupported", 0,
        r"^mcp__unity-editor-mcp__get_component_properties$", None,
        "ANTI-CAPABILITY — `get_component_properties` cannot read common value types: it "
        "returns the literal strings `<unsupported:Quaternion>` for `m_LocalRotation` and "
        "`<unsupported:LayerMask>` for layer masks. If you need rotation or a layer mask, "
        f"this call will not answer you. ({NOTES}#log)",
    ),
    (
        "coplay-write-no-echo", 0,
        r"^mcp__(UnityMCP|unityMCP)__manage_(gameobject|components|material|scriptable_object)$", None,
        "P5 — CoplayDev writes do not echo state. `set_property` returns only "
        "`{\"instanceID\": ...}`, and `manage_gameobject action=create` accepts "
        "`component_properties`, returns success, and silently leaves the property at its "
        "default (source-confirmed; there is no reachable way to set a component property "
        "at creation time — use `action=modify` after creating). Read the state back. "
        f"({NOTES}#p5--the-argument-that-is-accepted-and-then-ignored)",
    ),
    # ---- Broad, rate-limited ------------------------------------------------------------
    (
        "arbitrary-csharp", 3600,
        r"^mcp__(unity-editor-mcp__eval(_file)?|UnityMCP__execute_code|unityMCP__execute_code)$", None,
        "`eval` / `eval_file` / `execute_code` run arbitrary C# in the Editor and bypass "
        "every `confirm=true` and `dry_run` guard the other tools have, since anything "
        "those guards protect can be done directly from C#. This is a decision, not a "
        "convenience. If a read-only tool can answer the question, prefer it — the known "
        "exception is terrain introspection, which has no read-only route at all. "
        f"({NOTES}#unity-official-the-tool-surface-once-pipeline-is-live)",
    ),
    (
        "shared-editor-state", 3600,
        r"^mcp__(unity-editor-mcp|UnityMCP|unityMCP)__(editor_play|editor_stop|editor_pause|open_scene|set_active_scene|set_selection|menu|execute_menu_item)$",
        None,
        "The Editor is shared with a human at the keyboard. Play mode, the open scene and "
        "the selection are all things they are looking at right now. Confirm this was "
        "asked for, and put it back when you are done.",
    ),
    (
        "cli-general", 3600, r"^(Bash|PowerShell)$",
        r"(?<![\w./\\-])unity(\.exe)?\s+[a-z]",
        "`unity` CLI, general: do NOT gate on exit codes (several commands return 255 while "
        "printing correct output), allow 60s+ (they look hung and aren't; a few `--help` "
        "subcommands genuinely hang), prefer `--json`, and `cd` to the project first — "
        "several commands resolve the cwd as the project. Its defining failure mode is a "
        f"confident wrong answer rather than an error. ({NOTES}#p2--the-confident-wrong-answer)",
    ),
]

# Fired once per session, on the first Unity-adjacent tool call of any kind.
FIRST_TOUCH = (
    "This project keeps a record of how the Unity tooling actually behaves, and the "
    "measured failure is that it gets read after the cost is paid rather than before. "
    f"The five recurring failure shapes are in {NOTES} — the Patterns section, near the "
    "top. Two minutes, and it is the part that repeats: things read their ambient state "
    "once at startup; the CLI answers confidently and wrongly rather than erroring; "
    "exiting and succeeding are uncorrelated in both directions; a green light proves only "
    "its own layer; and an argument can be accepted and then ignored."
)

UNITY_ISH = re.compile(
    r"^mcp__(unity-editor-mcp|UnityMCP|unityMCP)__|"
    r"^(Bash|PowerShell)$",
)


def state_path(session_id: str) -> str:
    base = os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp"
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "nosession")
    return os.path.join(base, f"unity-trap-check-{safe}.json")


def load_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_state(path: str, state: dict) -> None:
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except Exception:
        pass  # a hook that fails must not break the tool call


# What a call *targets*, never what it *writes*. `new_string` and `content` used to be in
# here, which meant writing the string "Packages/manifest.json" into a markdown file fired
# the manifest rule. Editing a document that mentions a trap is not the trap. No rule in
# this file needs to see file bodies — they all match a command verb or a target path.
# `code` is included because for `eval` it *is* the command — the payload being executed,
# not a document being written. Without it, every MCP rule can only select on tool name.
TARGET_KEYS = ("command", "file_path", "path", "code")

# A segment that only inspects. Every trap in the record is about *mutating* or *invoking*
# something; `git diff Packages/manifest.json` and `grep unity docs/unity-cli.md` are
# neither, and both fired in M-001.
READ_VERB = re.compile(
    r"^(?:"
    r"cd\s+(?:\"[^\"]*\"|'[^']*'|\S+)\s*$"          # a bare `cd` segment is just a prefix
    r"|(?:git\s+(?:diff|log|show|status|ls-tree|ls-files|blame|branch|remote|config\s+--get)"
    r"|grep|rg|cat|head|tail|sed\s+-n|awk|less|ls|find|wc|echo|type"
    r"|Select-String|Get-Content|Get-ChildItem|Test-Path)\b"
    r")",
    re.IGNORECASE,
)
def split_segments(command: str) -> list[str]:
    """Split on `&&`, `||`, `|`, `;` — but not inside quotes.

    A naive `re.split` breaks `grep -nE 'unity-mcp|pipeline' file` and
    `grep -n "a\\|b" file | head` into fragments that no longer look like reads, which
    turns the read guard off exactly where it is needed most. Both are real commands from
    the M-001 transcript.
    """
    segments, current, quote = [], [], None
    i = 0
    while i < len(command):
        ch = command[i]
        if quote:
            current.append(ch)
            if ch == quote and (i == 0 or command[i - 1] != "\\"):
                quote = None
        elif ch in "\"'":
            quote = ch
            current.append(ch)
        elif ch in "&|;":
            while i < len(command) and command[i] in "&|;":
                i += 1
            segments.append("".join(current))
            current = []
            continue
        else:
            current.append(ch)
        i += 1
    segments.append("".join(current))
    return [s.strip() for s in segments if s.strip()]


def command_text(tool_input: dict) -> str:
    parts = []
    for key in TARGET_KEYS:
        val = tool_input.get(key)
        if isinstance(val, str):
            parts.append(val)
    return "\n".join(parts)


def is_read_only(command: str) -> bool:
    """True when every segment of a shell command merely inspects.

    Conservative on purpose: one segment that isn't recognisably a read makes the whole
    command non-read-only, so a genuine `unity ...` buried after a `grep` still fires.
    """
    segments = split_segments(command)
    return bool(segments) and all(READ_VERB.match(s) for s in segments)


def matching_rules(tool_name: str, tool_input: dict) -> list[tuple[str, str]]:
    """Rules whose selectors match this call, ignoring cooldown and state.

    The single source of truth for *does this rule apply*. The selftest calls this rather
    than re-deriving it: 703bf53 fixed a rule that was unreachable in production while a
    duplicated selftest loop reported it passing.
    """
    text = command_text(tool_input)

    # A shell command that only inspects cannot spring a trap. Suppresses the largest
    # misfire class measured in M-001 (5 of 8 injections). Deliberately does not gate the
    # first-touch pointer in evaluate() — that one fired correctly and is the only
    # injection in that session that changed what happened next.
    if tool_name in ("Bash", "PowerShell") and is_read_only(tool_input.get("command") or ""):
        return []

    hits = []
    for rule_id, _cooldown, name_re, cmd_re, message in RULES:
        if name_re and not re.search(name_re, tool_name):
            continue
        if cmd_re and not re.search(cmd_re, text, re.IGNORECASE):
            continue
        hits.append((rule_id, message))
    return hits


def evaluate(tool_name: str, tool_input: dict, state: dict, now: float) -> list[str]:
    """Return the messages that should fire. Mutates `state`."""
    fired: list[str] = []
    cooldowns = {rule_id: cd for rule_id, cd, _n, _c, _m in RULES}

    for rule_id, message in matching_rules(tool_name, tool_input):
        last = state.get(rule_id, 0)
        if cooldowns[rule_id] and (now - last) < cooldowns[rule_id]:
            continue
        state[rule_id] = now
        fired.append(message)

    if UNITY_ISH.search(tool_name) and not state.get("_first_touch"):
        # Only counts as a Unity touch if it is an MCP call or actually mentions unity/uv.
        text = command_text(tool_input)
        if tool_name.startswith("mcp__") or re.search(r"\bunity|\buv\b|UnityYAMLMerge", text, re.I):
            state["_first_touch"] = now
            fired.insert(0, FIRST_TOUCH)

    return fired


def main() -> int:
    # Windows consoles default to cp1252; the messages below contain em dashes and `≥`.
    # Without this the hook dies on UnicodeEncodeError and silently stops firing.
    for stream in (sys.stdout, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0

    tool_name = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    path = state_path(str(event.get("session_id") or ""))
    state = load_state(path)
    fired = evaluate(tool_name, tool_input, state, time.time())
    if not fired:
        return 0
    save_state(path, state)

    body = "Known trap for this call, from the project's tooling record:\n\n" + "\n\n".join(
        f"- {m}" for m in fired
    )
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": body[:9000],
            }
        },
        sys.stdout,
    )
    return 0


def selftest() -> int:
    # expectation: "rule-id" must fire · "!rule-id" must NOT fire · None -> nothing fires
    cases = [
        ("Bash", {"command": "unity open"}, "cli-open-no-path"),
        ("Bash", {"command": "unity open C:/repo"}, "!cli-open-no-path"),
        ("Bash", {"command": "cd /c/repo && unity pipeline list --json"}, "cli-pipeline-list"),
        ("PowerShell", {"command": "unity editors running"}, "cli-editors-running"),
        ("Bash", {"command": "unity auth login"}, "cli-auth-login"),
        ("Bash", {"command": "winget install astral-sh.uv"}, "uv-install"),
        ("Bash", {"command": "unity mcp configure claude-code"}, "cli-mcp-configure"),
        ("Bash", {"command": 'Unity.exe -batchmode -runTests -quit -projectPath .'}, "batch-runtests-quit"),
        ("Bash", {"command": 'git config merge.unityyamlmerge.driver "x %O %B %A"'}, "merge-driver-config"),
        ("Edit", {"file_path": "C:/repo/Packages/manifest.json"}, "manifest-while-running"),
        ("mcp__unity-editor-mcp__get_scene_hierarchy", {}, "hierarchy-no-pagination"),
        ("mcp__unity-editor-mcp__get_component_properties", {}, "component-props-unsupported"),
        ("mcp__UnityMCP__manage_gameobject", {}, "coplay-write-no-echo"),
        ("mcp__unity-editor-mcp__eval", {}, "arbitrary-csharp"),
        ("mcp__unity-editor-mcp__editor_play", {}, "shared-editor-state"),
        ("Bash", {"command": "unity list"}, "cli-general"),
        ("Bash", {"command": "git status --short"}, None),
        # a cd into a path that contains "unity" must not trip the CLI rule
        ("Bash", {"command": "cd /c/dev/UnityProjects/my-game && git log"}, None),
        ("Read", {"file_path": "C:/repo/README.md"}, None),
        # ---- misfires measured in M-001. Every one of these fired in production. --------
        # Reads of the manifest are not changes to the manifest.
        ("Bash", {"command": "git diff --stat Packages/ ; git diff Packages/manifest.json"}, None),
        ("Bash", {"command": "grep -nE 'unity-mcp|pipeline' Packages/manifest.json"}, None),
        ("Bash", {"command": "git ls-tree -r --name-only origin/main -- Assets/Game"}, None),
        # Grepping the CLI's own documentation is not invoking the CLI.
        ("Bash", {"command": 'grep -n "unity open\\|-projectPath" docs/unity-cli.md | head -20'}, None),
        # Writing a document that mentions a trap is not springing it.
        ("Write", {"file_path": "docs/trials/M-001-RESULT.md",
                   "content": "the rule fired on Packages/manifest.json and unity pipeline list"}, None),
        ("Edit", {"file_path": "docs/findings-inbox.md",
                  "new_string": "hit the Packages/manifest.json trap again"}, None),
        # ...but the read guard must not swallow a real call hidden behind a read.
        ("Bash", {"command": "grep -n foo docs/unity-cli.md && unity pipeline list"}, "cli-pipeline-list"),
        ("Bash", {"command": "cat notes.md; unity auth login"}, "cli-auth-login"),
        # ...and editing the manifest itself still fires.
        ("Write", {"file_path": "C:/repo/Packages/manifest.json"}, "manifest-while-running"),
        # ---- authoring rules mined from 69735fe7 (271 arm-B calls) ---------------------
        ("mcp__unity-editor-mcp__set_import_settings",
         {"path": "Assets/x.fbx", "settings": "{}", "code": "globalScale=0.0018"}, "import-globalscale"),
        ("mcp__unity-editor-mcp__set_import_settings",
         {"path": "Assets/x.png"}, "!import-globalscale"),
        ("mcp__unity-editor-mcp__set_component_properties",
         {"code": "skinWidth", "path": "Player"}, "collider-root-scale"),
        ("mcp__unity-editor-mcp__set_component_properties", {"path": "Player"}, "!collider-root-scale"),
        ("mcp__unity-editor-mcp__create_animator_controller", {}, "empty-motion-slots"),
        ("mcp__unity-editor-mcp__add_animator_state", {}, "empty-motion-slots"),
        ("mcp__unity-editor-mcp__eval",
         {"code": "var h = a.GetBoneTransform(HumanBodyBones.Hips);"}, "bone-write-timing"),
        ("mcp__unity-editor-mcp__eval", {"code": "Debug.Log(1);"}, "!bone-write-timing"),
    ]
    ok = True
    for tool_name, tool_input, expect in cases:
        hits = [rule_id for rule_id, _msg in matching_rules(tool_name, tool_input)]
        if expect is None:
            good = not hits
        elif expect.startswith("!"):
            good = expect[1:] not in hits
        else:
            good = expect in hits
        status = "ok  " if good else "FAIL"
        if not good:
            ok = False
        print(f"{status} {tool_name:48s} {str(tool_input)[:44]:46s} -> {hits or '-'}")
    # the false-positive case that matters most: a cd into a path containing 'unity'
    print("\nselftest", "passed" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
