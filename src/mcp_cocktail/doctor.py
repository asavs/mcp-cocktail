"""Arm health verification and diagnostic engine for mcp-cocktail.

Probes HTTP URLs, shell commands, and stdio MCP servers directly by speaking the JSON-RPC
MCP protocol, verifying initialize responses and available tool counts honestly.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_cocktail.config import CocktailConfig, ArmConfig


@dataclass
class ArmHealthResult:
    arm_id: str
    arm_name: str
    status: str  # "READY", "ASSUMED_READY", "SOCKET_BOUND_ONLY", "UNCONFIGURED", "OFFLINE"
    message: str
    details: dict[str, Any]


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
        first_token = hc.split()[0].strip("\"'")
        if first_token:
            return first_token

    return arm.command or arm.mcp_server or arm.id


def probe_cli_arm(arm: ArmConfig) -> ArmHealthResult:
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


def probe_mcp_arm(arm: ArmConfig) -> ArmHealthResult:
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
        return probe_cli_arm(arm)

    # 3. Default Stdio MCP probe
    return probe_stdio_mcp_arm(arm)


def doctor_check_arm(arm: ArmConfig) -> ArmHealthResult:
    if arm.type == "cli":
        return probe_cli_arm(arm)
    elif arm.type == "mcp":
        return probe_mcp_arm(arm)
    else:
        return probe_cli_arm(arm)


def run_doctor(config: CocktailConfig) -> list[ArmHealthResult]:
    results = []
    for arm in config.arms:
        res = doctor_check_arm(arm)
        results.append(res)
    return results


def print_doctor_report(results: list[ArmHealthResult], config: CocktailConfig) -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore
        except (AttributeError, OSError):
            pass

    print(f"\n=== mcp-cocktail Doctor: Arm Health & Diagnostics ===")
    print(f"Domain: {config.name} ({len(results)} arms defined)\n")

    print(f"{'Arm ID':<18} {'Arm Name':<24} {'Status':<20} {'Diagnostic Summary'}")
    print("-" * 85)

    ready_count = 0
    for r in results:
        if r.status in ("READY", "ASSUMED_READY"):
            ready_count += 1
            status_str = "[READY]" if r.status == "READY" else "[ASSUMED_READY]"
        elif r.status == "SOCKET_BOUND_ONLY":
            status_str = "[BOUND_ONLY (P4)]"
        elif r.status == "UNCONFIGURED":
            status_str = "[UNCONFIGURED]"
        else:
            status_str = "[OFFLINE]"

        print(f"{r.arm_id:<18} {r.arm_name:<24} {status_str:<20} {r.message}")

    print(f"\nDoctor Summary: {ready_count}/{len(results)} arms READY / ASSUMED_READY.")
    sys.stdout.flush()
