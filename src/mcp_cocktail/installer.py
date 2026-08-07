"""Automated PreToolUse hook installer for mcp-cocktail."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

DEFAULT_HOOK_COMMAND = "mcp-cocktail check"


def get_settings_path(global_settings: bool = False, target_path: str | None = None) -> Path:
    if target_path:
        return Path(target_path)
    if global_settings:
        return Path(os.path.expanduser("~/.claude/settings.json"))
    return Path.cwd() / ".claude" / "settings.json"


def load_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def is_mcp_cocktail_hook(hook_cmd: str) -> bool:
    return "mcp-cocktail check" in hook_cmd or "mcp_cocktail check" in hook_cmd or "cocktail check" in hook_cmd


def install_hook(
    global_settings: bool = False,
    target_path: str | None = None,
    custom_traps: str | None = None,
    matcher: str = "Bash|PowerShell|mcp__.*",
) -> tuple[bool, str]:
    path = get_settings_path(global_settings, target_path)
    data = load_settings(path)

    hooks_sec = data.setdefault("hooks", {})
    pre_tool = hooks_sec.setdefault("PreToolUse", [])

    command_str = DEFAULT_HOOK_COMMAND
    if custom_traps:
        command_str += f" --traps \"{custom_traps}\""

    target_hook_obj = {
        "type": "command",
        "command": command_str,
        "timeout": 10,
    }

    # Check if entry already exists under matcher
    matcher_entry = None
    for entry in pre_tool:
        if isinstance(entry, dict) and entry.get("matcher") == matcher:
            matcher_entry = entry
            break

    if matcher_entry is None:
        matcher_entry = {"matcher": matcher, "hooks": []}
        pre_tool.append(matcher_entry)

    # Check if cocktail hook is already inside hooks list
    hooks_list = matcher_entry.setdefault("hooks", [])
    already_installed = False

    for idx, h in enumerate(hooks_list):
        if isinstance(h, dict) and is_mcp_cocktail_hook(h.get("command", "")):
            hooks_list[idx] = target_hook_obj
            already_installed = True
            break

    if not already_installed:
        hooks_list.append(target_hook_obj)

    save_settings(path, data)
    status = "Updated" if already_installed else "Installed"
    return True, f"{status} mcp-cocktail PreToolUse hook in {path}"


def uninstall_hook(
    global_settings: bool = False,
    target_path: str | None = None,
) -> tuple[bool, str]:
    path = get_settings_path(global_settings, target_path)
    if not path.exists():
        return False, f"Settings file {path} does not exist."

    data = load_settings(path)
    hooks_sec = data.get("hooks", {})
    pre_tool = hooks_sec.get("PreToolUse", [])

    removed = False
    new_pre_tool = []

    for entry in pre_tool:
        if not isinstance(entry, dict):
            new_pre_tool.append(entry)
            continue

        hooks_list = entry.get("hooks", [])
        new_hooks_list = []
        for h in hooks_list:
            if isinstance(h, dict) and is_mcp_cocktail_hook(h.get("command", "")):
                removed = True
            else:
                new_hooks_list.append(h)

        if new_hooks_list:
            entry["hooks"] = new_hooks_list
            new_pre_tool.append(entry)

    if removed:
        data["hooks"]["PreToolUse"] = new_pre_tool
        save_settings(path, data)
        return True, f"Uninstalled mcp-cocktail PreToolUse hook from {path}"

    return False, f"No mcp-cocktail PreToolUse hook found in {path}"
