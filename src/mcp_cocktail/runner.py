"""Harness-neutral trial planning and brief generation for mcp-cocktail.

This module deliberately does not launch agents, schedule arms, reset an Editor,
or roll back a workspace.  Those lifecycle operations require a real harness
adapter; representing a plan as an executed trial would make the resulting
evidence untrustworthy.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_cocktail.config import CocktailConfig, ArmConfig
from mcp_cocktail.trial_state import (
    UNITY_SHARED_RESOURCE,
    TrialStage,
    TrialStateStore,
)


class ExecutionUnavailableError(RuntimeError):
    """Raised when execution is requested without an installed executor."""


class TrialPlanError(RuntimeError):
    """Base class for a trial plan that cannot be published safely."""


class InvalidTrialIdError(TrialPlanError, ValueError):
    """Raised when a trial ID is unsafe to use as one directory name."""


class TrialAlreadyExistsError(TrialPlanError, FileExistsError):
    """Raised when a trial ID has already been reserved."""


class EmptyTrialPlanError(TrialPlanError, ValueError):
    """Raised when arm selection would publish a trial with no executable tasks."""


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


@dataclass
class TrialSpec:
    id: str
    task_description: str
    target_arms: list[str]
    concurrency: str = "serial"
    scene_strategy: str = "instant_reload"
    timeout_seconds: int = 300


BRIEF_TEMPLATE = """# Trial Brief — {arm_name} (`{arm_id}`)

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
6. **Scheduling Contract:** {schedule_instructions}
{type_specific_rules}

