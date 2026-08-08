"""Non-polluting PreToolUse hook installer for mcp-cocktail.

Detects the specific active agent harness running right now (Claude, OMP, MCP)
and configures ONLY the active harness without creating unused configuration
directories or polluting the workspace. Uses .agents/ as canonical source.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_HOOK_COMMAND = "mcp-cocktail check"


def detect_domain_preset(target_dir: Path | str | None = None) -> str:
    """Auto-detect the workspace domain preset based on file signatures."""
    root = Path(target_dir) if target_dir else Path.cwd()

    if (root / "Assets").exists() or (root / "ProjectSettings").exists() or list(root.glob("*.csproj")):
        return "unity"
    if (root / "Dockerfile").exists() or (root / "docker-compose.yml").exists():
        return "docker"
    if (root / "package.json").exists():
        return "node"

    return "unity"


def detect_current_active_harness(target_dir: Path | str | None = None) -> str:
    """Detect the specific agent harness executing right now or configured in workspace.

    Checks environment variables (CLAUDE_SESSION_ID, OMP_SESSION_ID) and existing
    local workspace directories (.claude, .omp, mcp.json).
    NEVER creates config directories for inactive harnesses.
    """
    root = Path(target_dir) if target_dir else Path.cwd()

    # 1. Runtime environment variable detection
    if os.environ.get("OMP_SESSION_ID") or os.environ.get("OMP_DIR"):
        return "omp"
    if os.environ.get("CLAUDE_SESSION_ID"):
        return "claude"

    # 2. Existing local workspace directory detection
    if (root / ".omp").exists():
        return "omp"
    if (root / ".claude").exists():
        return "claude"
    if (root / "mcp.json").exists():
        return "mcp"

    # 3. User home folder presence
    if Path(os.path.expanduser("~/.omp")).exists() and not Path(os.path.expanduser("~/.claude")).exists():
        return "omp"

    return "claude"


def get_harness_settings_path(
    harness: str = "claude",
    global_settings: bool = False,
    target_path: str | None = None,
) -> Path:
    if target_path:
        return Path(target_path)

    h_clean = harness.lower().strip()
    if h_clean == "omp":
        if global_settings:
            return Path(os.path.expanduser("~/.omp/settings.json"))
        return Path.cwd() / ".omp" / "settings.json"
    elif h_clean == "mcp":
        if global_settings:
            return Path(os.environ.get("APPDATA", os.path.expanduser("~"))) / "Claude" / "claude_desktop_config.json"
        return Path.cwd() / "mcp.json"
    else:  # claude / default
        if global_settings:
            return Path(os.path.expanduser("~/.claude/settings.json"))
        return Path.cwd() / ".claude" / "settings.json"


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def is_mcp_cocktail_hook(hook_cmd: str) -> bool:
    return "mcp-cocktail check" in hook_cmd or "mcp_cocktail check" in hook_cmd or "cocktail check" in hook_cmd


def install_hook_for_harness(
    harness: str = "claude",
    global_settings: bool = False,
    target_path: str | None = None,
    custom_traps: str | None = None,
    matcher: str = "Bash|PowerShell|mcp__.*",
) -> tuple[bool, str]:
    path = get_harness_settings_path(harness, global_settings, target_path)
    data = load_json_file(path)
    h_clean = harness.lower().strip()

    if h_clean == "mcp":
        mcp_servers = data.setdefault("mcpServers", {})
        mcp_servers["mcp-cocktail"] = {
            "command": "mcp-cocktail",
            "args": ["serve"],
        }
        save_json_file(path, data)
        return True, f"Installed mcp-cocktail stdio MCP server in {path}"

    hooks_sec = data.setdefault("hooks", {})
    pre_tool = hooks_sec.setdefault("PreToolUse", [])

    command_str = DEFAULT_HOOK_COMMAND
    if custom_traps:
        command_str += f" --traps \"{custom_traps}\""
    elif (Path.cwd() / ".agents" / "traps.json").exists():
        command_str += ' --traps ".agents/traps.json"'

    target_hook_obj = {
        "type": "command",
        "command": command_str,
        "timeout": 10,
    }

    matcher_entry = None
    for entry in pre_tool:
        if isinstance(entry, dict) and entry.get("matcher") == matcher:
            matcher_entry = entry
            break

    if matcher_entry is None:
        matcher_entry = {"matcher": matcher, "hooks": []}
        pre_tool.append(matcher_entry)

    hooks_list = matcher_entry.setdefault("hooks", [])
    already_installed = False

    for idx, h in enumerate(hooks_list):
        if isinstance(h, dict) and is_mcp_cocktail_hook(h.get("command", "")):
            hooks_list[idx] = target_hook_obj
            already_installed = True
            break

    if not already_installed:
        hooks_list.append(target_hook_obj)

    save_json_file(path, data)
    status = "Updated" if already_installed else "Installed"
    return True, f"{status} mcp-cocktail PreToolUse hook for '{harness}' in {path}"


def install_hook(
    harness: str | None = None,
    global_settings: bool = False,
    target_path: str | None = None,
    custom_traps: str | None = None,
    matcher: str = "Bash|PowerShell|mcp__.*",
) -> tuple[bool, str]:
    """Install hook into ONLY the active harness. Auto-detects runtime environment if harness is None or 'auto'."""
    if not harness or harness.lower().strip() == "auto":
        target_harness = detect_current_active_harness()
    else:
        target_harness = harness

    return install_hook_for_harness(
        harness=target_harness,
        global_settings=global_settings,
        target_path=target_path,
        custom_traps=custom_traps,
        matcher=matcher,
    )


def uninstall_hook(
    harness: str | None = None,
    global_settings: bool = False,
    target_path: str | None = None,
) -> tuple[bool, str]:
    target_harness = detect_current_active_harness() if (not harness or harness.lower().strip() == "auto") else harness
    path = get_harness_settings_path(target_harness, global_settings, target_path)

    if not path.exists():
        return False, f"Settings file {path} does not exist."

    data = load_json_file(path)
    h_clean = target_harness.lower().strip()

    if h_clean == "mcp":
        if "mcpServers" in data and "mcp-cocktail" in data["mcpServers"]:
            del data["mcpServers"]["mcp-cocktail"]
            save_json_file(path, data)
            return True, f"Uninstalled mcp-cocktail MCP server from {path}"
        return False, f"No mcp-cocktail MCP server entry in {path}"

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
        for item in hooks_list:
            if isinstance(item, dict) and is_mcp_cocktail_hook(item.get("command", "")):
                removed = True
            else:
                new_hooks_list.append(item)

        if new_hooks_list:
            entry["hooks"] = new_hooks_list
            new_pre_tool.append(entry)

    if removed:
        data["hooks"]["PreToolUse"] = new_pre_tool
        save_json_file(path, data)
        return True, f"Uninstalled mcp-cocktail PreToolUse hook from {path}"

    return False, f"No mcp-cocktail PreToolUse hook found in {path}"
