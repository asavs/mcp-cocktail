"""Arm health verification and diagnostic engine for mcp-cocktail.

Probes HTTP URLs, shell commands, and stdio MCP servers directly by speaking the JSON-RPC
MCP protocol, verifying initialize responses and available tool counts honestly.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_cocktail.config import CocktailConfig, ArmConfig
from mcp_cocktail.console import ensure_utf8_streams


@dataclass
class ArmHealthResult:
    arm_id: str
    arm_name: str
    # "READY", "ASSUMED_READY", "SOCKET_BOUND_ONLY", "BOUND_ELSEWHERE",
    # "UNCONFIGURED", "OFFLINE"
    status: str
    message: str
    details: dict[str, Any]


def extract_json_path(data: Any, path: str) -> list[Any]:
    """Read a dotted path out of parsed JSON. `a.b[].c` maps over the list at b."""
    values: list[Any] = [data]

    for part in path.split("."):
        collected: list[Any] = []
        is_list = part.endswith("[]")
        key = part[:-2] if is_list else part

        for value in values:
            if not isinstance(value, dict) or key not in value:
                continue
            found = value[key]
            if is_list and isinstance(found, list):
                collected.extend(found)
            else:
                collected.append(found)

        values = collected

    return values


def _same_location(a: str, b: str) -> bool:
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except Exception:
        return os.path.normcase(str(a).rstrip("\\/")) == os.path.normcase(str(b).rstrip("\\/"))


def check_arm_binding(arm: ArmConfig, stdout: str, workspace_root: Path | None) -> ArmHealthResult | None:
    """Fail an otherwise-healthy arm that is serving a different project.

    Liveness is not the same claim as relevance: an arm registered at user
    scope against another project answers every health check truthfully while
    being useless to this workspace. Returns None when the arm is correctly
    bound or the check does not apply.
    """
    if not arm.binding_path or not workspace_root:
        return None

    try:
        payload = json.loads(stdout)
    except Exception:
        return None

    bound_to = [str(v) for v in extract_json_path(payload, arm.binding_path) if isinstance(v, str)]
    if not bound_to:
        return None

    if any(_same_location(p, str(workspace_root)) for p in bound_to):
        return None

    return ArmHealthResult(
        arm.id,
        arm.name,
        "BOUND_ELSEWHERE",
        f"P4 Warning: live but serving {', '.join(bound_to)} — not this workspace ({workspace_root}).",
        {"bound_to": bound_to, "workspace_root": str(workspace_root)},
    )


def first_command_token(command: str) -> str:
    """Extract the executable from a shell command, honouring quotes.

    Splitting on whitespace truncates `"C:\\Program Files\\..."` at the space
    and probes for a binary named `C:\\Program`, which reports OFFLINE with a
    misleading reason. posix=False is deliberate: posix=True strips the
    backslashes out of unquoted Windows paths, turning `C:\\Tools\\unity.exe`
    into `C:Toolsunity.exe`.
    """
    try:
        tokens = shlex.split(command, posix=False)
    except ValueError:  # unbalanced quotes; salvage what we can
        tokens = command.split()

    return tokens[0].strip("\"'") if tokens else ""


def resolve_probe_binary(arm: ArmConfig) -> str:
    """Name the executable a PATH probe should look for.

    An arm's identity fields are not reliably binaries: `mcp_server` is a
    harness registry key and `id` is a label, so resolving either strands
    every MCP arm on a lookup that cannot succeed. When the arm declares a
    shell health_check, that command's first token is the binary actually
    about to run -- probe for that instead.
    """
    hc = (arm.health_check or "").strip()
    if hc and not hc.startswith(("http://", "https://")):
        first_token = first_command_token(hc)
        if first_token:
            return first_token

    return arm.command or arm.mcp_server or arm.id


def probe_cli_arm(arm: ArmConfig, workspace_root: Path | None = None) -> ArmHealthResult:
    cmd_name = resolve_probe_binary(arm)
    executable = shutil.which(cmd_name)

    if not executable:
        return ArmHealthResult(
            arm.id, arm.name, "OFFLINE", f"CLI executable '{cmd_name}' not found in PATH.", {}
        )

    if arm.health_check and not arm.health_check.startswith("http"):
        try:
            res = subprocess.run(
                arm.health_check,
                shell=True,
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res.returncode in (0, 255):
                misbound = check_arm_binding(arm, res.stdout, workspace_root)
                if misbound:
                    return misbound
                return ArmHealthResult(
                    arm.id, arm.name, "READY", f"Health check command '{arm.health_check}' active and responding.", {"stdout": res.stdout[:200]}
                )

            # A health check that ran and failed is a verdict, not a missing
            # verdict. Falling through to "executable found in PATH" would
            # green-light a dead arm on the strength of its binary existing.
            detail = (res.stderr.strip() or res.stdout.strip() or "no output").splitlines()[0][:120]
            return ArmHealthResult(
                arm.id,
                arm.name,
                "OFFLINE",
                f"Health check '{arm.health_check}' failed (exit {res.returncode}): {detail}",
                {"returncode": res.returncode, "stderr": res.stderr[:200]},
            )
        except subprocess.TimeoutExpired:
            return ArmHealthResult(
                arm.id, arm.name, "ASSUMED_READY", f"Executable '{cmd_name}' found at {executable} (health check timed out).", {}
            )
        except Exception as e:
            return ArmHealthResult(
                arm.id, arm.name, "UNCONFIGURED", f"Health check failed: {e}", {}
            )

    return ArmHealthResult(arm.id, arm.name, "READY", f"Executable '{cmd_name}' found in PATH at {executable}.", {})


def probe_http_health(url: str, timeout: int = 2) -> tuple[int | None, str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mcp-cocktail-doctor"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, "Connected"
    except urllib.error.HTTPError as e:
        return e.code, f"HTTP Error {e.code}"
    except Exception as e:
        return None, str(e)


def probe_stdio_mcp_arm(arm: ArmConfig) -> ArmHealthResult:
    """Probe a stdio MCP server directly by spawning the process and sending JSON-RPC initialize."""
    target_cmd = arm.command or arm.mcp_server or arm.id
    executable = shutil.which(target_cmd)

    if not executable:
        return ArmHealthResult(
            arm.id, arm.name, "OFFLINE", f"Stdio MCP server binary '{target_cmd}' not found in PATH.", {}
        )

    try:
        proc = subprocess.Popen(
            [executable],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )

        init_req = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mcp-cocktail-doctor", "version": "1.0"},
            },
        })

        if proc.stdin and proc.stdout:
            proc.stdin.write(init_req + "\n")
            proc.stdin.flush()

            resp_line = proc.stdout.readline()
            if resp_line and "jsonrpc" in resp_line:
                list_req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
                proc.stdin.write(list_req + "\n")
                proc.stdin.flush()

                list_line = proc.stdout.readline()
                tool_count = 0
                if list_line and "tools" in list_line:
                    try:
                        list_data = json.loads(list_line)
                        tool_count = len(list_data.get("result", {}).get("tools", []))
                    except Exception:
                        pass

                proc.terminate()
                tool_msg = f"{tool_count} tools available" if tool_count > 0 else "initialized cleanly"
                return ArmHealthResult(
                    arm.id,
                    arm.name,
                    "READY",
                    f"Stdio MCP server '{target_cmd}' active ({tool_msg}).",
                    {"tools_count": tool_count},
                )

        proc.terminate()
    except Exception:
        pass

    # Fallback when executable exists in PATH but stdio probe requires full launch args
    return ArmHealthResult(
        arm.id, arm.name, "ASSUMED_READY", f"Stdio MCP binary '{target_cmd}' found in PATH at {executable}.", {}
    )


def probe_mcp_arm(arm: ArmConfig, workspace_root: Path | None = None) -> ArmHealthResult:
    hc = (arm.health_check or "").strip()

    # 1. If health_check is an HTTP URL, probe HTTP
    if hc.startswith("http://") or hc.startswith("https://"):
        url = hc
        status_code, msg = probe_http_health(url)

        if status_code is None:
            return ArmHealthResult(
                arm.id, arm.name, "OFFLINE", f"Server unreachable at {url} ({msg}).", {}
            )

        if status_code in (200, 204):
            return ArmHealthResult(
                arm.id, arm.name, "READY", f"MCP server reachable and responding 200 OK at {url}.", {"status": status_code}
            )

        if status_code in (401, 403, 406):
            return ArmHealthResult(
                arm.id,
                arm.name,
                "SOCKET_BOUND_ONLY",
                f"P4 Warning: Listener bound at {url} but returned HTTP {status_code} ({msg}). Session token or Editor registration required.",
                {"status": status_code},
            )

        return ArmHealthResult(
            arm.id, arm.name, "UNCONFIGURED", f"Server returned HTTP {status_code} at {url}.", {"status": status_code}
        )

    # 2. If health_check is a non-HTTP shell command (e.g. "unity status --json"), run command probe!
    if hc:
        return probe_cli_arm(arm, workspace_root)

    # 3. Default Stdio MCP probe
    return probe_stdio_mcp_arm(arm)


def missing_setup_script(arm: ArmConfig, workspace_root: Path | None) -> Path | None:
    """Path of the arm's declared setup script when it is not on disk."""
    if not arm.setup_script:
        return None

    candidate = Path(arm.setup_script)
    if not candidate.is_absolute():
        candidate = (workspace_root or Path.cwd()) / candidate

    return None if candidate.exists() else candidate