## Deliverable
Write your complete trial report to `docs/trials/{trial_id}/{arm_id}.md`.
Include:
- Exact tool calls executed in chronological order
- Total steps & retries
- Errors encountered & resolution
- Read-back verification evidence
- Verdict (Success / Partial / Failure)
"""


GUI_RULES = """7. **Exclusive Input:** This GUI arm requires exclusive mouse and keyboard control. It MUST run serially and no other agent may interact with the shared Editor during its turn.
8. **Visible Interaction Only:** Use only the computer-use/GUI controls assigned to this arm. Do not fall back to CLI, MCP, direct file edits, or another arm's automation channel.
9. **Visual Evidence:** Capture before-and-after screenshots that show the relevant Unity window and result.
10. **GUI State Read-back:** Harness-level computer-use availability is not proof that Unity is responsive. After every mutation, inspect the resulting target state in the visible Unity UI (for example, Hierarchy plus Inspector) and capture that read-back in a screenshot. A click sequence or screenshot of an action in progress is not verification.
11. **Shared Editor Safety:** Treat the Unity Editor, active scene, selection, focus, modal dialogs, play mode, and domain reloads as shared global state. Do not close or restart the Editor without explicit authorization. Leave it stable and report any modal or reload before the next arm starts.
12. **Responsiveness Stop:** If the Editor stops responding, stop the arm. Record the last responsive screenshot and attempted action; do not keep clicking, restart Unity, or claim success.
13. **GUI Coverage:** Exercise and report GUI-only strengths when relevant, including modal dialogs, Console and Package Manager workflows, and scene placement that requires visible context."""


def generate_arm_brief(trial: TrialSpec, arm: ArmConfig) -> str:
    arm_details_lines = []
    if arm.description:
        arm_details_lines.append(f"- **Description:** {arm.description}")
    if arm.capabilities:
        arm_details_lines.append(f"- **Key Capabilities:** {', '.join(arm.capabilities)}")
    if arm.command:
        arm_details_lines.append(f"- **CLI Command:** `{arm.command}`")
    if arm.mcp_server:
        arm_details_lines.append(f"- **MCP Server:** `{arm.mcp_server}`")
    if arm.tool_prefix:
        arm_details_lines.append(f"- **Tool Prefix Filter:** `{arm.tool_prefix}`")
    if arm.env:
        arm_details_lines.append(f"- **Environment Vars:** `{json.dumps(arm.env)}`")

    type_specific_rules = GUI_RULES if arm.type.lower() == "gui" else ""
    schedule_instructions = (
        "This arm shares the trial workspace and may mutate it even when it does not directly "
        "control the Unity Editor. Before acting, acquire the declared shared-resource lease with "
        f"`mcp-cocktail trial acquire {trial.id} --owner <adapter>`, then admit this stage with "
        f"`mcp-cocktail trial begin {trial.id} --stage arm-{arm.id} --arm {arm.id} "
        "--owner <adapter> --token <token>`. Run it serially; a task payload is not permission "
        "to overlap mutations. Finish and release through the same `mcp-cocktail trial` protocol."
    )

    if trial.scene_strategy == "temp_scene":
        scene_instructions = f"Work inside a dedicated temporary scene file: `Assets/Scenes/Trial_{trial.id}_{arm.id}.unity`. Duplicate the baseline scene before mutating. Cocktail only planned this path; your harness must perform and verify the duplication."
    else:
        scene_instructions = "Work in the baseline active scene only if your harness has established a safe baseline. Cocktail does not reset the Editor, run git checkout, roll back files, or protect uncommitted work. The executing harness must provide and verify any isolation and cleanup."

    return BRIEF_TEMPLATE.format(
        trial_id=trial.id,
        arm_id=arm.id,
        arm_name=arm.name,
        arm_type=arm.type,
        scene_strategy=trial.scene_strategy,
        task_description=trial.task_description,
        arm_details="\n".join(arm_details_lines),
        scene_instructions=scene_instructions,
        type_specific_rules=type_specific_rules,
        schedule_instructions=schedule_instructions,
    )


def _validate_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value):
        raise InvalidTrialIdError(
            f"Invalid {label} {value!r}: use 1-128 ASCII letters, digits, '_' or '-' "
            "and start with a letter or digit. Paths and '..' are not allowed."
        )


def _atomic_write_text(path: Path, content: str) -> None:
    """Publish a complete UTF-8 file in one replace operation."""
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass


def setup_trial_directory(trial_id: str, root_dir: Path | str | None = None) -> Path:
    """Atomically reserve a never-before-used trial directory."""
    _validate_identifier(trial_id, "trial ID")
    root = Path(root_dir) if root_dir else Path.cwd()
    trials_dir = root / "docs" / "trials"
    trials_dir.mkdir(parents=True, exist_ok=True)
    trial_dir = trials_dir / trial_id
    try:
        trial_dir.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise TrialAlreadyExistsError(
            f"Trial '{trial_id}' already exists at {trial_dir}; refusing to overwrite its plan or evidence. "
            "Choose a new trial ID."
        ) from exc
    return trial_dir


def plan_trial(
    trial_id: str,
    task_description: str,
    config: CocktailConfig,
    arms_override: list[str] | None = None,
    scene_strategy: str | None = None,
    compare_visual: bool = False,
    capability: str | None = None,
) -> dict[str, Any]:
    """Write a trial plan and arm briefs without executing any agent or tool."""
    _validate_identifier(trial_id, "trial ID")

    # A trial across every arm in the manifest is not automatically a
    # comparison. rage-cli installs and launches Unity for CI; the other CLI
    # arms drive an Editor that is already running. Handing both the same task
    # measures nothing -- one of them cannot perform it at all -- and the
    # resulting scorecard reads as a defeat rather than a category error.
    eligible = [a for a in config.arms if not capability or capability in a.capabilities]
    target_arm_ids = arms_override or [a.id for a in eligible]
    known_arm_ids = {arm.id for arm in config.arms}
    unknown_arm_ids = sorted(set(target_arm_ids) - known_arm_ids)
    if unknown_arm_ids:
        raise EmptyTrialPlanError(
            f"Unknown arm(s): {', '.join(unknown_arm_ids)}. No trial artifacts were written."
        )
    if not target_arm_ids:
        known_capabilities = sorted({item for arm in config.arms for item in arm.capabilities})
        detail = (
            f" No arm declares capability {capability!r}. Known capabilities: "
            f"{', '.join(known_capabilities) or '(none)'}"
            if capability else " No arms are configured."
        )
        raise EmptyTrialPlanError(f"Trial would contain no arms.{detail} No trial artifacts were written.")

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
    planned_stages: list[TrialStage] = []

    for arm in config.arms:
        if arm.id in target_arm_ids:
            _validate_identifier(arm.id, "arm ID")
            brief = generate_arm_brief(trial, arm)
            briefs[arm.id] = brief

            # Every benchmark arm receives the same repository and may write files,
            # even when its declared capability is CI or project lifecycle rather
            # than direct Editor automation. Serialize mutations until a future
            # executor can prove it has provisioned an isolated workspace clone.
            shared_resources = [UNITY_SHARED_RESOURCE]
            stage_id = f"arm-{arm.id}"
            planned_stages.append(TrialStage(
                id=stage_id,
                capability=capability or "benchmark-task",
                assigned_arm=arm.id,
            ))
            task_payloads.append({
                "name": f"Trial_{trial_id}_{arm.id.replace('-', '_')}",
                "arm": arm.id,
                "stage_id": stage_id,
                "description": arm.description,
                "arm_type": arm.type,
                "capabilities": arm.capabilities,
                "requires_exclusive_input": arm.type.lower() == "gui",
                "shared_resources": shared_resources,
                "requires_mutation_lease": bool(shared_resources),
                "requested_concurrency": trial.concurrency,
                "timeout_seconds": trial.timeout_seconds,
                "scene_strategy": eff_strategy,
                "task": brief,
            })

    root = Path(config.root_dir)
    trials_dir = root / "docs" / "trials"
    trials_dir.mkdir(parents=True, exist_ok=True)
    final_trial_dir = trials_dir / trial_id
    if final_trial_dir.exists():
        raise TrialAlreadyExistsError(
            f"Trial '{trial_id}' already exists at {final_trial_dir}; refusing to overwrite its plan or evidence. Choose a new trial ID."
        )
    # Build the complete plan out of sight. The final directory appears only
    # after every file and the completion marker have been fsynced.
    trial_dir = Path(tempfile.mkdtemp(prefix=f".{trial_id}.", suffix=".staging", dir=trials_dir))
    published = False
    try:
        for arm_id, brief in briefs.items():
            _atomic_write_text(trial_dir / f"brief-{arm_id}.md", brief)

        meta = {
            "id": trial.id,
            "task_description": trial.task_description,
            "arms": target_arm_ids,
            "concurrency": trial.concurrency,
            "scene_strategy": eff_strategy,
            "timeout_seconds": trial.timeout_seconds,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "lifecycle": {
                "phase": "planned",
                "executed": False,
                "executor": None,
                "note": "Cocktail generated artifacts only; no agent was launched and no reset or rollback was performed.",
            },
            "execution_contract": {
                "requested_concurrency": trial.concurrency,
                "lease_directory": ".agents/leases",
                "state_file": "trial-state.json",
                "note": "External harnesses must honor each task's shared_resources before execution.",
            },
        }
        _atomic_write_text(trial_dir / "trial-meta.json", json.dumps(meta, indent=2))
        _atomic_write_text(trial_dir / "trial-tasks.json", json.dumps(task_payloads, indent=2))
        state_store = TrialStateStore(trial_dir / "trial-state.json", trial_id)
        for stage in planned_stages:
            state_store.add_stage(stage)
        _atomic_write_text(trial_dir / ".plan-complete", "schema_version=1\n")
        try:
            trial_dir.rename(final_trial_dir)
        except (FileExistsError, OSError) as exc:
            if final_trial_dir.exists():
                raise TrialAlreadyExistsError(
                    f"Trial '{trial_id}' was concurrently published at {final_trial_dir}; refusing to overwrite it."
                ) from exc
            raise
        published = True
    finally:
        if not published and trial_dir.exists():
            shutil.rmtree(trial_dir)

    return {
        "briefs": briefs,
        "tasks_file": str(final_trial_dir / "trial-tasks.json"),
        "executed": False,
        "concurrency": trial.concurrency,
        "scene_strategy": eff_strategy,
    }


def create_trial(
    trial_id: str,
    task_description: str,
    config: CocktailConfig,
    arms_override: list[str] | None = None,
    exec_mode: str | None = None,
    scene_strategy: str | None = None,
    compare_visual: bool = False,
    capability: str | None = None,
) -> dict[str, Any]:
    """Backward-compatible alias for :func:`plan_trial`.

    ``exec_mode`` was previously recorded without being acted upon.  It is now
    rejected so callers cannot mistake generated payloads for an executed run.
    """
    if exec_mode is not None:
        raise ExecutionUnavailableError(
            "Agent execution is not available: --exec never launched agents. "
            "Use plan_trial/create_trial without exec_mode and pass trial-tasks.json "
            "to an external harness."
        )
    return plan_trial(
        trial_id=trial_id,
        task_description=task_description,
        config=config,
        arms_override=arms_override,
        scene_strategy=scene_strategy,
        compare_visual=compare_visual,
        capability=capability,
    )
