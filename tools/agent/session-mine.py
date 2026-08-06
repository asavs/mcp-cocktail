#!/usr/bin/env python3
"""Read Claude Code session transcripts.

Sessions are the best evidence source for this record and nothing read them
systematically. Three mining runs each rewrote this parser from scratch in a
scratchpad and threw it away, so the fourth run paid the same cost as the first.

Transcripts live in ~/.claude/projects/<slug>/<session-uuid>.jsonl, one JSON
object per line. The useful payload is message.content[], a list of blocks with
a "type" of text / thinking / tool_use / tool_result.

Set PYTHONIOENCODING=utf-8 on Windows. Transcripts are full of box-drawing
characters and the default console codec dies on them.

    session-mine.py sweep                 rank sessions by Unity tooling used
    session-mine.py stats   <file|uuid>   one session: turns, tools, arms
    session-mine.py grep    <pat> <file>  search all text, with context
    session-mine.py tools   <file|uuid>   every tool call, in order

`sweep` is the one that matters. Every session mined so far was picked because
a human remembered it, which is the opposite of the sampling rule this record
sets out: sample long, multi-goal, drifting sessions. A human remembers the
interesting ones, so recall-based sampling reports success while the actual
failure mode goes unobserved. Rank mechanically instead.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

PROJECTS = Path(os.path.expanduser("~/.claude/projects"))

# Which arm a tool call belongs to. A and B are one stack but reached
# differently, and the distinction is exactly what the record needs measured.
ARMS = {
    "A-cli":    re.compile(r"\bunity(\.exe)?\s+(command|list|status|open|run|test|build|editors|mcp)\b"),
    "B-mcp":    re.compile(r"^mcp__unity-editor-mcp__"),
    "C-mcp":    re.compile(r"^mcp__[Uu]nity[Mm][Cc][Pp]__"),
}


def sessions(slug: str | None = None):
    roots = [PROJECTS / slug] if slug else sorted(p for p in PROJECTS.iterdir() if p.is_dir())
    for root in roots:
        if root.is_dir():
            yield from sorted(root.glob("*.jsonl"))


def resolve(target: str) -> Path:
    p = Path(target)
    if p.is_file():
        return p
    hits = [f for f in sessions() if f.stem.startswith(target)]
    if not hits:
        sys.exit(f"no session matching {target!r}")
    if len(hits) > 1:
        sys.exit("ambiguous:\n  " + "\n  ".join(str(h) for h in hits))
    return hits[0]


def blocks(path: Path):
    """Yield (lineno, role, kind, name, text) for every content block.

    Malformed lines are skipped rather than fatal: a transcript being written
    by a live session can have a torn final line, and refusing to parse the
    whole file for that is how a tool gets abandoned mid-investigation.
    """
    with path.open(encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get("message") or {}
            role = msg.get("role") or rec.get("type") or "?"
            content = msg.get("content")
            if isinstance(content, str):
                yield n, role, "text", "", content
                continue
            for b in content or []:
                if not isinstance(b, dict):
                    continue
                kind = b.get("type", "")
                if kind in ("text", "thinking"):
                    yield n, role, kind, "", b.get(kind) or b.get("text") or ""
                elif kind == "tool_use":
                    yield n, role, kind, b.get("name", ""), json.dumps(b.get("input", {}))
                elif kind == "tool_result":
                    c = b.get("content")
                    if isinstance(c, list):
                        c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
                    yield n, role, kind, "", str(c or "")


def arm_of(name: str, payload: str) -> str | None:
    for arm, pat in ARMS.items():
        if arm == "A-cli":
            if name in ("Bash", "PowerShell") and pat.search(payload):
                return arm
        elif pat.match(name):
            return arm
    return None


# A session that is *about* the record will consult the record, and measuring
# retrieval there reports success while the real failure mode goes unobserved.
# Same for a session standing the tooling up: that phase is already covered
# exhaustively and each machine passes through it once. Both must be excluded
# from sampling, and both look identical to a naive rank-by-Unity-usage sweep --
# which is exactly the mistake that produced three useless candidates the first
# time this ran.
SELF_REF = re.compile(r"UNITY-TOOLING-NOTES|tooling-scorecard|tooling-experiment|unity-tooling", re.I)
SETUP = re.compile(r"\b(install|installing) (the )?(latest )?unity\b|unity cli\b.*\binstall|"
                   r"\bset ?up the (mcp|editor|pipeline)\b", re.I)


def summarise(path: Path) -> dict:
    tools: Counter = Counter()
    arms: Counter = Counter()
    turns = 0
    chars = 0
    selfref = 0
    setupish = False
    first_user = ""
    for _, role, kind, name, text in blocks(path):
        chars += len(text)
        if SELF_REF.search(text):
            selfref += 1
        if kind == "text" and role == "user":
            turns += 1
            t = " ".join(text.split())
            if not first_user and t and not t.startswith(("<", "[SYSTEM", "Caveat")):
                first_user = t[:120]
                if SETUP.search(t):
                    setupish = True
        if kind == "tool_use":
            tools[name] += 1
            a = arm_of(name, text)
            if a:
                arms[a] += 1
    return {
        "path": path, "turns": turns, "calls": sum(tools.values()),
        "tools": tools, "arms": arms, "unity": sum(arms.values()), "chars": chars,
        "selfref": selfref, "setup": setupish, "first_user": first_user,
    }


def cmd_sweep(args):
    rows = []
    for f in sessions(args[0] if args else None):
        try:
            rows.append(summarise(f))
        except OSError:
            continue
    rows.sort(key=lambda r: (-r["unity"], -r["calls"]))
    print(f"{'session':<38} {'turns':>6} {'calls':>7} {'unity':>6} {'flag':<10} arms")
    print("-" * 96)
    usable = 0
    for r in rows[:40]:
        if not r["calls"]:
            continue
        flag = "SETUP" if r["setup"] else ("self-ref" if r["selfref"] > 20 else "")
        if r["unity"] and not flag:
            usable += 1
        arms = " ".join(f"{k}={v}" for k, v in sorted(r["arms"].items())) or "-"
        print(f"{r['path'].stem:<38} {r['turns']:>6} {r['calls']:>7} {r['unity']:>6} {flag:<10} {arms}")
    print(f"\nUnflagged sessions that drove Unity: {usable}")
    print("Rank is mechanical, not by recall — a human remembers the memorable ones,")
    print("which is the opposite of the drifting sessions the failure mode lives in.")
    print("SETUP    = standing the tooling up. That phase is already documented to")
    print("           exhaustion and each machine passes through it once.")
    print("self-ref = the session is about the record, so it consults the record and")
    print("           any retrieval measurement taken there is meaningless.")
    print("Both look identical to a naive rank-by-usage sweep. Exclude them, and if")
    print("that leaves nothing, the honest report is that the sample does not exist.")


def cmd_stats(args):
    r = summarise(resolve(args[0]))
    print(f"session   {r['path'].stem}")
    print(f"user turns{r['turns']:>8}")
    print(f"tool calls{r['calls']:>8}")
    print(f"unity calls{r['unity']:>7}")
    print(f"transcript{r['chars']:>8} chars")
    if r["arms"]:
        print("\narms")
        for k, v in sorted(r["arms"].items()):
            print(f"  {k:<10} {v:>5}")
    print("\ntop tools")
    for name, n in r["tools"].most_common(15):
        print(f"  {name:<34} {n:>5}")


def cmd_grep(args):
    pat = re.compile(args[0], re.I)
    for f in ([resolve(args[1])] if len(args) > 1 else sessions()):
        for n, role, kind, name, text in blocks(f):
            if pat.search(text):
                flat = " ".join(text.split())
                label = f"{name}" if name else kind
                print(f"{f.stem[:8]}:{n:<6} {role:<9} {label:<28} {flat[:150]}")


def cmd_tools(args):
    for n, role, kind, name, text in blocks(resolve(args[0])):
        if kind == "tool_use":
            print(f"{n:<7} {name:<32} {' '.join(text.split())[:130]}")


NEEDS_ARG = {"stats": "<file|uuid>", "grep": "<pattern> [file|uuid]", "tools": "<file|uuid>"}


def main() -> None:
    cmds = {"sweep": cmd_sweep, "stats": cmd_stats, "grep": cmd_grep, "tools": cmd_tools}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd in NEEDS_ARG and not args:
        sys.exit(f"{cmd} needs an argument: {cmd} {NEEDS_ARG[cmd]}\n"
                 f"Run `sweep` first to list sessions.")
    cmds[cmd](args)


if __name__ == "__main__":
    main()
