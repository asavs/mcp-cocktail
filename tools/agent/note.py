#!/usr/bin/env python3
"""Append a finding to the inbox, in one line, mid-task.

The loop's SENSE stage has been retrospective: mine the transcript afterwards and
hope the finding is still legible. It usually is not. The moment an agent knows
something worth recording is the moment it is fighting the thing, and by the end
of the session that knowledge is buried under whatever came next.

This is the cheapest possible capture. It is not the record — it is a staging
area, deliberately unstructured, so that writing to it costs nothing and nobody
skips it because the "proper" format is intimidating.

    note.py "eval on a Task deadlocks the Editor; fire-and-forget instead"
    note.py --cost 40 "unity open never returns though the Editor is ready"
    note.py --show

`--cost` is minutes lost, if known. It is the only structured field, because
cost x frequency is how upstream reports get ranked and it is the number nobody
can reconstruct after the fact.

Entries land in docs/findings-inbox.md. Promoting them into UNITY-TOOLING-NOTES.md
is a separate, deliberate act -- an inbox that auto-promotes is just a second
record that drifts from the first.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

# The default Windows console codec mangles anything non-ASCII, and a capture tool
# that prints mojibake looks broken and stops being used -- which is the exact
# friction this tool exists to remove. Fix our own stdout rather than asking anyone
# to remember PYTHONIOENCODING.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def record_root() -> Path:
    """Where the record lives — derived from this file, never from the cwd.

    These scripts run from inside *other* repositories: as a hook, or as a one-line
    capture during unrelated work. `git rev-parse --show-toplevel` resolves to whatever
    project is being worked on, so the previous version of this function wrote the inbox
    into the game repo that happened to be current. Set `MCP_COCKTAIL_DIR` if the record
    is somewhere other than two levels above this file.
    """
    env = os.environ.get("MCP_COCKTAIL_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[2]


INBOX = record_root() / "docs" / "findings-inbox.md"

HEADER = """# Findings inbox

Raw, unstructured, append-only. Written mid-task by whoever hit the thing.

This is **not** the record. Promoting an entry into
[UNITY-TOOLING-NOTES.md](../UNITY-TOOLING-NOTES.md) is a separate deliberate act:
version-stamp it, say what was observed versus inferred, and put it in one home.
An inbox that auto-promotes is just a second record that drifts from the first.

Nothing here has been verified. Read it as a to-check list.

---
"""


def main() -> None:
    ap = argparse.ArgumentParser(add_help=True, description=__doc__)
    ap.add_argument("text", nargs="*", help="the finding, in plain words")
    ap.add_argument("--cost", type=int, default=None, help="minutes lost, if known")
    ap.add_argument("--show", action="store_true", help="print the inbox and exit")
    a = ap.parse_args()

    if a.show:
        sys.exit(INBOX.read_text(encoding="utf-8") if INBOX.exists() else "inbox is empty")

    text = " ".join(a.text).strip()
    if not text:
        sys.exit("nothing to record.\n  note.py \"what you just learned\" [--cost MINUTES]")

    INBOX.parent.mkdir(parents=True, exist_ok=True)
    if not INBOX.exists():
        INBOX.write_text(HEADER, encoding="utf-8")

    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    session = os.environ.get("CLAUDE_SESSION_ID", "")[:8]
    meta = " · ".join(x for x in (stamp, f"{a.cost}min" if a.cost else "", session) if x)
    with INBOX.open("a", encoding="utf-8") as fh:
        fh.write(f"\n- **{meta}** — {text}\n")
    print(f"recorded -> {INBOX.relative_to(repo_root())}")


if __name__ == "__main__":
    main()
