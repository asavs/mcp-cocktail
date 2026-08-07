"""Comparative scorecard analysis, RSI loop engine, and 4-Exhaust pipeline for mcp-cocktail."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp_cocktail.config import CocktailConfig, ArmConfig
from mcp_cocktail.weakness import derive_weakest_rule, compute_weakness_score


@dataclass
class ArmScore:
    arm_id: str
    arm_name: str
    trials_run: int = 0
    successes: int = 0
    total_steps: int = 0
    total_errors: int = 0
    traps_hit: int = 0
    findings: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return (self.successes / self.trials_run * 100.0) if self.trials_run > 0 else 0.0

    @property
    def avg_steps(self) -> float:
        return (self.total_steps / self.trials_run) if self.trials_run > 0 else 0.0


def parse_trial_report(report_path: Path) -> dict[str, Any]:
    if not report_path.exists():
        return {}

    text = report_path.read_text(encoding="utf-8", errors="replace")

    is_success = bool(re.search(r"verdict:?\s*(success|passed)", text, re.I))
    step_matches = re.findall(r"step(?:s)?:\s*(\d+)", text, re.I)
    steps = int(step_matches[0]) if step_matches else len(re.findall(r"^\d+\.\s+", text, re.M))

    error_count = len(re.findall(r"\b(error|fail|exception|trap)\b", text, re.I))

    return {
        "text": text,
        "success": is_success,
        "steps": steps,
        "errors": error_count,
    }


def generate_scorecard(config: CocktailConfig, root_dir: Path | str | None = None) -> str:
    root = Path(root_dir) if root_dir else config.root_dir
    trials_dir = root / "docs" / "trials"

    scores: dict[str, ArmScore] = {
        arm.id: ArmScore(arm_id=arm.id, arm_name=arm.name) for arm in config.arms
    }

    if trials_dir.exists():
        for tdir in trials_dir.iterdir():
            if not tdir.is_dir():
                continue
            for rfile in tdir.glob("*.md"):
                if rfile.name.startswith("brief-"):
                    continue
                arm_id = rfile.stem[4:] if rfile.stem.startswith("arm-") else rfile.stem
                if arm_id not in scores:
                    scores[arm_id] = ArmScore(arm_id=arm_id, arm_name=arm_id)

                s = scores[arm_id]
                parsed = parse_trial_report(rfile)
                if parsed:
                    s.trials_run += 1
                    if parsed["success"]:
                        s.successes += 1
                    s.total_steps += parsed["steps"]
                    s.total_errors += parsed["errors"]

    lines = [
        "# Tooling Scorecard & Comparative Verdicts\n",
        f"**Domain:** {config.name} | **Description:** {config.description}\n",
        "| Arm ID | Arm Name | Trials | Success Rate | Avg Steps | Total Errors | Verdict |",
        "|---|---|---|---|---|---|---|",
    ]

    for arm_id, s in scores.items():
        verdict = "Recommended" if s.success_rate >= 80 else ("Use with Caution" if s.success_rate >= 50 else "Not Recommended")
        lines.append(
            f"| `{s.arm_id}` | {s.arm_name} | {s.trials_run} | {s.success_rate:.1f}% | {s.avg_steps:.1f} | {s.total_errors} | {verdict} |"
        )

    lines.append("\n## Analysis & Standing Observations\n")
    lines.append("- Scorecard generated dynamically via `mcp-cocktail scorecard`.")
    lines.append("- Automated trial mining aggregates step counts and verified readbacks.\n")

    out_text = "\n".join(lines)
    scorecard_path = root / "docs" / "tooling-scorecard.md"
    scorecard_path.parent.mkdir(parents=True, exist_ok=True)
    scorecard_path.write_text(out_text, encoding="utf-8")

    return out_text


def propose_rsi_guardrails(root_dir: Path | str | None = None) -> list[dict[str, Any]]:
    """Scan findings inbox and identify candidate guardrail rules using Weakness Maximization."""
    root = Path(root_dir) if root_dir else Path.cwd()
    inbox_path = root / "docs" / "findings-inbox.md"

    if not inbox_path.exists():
        return []

    lines = inbox_path.read_text(encoding="utf-8").splitlines()
    candidates = []

    for line in lines:
        if not line.startswith("- ["):
            continue

        if re.search(r"\b(rejects|ignores|fails|hangs|trap|deadlock|drop|silent)\b", line, re.I):
            rule = derive_weakest_rule(line)
            candidates.append({
                "source_line": line,
                "suggested_message": rule.message,
                "rule_id_proposal": rule.id,
                "target_matcher_proposal": rule.target_matcher,
                "weakness_optimized": True,
            })

    return candidates


def generate_upstream_bug_draft(
    observation: str,
    arm_name: str,
    root_dir: Path | str | None = None,
) -> Path:
    """Exhaust 4: Generate a structured upstream bug report draft for vendor bug trackers."""
    root = Path(root_dir) if root_dir else Path.cwd()
    upstream_dir = root / "docs" / "upstream"
    upstream_dir.mkdir(parents=True, exist_ok=True)

    date_str = time.strftime("%Y-%m-%d", time.gmtime())
    slug = re.sub(r"[^a-z0-9]", "-", observation.lower())[:35].strip("-")
    filename = f"{date_str}-{slug}.md"
    file_path = upstream_dir / filename

    content = f"""# Upstream Bug Draft: {observation}

**Target Tool / Arm:** {arm_name}
**Date Identified:** {date_str}
**Status:** Draft for Upstream Submission `[feedback]`

## Summary
{observation}

## Observed Behavior
Executing the tool payload produces an inconsistent or unhandled result:
- The command returns success or non-zero status unexpectedly.
- State mutation is silently dropped or argument parsing ignores positional parameters.

## Reproduction Steps
1. Invocations executed against `{arm_name}`.
2. Tool call payload:
   ```json
   {{
     "observation": "{observation}"
   }}
   ```
3. Read-back verification failed or state was left at default.

## Expected Behavior
The tool should validate parameters strictly or echo modified state upon completion.
"""
    file_path.write_text(content, encoding="utf-8")
    return file_path


def generate_patch_task(
    observation: str,
    arm_id: str,
    repo_path: str,
) -> dict[str, Any]:
    """Exhaust 3: Generate an open-source bug fix subagent task spec."""
    return {
        "name": f"Fix_{arm_id}_{re.sub(r'[^a-zA-Z0-9]', '', observation)[:15]}",
        "agent": "task",
        "task": f"""# Open-Source Fix Task — {arm_id}

**Target Repository:** `{repo_path}`
**Issue to Fix:** {observation}

## Instructions for Fix Agent
1. Locate the source code handling the affected command / tool invocation in `{repo_path}`.
2. Write a failing reproduction test reproducing: '{observation}'.
3. Implement the fix cleanly in source code.
4. Verify the test passes.
5. Create a clean git commit or patch file.
""",
    }
