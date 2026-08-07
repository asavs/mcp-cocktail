"""Multi-arm subagent trial runner and brief generator for mcp-cocktail."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_cocktail.config import CocktailConfig, ArmConfig


@dataclass
class TrialSpec:
    id: str
    task_description: str
    target_arms: list[str]
    concurrency: str = "serial"
    scene_strategy: str = "instant_reload"
    timeout_seconds: int = 300


BRIEF_TEMPLATE = """# Trial Brief — Arm {arm_id} ({arm_name})

**Task:**
{task_description}

## Arm Instructions & Scope
- **Arm ID:** `{arm_id}`
- **Arm Type:** `{arm_type}`
- **Scene Isolation Strategy:** `{scene_strategy}`
{arm_details}

## Execution Rules & Constraints
1. **Tool Lock:** You MUST only use tools designated for Arm `{arm_id}`.
2. **State Verification:** A write that does not echo the resulting state has not been verified. Read back state after mutating.
3. **Scene Isolation:** {scene_instructions}
4. **No Spillover:** Do not modify or interact with other arms' components or processes.
5. **Log Friction:** Record every error, unexpected hang, silent failure, or unexpected behaviour verbatim.

## Deliverable
Write your complete trial report to `docs/trials/{trial_id}/arm-{arm_id}.md`.
Include:
- Exact tool calls executed in chronological order
- Total steps & retries
- Errors encountered & resolution
- Read-back verification evidence
- Verdict (Success / Partial / Failure)
"""


def generate_arm_brief(trial: TrialSpec, arm: ArmConfig) -> str:
    arm_details_lines = []
    if arm.command:
        arm_details_lines.append(f"- **CLI Command:** `{arm.command}`")
    if arm.mcp_server:
        arm_details_lines.append(f"- **MCP Server:** `{arm.mcp_server}`")
    if arm.tool_prefix:
        arm_details_lines.append(f"- **Tool Prefix Filter:** `{arm.tool_prefix}`")
    if arm.env:
        arm_details_lines.append(f"- **Environment Vars:** `{json.dumps(arm.env)}`")

    if trial.scene_strategy == "temp_scene":
        scene_instructions = f"Work inside a dedicated temporary scene file: `Assets/Scenes/Trial_{trial.id}_Arm_{arm.id}.unity`. Duplicate baseline scene before mutating."
    else:
        scene_instructions = "Work in the baseline active scene. The trial runner will reset scene state (git checkout) upon trial completion."

    return BRIEF_TEMPLATE.format(
        trial_id=trial.id,
        arm_id=arm.id,
        arm_name=arm.name,
        arm_type=arm.type,
        scene_strategy=trial.scene_strategy,
        task_description=trial.task_description,
        arm_details="\n".join(arm_details_lines),
        scene_instructions=scene_instructions,
    )


def setup_trial_directory(trial_id: str, root_dir: Path | str | None = None) -> Path:
    root = Path(root_dir) if root_dir else Path.cwd()
    trial_dir = root / "docs" / "trials" / trial_id
    trial_dir.mkdir(parents=True, exist_ok=True)
    return trial_dir


def create_trial(
    trial_id: str,
    task_description: str,
    config: CocktailConfig,
    arms_override: list[str] | None = None,
    exec_mode: str | None = None,
    scene_strategy: str | None = None,
    compare_visual: bool = False,
) -> dict[str, Any]:
    """Generate briefs for all targeted arms and prepare trial files."""
    trial_dir = setup_trial_directory(trial_id, config.root_dir)

    target_arm_ids = arms_override or [a.id for a in config.arms]

    # Resolve scene strategy
    if compare_visual or scene_strategy == "temp_scene":
        eff_strategy = "temp_scene"
    elif scene_strategy in ("instant_reload", "auto") or not scene_strategy:
        eff_strategy = config.trial_defaults.scene_strategy if config.trial_defaults.scene_strategy != "auto" else "instant_reload"
    else:
        eff_strategy = scene_strategy

    trial = TrialSpec(
        id=trial_id,
        task_description=task_description,
        target_arms=target_arm_ids,
        concurrency=config.trial_defaults.concurrency,
        scene_strategy=eff_strategy,
        timeout_seconds=config.trial_defaults.timeout_seconds,
    )

    briefs: dict[str, str] = {}
    task_payloads: list[dict[str, Any]] = []

    for arm in config.arms:
        if arm.id in target_arm_ids:
            brief = generate_arm_brief(trial, arm)
            brief_file = trial_dir / f"brief-arm-{arm.id}.md"
            brief_file.write_text(brief, encoding="utf-8")
            briefs[arm.id] = brief

            task_payloads.append({
                "name": f"Trial_{trial_id}_{arm.id.replace('-', '_')}",
                "arm": arm.id,
                "scene_strategy": eff_strategy,
                "task": brief,
            })

    meta = {
        "id": trial.id,
        "task_description": trial.task_description,
        "arms": target_arm_ids,
        "concurrency": trial.concurrency,
        "scene_strategy": eff_strategy,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (trial_dir / "trial-meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (trial_dir / "trial-tasks.json").write_text(json.dumps(task_payloads, indent=2), encoding="utf-8")

    return {
        "briefs": briefs,
        "tasks_file": str(trial_dir / "trial-tasks.json"),
        "exec_mode": exec_mode,
        "concurrency": trial.concurrency,
        "scene_strategy": eff_strategy,
    }