def doctor_check_arm(arm: ArmConfig, workspace_root: Path | None = None) -> ArmHealthResult:
    result = probe_mcp_arm(arm, workspace_root) if arm.type == "mcp" else probe_cli_arm(arm, workspace_root)

    # An arm that is down *and* has no way to be brought up is unconfigured,
    # not merely offline. Checked after probing, because a running arm does not
    # care whether its setup script survived.
    if result.status == "OFFLINE":
        absent = missing_setup_script(arm, workspace_root)
        if absent:
            return ArmHealthResult(
                arm.id,
                arm.name,
                "UNCONFIGURED",
                f"{result.message} Setup script '{arm.setup_script}' is missing ({absent}), "
                f"so this arm cannot be started.",
                {**result.details, "missing_setup_script": str(absent)},
            )

    return result


def run_doctor(config: CocktailConfig) -> list[ArmHealthResult]:
    return [doctor_check_arm(arm, config.root_dir) for arm in config.arms]


def print_doctor_report(results: list[ArmHealthResult], config: CocktailConfig) -> None:
    ensure_utf8_streams()

    print(f"\n=== mcp-cocktail Doctor: Arm Health & Diagnostics ===")
    print(f"Domain: {config.name} ({len(results)} arms defined)\n")

    # "0/0 arms READY" reads as a pass. Nothing was checked because nothing is
    # configured, which is a setup failure, not a clean bill of health.
    if not results:
        print("[UNCONFIGURED] No arms defined — nothing was probed.")
        print(f"No manifest resolved under {config.root_dir}.")
        print("Run `mcp-cocktail init` or `mcp-cocktail setup --preset <domain>` first.")
        sys.stdout.flush()
        return

    print(f"{'Arm ID':<18} {'Arm Name':<24} {'Status':<20} {'Diagnostic Summary'}")
    print("-" * 85)

    ready_count = 0
    for r in results:
        if r.status in ("READY", "ASSUMED_READY"):
            ready_count += 1
            status_str = "[READY]" if r.status == "READY" else "[ASSUMED_READY]"
        elif r.status == "SOCKET_BOUND_ONLY":
            status_str = "[BOUND_ONLY (P4)]"
        elif r.status == "BOUND_ELSEWHERE":
            status_str = "[WRONG_PROJECT (P4)]"
        elif r.status == "UNCONFIGURED":
            status_str = "[UNCONFIGURED]"
        else:
            status_str = "[OFFLINE]"

        print(f"{r.arm_id:<18} {r.arm_name:<24} {status_str:<20} {r.message}")

    print(f"\nDoctor Summary: {ready_count}/{len(results)} arms READY / ASSUMED_READY.")
    sys.stdout.flush()
