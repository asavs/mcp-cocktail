"""Friction note capture for mcp-cocktail findings inbox."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

INBOX_HEADER = """# Findings inbox

Raw, unverified observations, appended mid-task.
A to-check list, not the permanent record. Promoting an entry into a domain
record or rule store is a separate, deliberate act.
"""


def get_inbox_path(root_dir: Path | str | None = None) -> Path:
    root = Path(root_dir) if root_dir else Path.cwd()
    docs_dir = root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    return docs_dir / "findings-inbox.md"


def append_note(
    text: str,
    cost_mins: int | None = None,
    inbox_path: Path | str | None = None,
) -> Path:
    target = Path(inbox_path) if inbox_path else get_inbox_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(INBOX_HEADER + "\n", encoding="utf-8")

    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    cost_str = f" (cost: {cost_mins}m)" if cost_mins is not None else ""
    line = f"- [{timestamp}]{cost_str} {text.strip()}\n"

    with open(target, "a", encoding="utf-8") as f:
        f.write(line)

    return target


def show_inbox(inbox_path: Path | str | None = None) -> str:
    target = Path(inbox_path) if inbox_path else get_inbox_path()
    if not target.exists():
        return "Inbox is empty (file does not exist)."
    return target.read_text(encoding="utf-8")


def main(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mcp-cocktail note",
        description="Append a friction observation to the findings inbox.",
    )
    parser.add_argument("note", nargs="*", help="Observation text to record")
    parser.add_argument("--cost", type=int, default=None, help="Minutes lost to this issue")
    parser.add_argument("--show", action="store_true", help="Display inbox contents")
    parser.add_argument("--inbox", type=str, default=None, help="Path to findings inbox file")

    opts = parser.parse_args(args)

    if opts.show:
        print(show_inbox(opts.inbox))
        return 0

    if not opts.note:
        parser.print_help()
        return 1

    text = " ".join(opts.note)
    p = append_note(text, cost_mins=opts.cost, inbox_path=opts.inbox)
    print(f"Recorded note -> {p}")
    return 0
