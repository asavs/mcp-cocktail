"""Render the acquisition plan for arms a workspace does not yet have.

Deliberately a planner, not a package manager. The arms in a real preset do
not share one install shape -- some are a single `npx`, some are a Unity
package plus a separate server process, one has no shell installer at all and
is provisioned by a button inside the Editor. A command runner would have to
either cover a fraction of them or invent the rest, and running third-party
installers unattended is a much larger promise than this tool makes anywhere
else. Printing the exact documented steps is the part that is always correct.
"""

from __future__ import annotations

import json
from typing import Any

from mcp_cocktail.config import ArmConfig, CocktailConfig

INDENT = "    "


def format_client_config(client_config: Any) -> list[str]:
    """Render the harness registration snippet an arm documents."""
    if not client_config:
        return []

    if isinstance(client_config, str):
        return client_config.splitlines()

    return json.dumps(client_config, indent=2).splitlines()


def render_arm_plan(arm: ArmConfig) -> list[str]:
    """One arm's acquisition block. Empty when the arm records no route."""
    install = arm.install or {}
    lines: list[str] = []

    header = f"{arm.id}  ({arm.name})"
    lines.append(header)
    lines.append("-" * len(header))

    if arm.probe == "unverified":
        lines.append(f"{INDENT}UNVERIFIED — this entry could not be tied to a real upstream")
        lines.append(f"{INDENT}project. Nothing below is a working install route.")
        if arm.probe_reason:
            lines.append(f"{INDENT}{arm.probe_reason}")

    if install.get("method"):
        lines.append(f"{INDENT}method: {install['method']}")
    if install.get("requires_editor"):
        lines.append(f"{INDENT}requires the Unity Editor to be running")

    for i, step in enumerate(install.get("steps") or [], 1):
        lines.append(f"{INDENT}{i}. {step}")

    if install.get("command"):
        lines.append(f"{INDENT}install:")
        for line in str(install["command"]).splitlines():
            lines.append(f"{INDENT}{INDENT}{line}")

    if install.get("package_url"):
        lines.append(f"{INDENT}Unity Package Manager -> Add package from git URL:")
        lines.append(f"{INDENT}{INDENT}{install['package_url']}")

    client_lines = format_client_config(install.get("client_config"))
    if client_lines:
        lines.append(f"{INDENT}register with your harness:")
        for line in client_lines:
            lines.append(f"{INDENT}{INDENT}{line}")

    if install.get("docs_url"):
        lines.append(f"{INDENT}docs: {install['docs_url']}")

    if install.get("note"):
        lines.append(f"{INDENT}note: {install['note']}")

    # Header plus nothing actionable is worse than saying so outright.
    if len(lines) <= 2:
        lines.append(f"{INDENT}No install route is recorded for this arm.")

    return lines


def render_install_plan(config: CocktailConfig, arm_ids: list[str] | None = None) -> tuple[str, list[str]]:
    """Acquisition plan for the named arms, or every arm. Returns (text, unknown_ids)."""
    by_id = {a.id: a for a in config.arms}
    unknown = [a for a in (arm_ids or []) if a not in by_id]
    selected = [by_id[a] for a in arm_ids if a in by_id] if arm_ids else list(config.arms)

    out: list[str] = []
    out.append(f"=== mcp-cocktail: how to obtain {config.name} arms ===")
    out.append("")

    if not selected:
        out.append("No arms selected.")
        return "\n".join(out), unknown

    for arm in selected:
        out.extend(render_arm_plan(arm))
        out.append("")

    routed = sum(1 for a in selected if a.install or a.setup_script)
    out.append(f"{routed}/{len(selected)} arm(s) record an install route.")
    out.append("These steps are printed, never executed: they install third-party software")
    out.append("and several need choices only you can make (which Unity project, which port).")

    return "\n".join(out), unknown
