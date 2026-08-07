"""Arm health verification and diagnostic engine for mcp-cocktail."""

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
    status: str  # "READY", "SOCKET_BOUND_ONLY", "UNCONFIGURED", "OFFLINE"
    message: str
    details: dict[str, Any]


def probe_cli_arm(arm: ArmConfig) -> ArmHealthResult:
    if not arm.command:
        return ArmHealthResult(
            arm.id, arm.name, "UNCONFIGURED", "No CLI command specified in manifest.", {}
        )

    executable = shutil.which(arm.command)
    if not executable:
        return ArmHealthResult(
            arm.id, arm.name, "OFFLINE", f"Executable '{arm.command}' not found in PATH.", {}
        )

    if arm.health_check:
        try:
            res = subprocess.run(
                arm.health_check,
                shell=True,
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res.returncode in (0, 255) and res.stdout.strip():
                return ArmHealthResult(
                    arm.id, arm.name, "READY", f"CLI '{arm.command}' active and responding.", {"stdout": res.stdout[:200]}
                )
        except subprocess.TimeoutExpired:
            return ArmHealthResult(
                arm.id, arm.name, "READY", f"Executable '{arm.command}' found in PATH at {executable} (health check timed out).", {}
            )
        except Exception as e:
            return ArmHealthResult(
                arm.id, arm.name, "UNCONFIGURED", f"Health check failed: {e}", {}
            )

    return ArmHealthResult(arm.id, arm.name, "READY", f"Executable '{arm.command}' found in PATH at {executable}.", {})


def probe_http_health(url: str, timeout: int = 2) -> tuple[int | None, str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mcp-cocktail-doctor"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, "Connected"
    except urllib.error.HTTPError as e:
        return e.code, f"HTTP Error {e.code}"
    except Exception as e:
        return None, str(e)


def probe_mcp_arm(arm: ArmConfig) -> ArmHealthResult:
    hc = arm.health_check or ""
    url_match = re.search(r"https?://[^\s'\"]+", hc)

    if not url_match:
        return ArmHealthResult(
            arm.id, arm.name, "UNCONFIGURED", "No valid HTTP health check URL found for MCP arm.", {}
        )

    url = url_match.group(0)
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
            f"P4 Warning: Listener bound at {url} but returned HTTP {status_code} ({msg}). Editor/Server session not fully registered.",
            {"status": status_code},
        )

    return ArmHealthResult(
        arm.id, arm.name, "UNCONFIGURED", f"Server returned HTTP {status_code} at {url}.", {"status": status_code}
    )


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
        if r.status == "READY":
            ready_count += 1
            status_str = "[READY]"
        elif r.status == "SOCKET_BOUND_ONLY":
            status_str = "[BOUND_ONLY (P4)]"
        elif r.status == "UNCONFIGURED":
            status_str = "[UNCONFIGURED]"
        else:
            status_str = "[OFFLINE]"

        print(f"{r.arm_id:<18} {r.arm_name:<24} {status_str:<20} {r.message}")

    print(f"\nDoctor Summary: {ready_count}/{len(results)} arms READY.")
    sys.stdout.flush()
