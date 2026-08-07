"""Session transcript miner, usage analyzer, and P1-P5 trap detector for mcp-cocktail."""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from mcp_cocktail.config import CocktailConfig, ArmConfig

PROJECTS_DIR = Path(os.path.expanduser("~/.claude/projects"))

# Exclusion patterns for invalid evidence filtering
SELF_REF_PAT = re.compile(
    r"\b(mcp-cocktail|cocktail|tooling-scorecard|tooling-experiment|findings-inbox|traps\.json)\b",
    re.I,
)
SETUP_PAT = re.compile(
    r"\b(install|installing|setup|configuring)\b.*\b(mcp|cli|server|environment)\b",
    re.I,
)

# Pattern signatures for P1-P5 recurring trap shapes
P1_PAT = re.compile(r"\b(not found in PATH|signed out|restart|access token|snapshot)\b", re.I)
P2_PAT = re.compile(r"\b(misreported|invented|wrong pid|isRunning.*true|fake row)\b", re.I)
P3_PAT = re.compile(r"\b(never exits|hang|timeout|exited 0.*no tests|exit status)\b", re.I)
P4_PAT = re.compile(r"\b(connected.*zero tools|0 tools|unreachable|bound.*refus|406)\b", re.I)
P5_PAT = re.compile(r"\b(ignored|property.*default|success.*true.*not set|did not echo)\b", re.I)


@dataclass
class TrapPatternInstance:
    pattern_id: str  # P1, P2, P3, P4, P5
    name: str
    line_no: int
    context: str


@dataclass
class SessionSummary:
    session_id: str
    file_path: Path
    turn_count: int = 0
    arm_counts: Counter[str] = field(default_factory=Counter)
    tool_counts: Counter[str] = field(default_factory=Counter)
    error_count: int = 0
    pattern_hits: list[TrapPatternInstance] = field(default_factory=list)
    is_self_ref: bool = False
    is_setup: bool = False


def find_transcripts(project_slug: str | None = None) -> Iterator[Path]:
    """Yield all jsonl transcript files matching a project or all projects."""
    if not PROJECTS_DIR.exists():
        return

    roots = [PROJECTS_DIR / project_slug] if project_slug else sorted(
        p for p in PROJECTS_DIR.iterdir() if p.is_dir()
    )

    for root in roots:
        if root.exists():
            yield from sorted(root.glob("*.jsonl"))


def parse_blocks(path: Path) -> Iterator[tuple[int, str, str, str, str]]:
    """Yield (line_no, role, kind, name, text) for every block in transcript."""
    if not path.exists():
        return

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue

            role = row.get("type", row.get("role", "unknown"))
            msg = row.get("message", {})
            content = msg.get("content") if isinstance(msg, dict) else row.get("content")

            if isinstance(content, str):
                yield lineno, role, "text", "", content
            elif isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    kind = item.get("type", "unknown")
                    if kind == "tool_use":
                        name = item.get("name", "")
                        inp = json.dumps(item.get("input", {}))
                        yield lineno, role, "tool_use", name, inp
                    elif kind == "tool_result":
                        name = item.get("tool_use_id", "")
                        text = str(item.get("content", ""))
                        yield lineno, role, "tool_result", name, text
                    elif kind == "text":
                        yield lineno, role, "text", "", item.get("text", "")


def match_arm(tool_name: str, tool_payload: str, config: CocktailConfig) -> str | None:
    """Classify a tool call into one of the arms defined in CocktailConfig."""
    for arm in config.arms:
        if arm.tool_prefix and tool_name.startswith(arm.tool_prefix):
            return arm.id
        if arm.mcp_server and arm.mcp_server.lower() in tool_name.lower():
            return arm.id
        if arm.command and (tool_name.lower() in ("bash", "powershell")):
            if arm.command.lower() in tool_payload.lower():
                return arm.id
    return None


def detect_patterns(lineno: int, text: str) -> list[TrapPatternInstance]:
    hits = []
    if P1_PAT.search(text):
        hits.append(TrapPatternInstance("P1", "Reads-Once-at-Startup", lineno, text[:120]))
    if P2_PAT.search(text):
        hits.append(TrapPatternInstance("P2", "Confident Wrong Answer", lineno, text[:120]))
    if P3_PAT.search(text):
        hits.append(TrapPatternInstance("P3", "Termination != Completion", lineno, text[:120]))
    if P4_PAT.search(text):
        hits.append(TrapPatternInstance("P4", "Green Light (First State Only)", lineno, text[:120]))
    if P5_PAT.search(text):
        hits.append(TrapPatternInstance("P5", "Argument Accepted then Ignored", lineno, text[:120]))
    return hits


def summarize_transcript(path: Path, config: CocktailConfig) -> SessionSummary:
    summary = SessionSummary(session_id=path.stem, file_path=path)
    combined_text = []

    for lineno, role, kind, name, text in parse_blocks(path):
        summary.turn_count += 1
        combined_text.append(text)

        p_hits = detect_patterns(lineno, text)
        if p_hits:
            summary.pattern_hits.extend(p_hits)

        if kind == "tool_use":
            summary.tool_counts[name] += 1
            arm_id = match_arm(name, text, config)
            if arm_id:
                summary.arm_counts[arm_id] += 1
        elif kind == "tool_result" and ("error" in text.lower() or "fail" in text.lower()):
            summary.error_count += 1

    all_text = " ".join(combined_text[:50])
    summary.is_self_ref = bool(SELF_REF_PAT.search(all_text))
    summary.is_setup = bool(SETUP_PAT.search(all_text))

    return summary


def cmd_sweep(config: CocktailConfig, project_slug: str | None = None) -> list[SessionSummary]:
    results = []
    for path in find_transcripts(project_slug):
        s = summarize_transcript(path, config)
        if sum(s.arm_counts.values()) > 0 or len(s.pattern_hits) > 0:
            results.append(s)

    results.sort(key=lambda s: (len(s.pattern_hits), sum(s.arm_counts.values())), reverse=True)
    return results


def print_sweep_report(summaries: list[SessionSummary], config: CocktailConfig) -> None:
    print(f"\n{'Session ID':<36} {'Turns':>6} {'Arm Calls':>10} {'Traps (P1-P5)':>14} {'Flags'}")
    print("-" * 85)

    valid_count = 0
    for s in summaries:
        flags = []
        if s.is_self_ref:
            flags.append("SELF-REF")
        if s.is_setup:
            flags.append("SETUP")
        flag_str = ", ".join(flags) if flags else "VALID"

        if not flags:
            valid_count += 1

        total_arm_calls = sum(s.arm_counts.values())
        trap_count = len(s.pattern_hits)
        print(f"{s.session_id:<36} {s.turn_count:>6} {total_arm_calls:>10} {trap_count:>14} {flag_str}")

    print(f"\nTotal analyzed sessions: {len(summaries)} (Valid evidence sessions: {valid_count})")
