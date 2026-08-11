"""Non-polluting PreToolUse hook installer for mcp-cocktail.

Detects the specific active agent harness running right now (Claude, OMP, MCP)
and configures ONLY the active harness without creating unused configuration
directories or polluting the workspace. Uses .agents/ as canonical source.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

DEFAULT_HOOK_COMMAND = "mcp-cocktail check"

# Harness-level matchers filter by tool name *before* the hook process starts, so
# anything they exclude is invisible to every rule in traps.json regardless of that
# rule's own tool_matcher. Subscribe to all tools and let the rules do the filtering:
# the weakest valid matcher is the one that cannot silently strand a rule.
DEFAULT_HOOK_MATCHER = "*"


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


def provision_tree(src: Path, dst: Path) -> tuple[list[str], list[str]]:
    """Merge a preset directory into a workspace, never overwriting.

    An all-or-nothing `copytree` guarded on `not dst.exists()` skips the whole
    provisioning step whenever the workspace already has a directory of that
    name -- which for any real project is the common case, and which silently
    leaves declared setup_scripts undelivered. Merging per file keeps the
    don't-clobber guarantee at the granularity where it belongs.

    Returns (copied, skipped) as workspace-relative posix paths.
    """
    copied: list[str] = []
    skipped: list[str] = []

    if not src.is_dir():
        return copied, skipped

    for source_file in sorted(p for p in src.rglob("*") if p.is_file()):
        relative = source_file.relative_to(src)
        target = dst / relative

        if target.exists():
            skipped.append(relative.as_posix())
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target)  # copy2 preserves the executable bit
        copied.append(relative.as_posix())

    return copied, skipped


def is_mcp_cocktail_hook(hook_cmd: str) -> bool:
    return "mcp-cocktail check" in hook_cmd or "mcp_cocktail check" in hook_cmd or "cocktail check" in hook_cmd


def strip_cocktail_hooks(pre_tool: list[Any]) -> tuple[list[Any], int]:
    """Remove every cocktail hook from a PreToolUse list, whatever its matcher.

    Scanning only the entry matching the matcher we are about to write leaves
    hooks installed under any previous matcher in place, and the harness runs
    all matching entries -- so the agent receives one copy of every reminder
    per surviving entry.
    """
    kept: list[Any] = []
    removed = 0

    for entry in pre_tool:
        if not isinstance(entry, dict):
            kept.append(entry)
            continue

        surviving = []
        for hook in entry.get("hooks", []):
            if isinstance(hook, dict) and is_mcp_cocktail_hook(hook.get("command", "")):
                removed += 1
            else:
                surviving.append(hook)

        # An entry that existed only to carry a cocktail hook goes with it.
        if surviving:
            entry["hooks"] = surviving
            kept.append(entry)

    return kept, removed


def render_traps_arg(traps_path: str | Path | None, harness: str, root: Path | None = None) -> str:
    """Render the --traps value so a committed settings.json travels between machines.

    An absolute path bakes one developer's drive layout into the file the
    README tells teams to commit, which is the opposite of inheriting the
    guardrails.
    """
    if not traps_path:
        return ""

    base = (root or Path.cwd()).resolve()
    path = Path(traps_path)

    try:
        rel = path.resolve().relative_to(base).as_posix()
    except ValueError:
        return f' --traps "{path}"'  # genuinely outside the project; leave it alone

    if harness.lower().strip() == "claude":
        return f' --traps "$CLAUDE_PROJECT_DIR/{rel}"'

    return f' --traps "{rel}"'


def install_hook_for_harness(
    harness: str = "claude",
    global_settings: bool = False,
    target_path: str | None = None,
    custom_traps: str | None = None,
    matcher: str = DEFAULT_HOOK_MATCHER,
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

    traps_target = custom_traps
    if not traps_target and (Path.cwd() / ".agents" / "traps.json").exists():
        traps_target = Path.cwd() / ".agents" / "traps.json"

    command_str = DEFAULT_HOOK_COMMAND + render_traps_arg(traps_target, h_clean)

    target_hook_obj = {
        "type": "command",
        "command": command_str,
        "timeout": 10,
    }

    # Clear every prior cocktail hook first, whatever matcher carried it, so a
    # re-run repairs the configuration instead of stacking a second copy.
    cleaned, removed = strip_cocktail_hooks(pre_tool)
    hooks_sec["PreToolUse"] = cleaned

    matcher_entry = None
    for entry in cleaned:
        if isinstance(entry, dict) and entry.get("matcher") == matcher:
            matcher_entry = entry
            break

    if matcher_entry is None:
        matcher_entry = {"matcher": matcher, "hooks": []}
        cleaned.append(matcher_entry)

    matcher_entry.setdefault("hooks", []).append(target_hook_obj)

    save_json_file(path, data)
    status = f"Replaced {removed} existing" if removed else "Installed"
    return True, f"{status} mcp-cocktail PreToolUse hook for '{harness}' in {path}"


def install_hook(
    harness: str | None = None,
    global_settings: bool = False,
    target_path: str | None = None,
    custom_traps: str | None = None,
    matcher: str = DEFAULT_HOOK_MATCHER,
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

    new_pre_tool, removed = strip_cocktail_hooks(pre_tool)

    if removed:
        data["hooks"]["PreToolUse"] = new_pre_tool
        save_json_file(path, data)
        return True, f"Uninstalled {removed} mcp-cocktail PreToolUse hook(s) from {path}"

    return False, f"No mcp-cocktail PreToolUse hook found in {path}"
