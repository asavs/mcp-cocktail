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
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_cocktail.config import CocktailConfig, ArmConfig
from mcp_cocktail.console import ensure_utf8_streams


@dataclass
class ArmHealthResult:
    arm_id: str
    arm_name: str
    # "READY", "ASSUMED_READY", "NOT_RUNNING", "SOCKET_BOUND_ONLY",
    # "BOUND_ELSEWHERE", "UNCONFIGURED", "OFFLINE"
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


MAX_REPORTED_FIELDS = 6


def binding_instances(arm: ArmConfig, stdout: str) -> tuple[str, list[dict[str, Any]]]:
    """Split an arm's binding_path into (leaf key, the objects carrying it).

    `data.instances[].project` names a leaf; its parent is the instance object
    the health check is describing. Reading the parent gives every fact the
    tool already reports about itself -- port, pid, version -- without the code
    having to know any of those names.
    """
    if not arm.binding_path:
        return "", []

    try:
        payload = json.loads(stdout)
    except Exception:
        return "", []

    if "." in arm.binding_path:
        parent, leaf = arm.binding_path.rsplit(".", 1)
        containers = extract_json_path(payload, parent)
    else:
        leaf = arm.binding_path
        containers = [payload]

    return leaf, [c for c in containers if isinstance(c, dict)]


def describe_instance(instance: dict[str, Any], skip_key: str) -> str:
    """Render an instance's scalar facts, e.g. `port=7800, pid=1416`."""
    fields = []
    for key, value in instance.items():
        if key == skip_key or value is None or isinstance(value, (dict, list, bool)):
            continue
        fields.append(f"{key}={str(value)[:40]}")
        if len(fields) >= MAX_REPORTED_FIELDS:
            break

    return ", ".join(fields)


def describe_binding(arm: ArmConfig, stdout: str, workspace_root: Path | None) -> str:
    """One-line account of what a correctly-bound arm is actually serving.

    Surfaces the live values the manifest would otherwise have to hardcode --
    notably the port, which Unity reassigns between Editor sessions.
    """
    leaf, instances = binding_instances(arm, stdout)
    if not leaf or not workspace_root:
        return ""

    for instance in instances:
        served = instance.get(leaf)
        if isinstance(served, str) and _same_location(served, str(workspace_root)):
            facts = describe_instance(instance, leaf)
            return f"serving {served}" + (f" ({facts})" if facts else "")

    return ""


def check_arm_binding(arm: ArmConfig, stdout: str, workspace_root: Path | None) -> ArmHealthResult | None:
    """Fail an otherwise-healthy arm that is serving a different project.

    Liveness is not the same claim as relevance: an arm registered at user
    scope against another project answers every health check truthfully while
    being useless to this workspace. Returns None when the arm is correctly
    bound or the check does not apply.
    """
    if not arm.binding_path or not workspace_root:
        return None

    leaf, instances = binding_instances(arm, stdout)
    bound_to = [str(i[leaf]) for i in instances if isinstance(i.get(leaf), str)]
    if not bound_to:
        return None

    if any(_same_location(p, str(workspace_root)) for p in bound_to):
        return None

    detail = "; ".join(
        f"{i[leaf]}" + (f" ({facts})" if (facts := describe_instance(i, leaf)) else "")
        for i in instances
        if isinstance(i.get(leaf), str)
    )

    return ArmHealthResult(
        arm.id,
        arm.name,
        "BOUND_ELSEWHERE",
        f"P4 Warning: live but serving {detail} — not this workspace ({workspace_root}).",
        {"bound_to": bound_to, "workspace_root": str(workspace_root)},
    )


def summarize_failure(stdout: str, stderr: str) -> str:
    """Best available one-line reason a health check failed.

    Taking the first line of stdout blindly yields "{" for the many CLIs that
    emit a pretty-printed JSON envelope, discarding the actionable message
    inside it -- `unity status --json` explains exactly what to do, on a line
    the naive reader never reaches.
    """
    if stderr.strip():
        return stderr.strip().splitlines()[0][:160]

    try:
        payload = json.loads(stdout)
    except Exception:
        payload = None

    if isinstance(payload, dict):
        messages: list[str] = []
        errors = payload.get("errors")
        if isinstance(errors, list):
            for item in errors:
                if isinstance(item, dict) and item.get("message"):
                    messages.append(str(item["message"]))
                elif isinstance(item, str):
                    messages.append(item)

        for key in ("error", "message", "detail"):
            value = payload.get(key)
            if not messages and isinstance(value, str) and value.strip():
                messages.append(value.strip())

        if messages:
            return " ".join(messages)[:160]

    for line in stdout.splitlines():
        if line.strip() not in ("", "{", "}", "[", "]"):
            return line.strip()[:160]

    return "no output"


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
    shell_check = arm.health_check if (arm.health_check and not arm.health_check.startswith("http")) else ""

    # shutil.which() answers about *this* process's PATH. The health check runs
    # in a child shell resolving against its own, and the two disagree in
    # ordinary setups: shims and wrapper scripts, .cmd/.bat shadowing on
    # Windows, a login profile that extends PATH for the shell only, or a PATH
    # edited after this process started. When they disagree, the precheck's
    # verdict is about the wrong process -- it reported OFFLINE for arms whose
    # health check runs perfectly well one line later. A declared health check
    # is the authority on whether its own command runs, so run it and report
    # what happened. The precheck only decides for arms that never gave us one.
    if not executable and not shell_check:
        return ArmHealthResult(
            arm.id, arm.name, "OFFLINE", f"CLI executable '{cmd_name}' not found in PATH.", {}
        )

    if shell_check:
        try:
            res = subprocess.run(
                shell_check,
                shell=True,
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res.returncode in (0, 255):
                misbound = check_arm_binding(arm, res.stdout, workspace_root)
                if misbound:
                    return misbound

                serving = describe_binding(arm, res.stdout, workspace_root)
                summary = f"Health check command '{shell_check}' active and responding."
                if serving:
                    summary = f"Health check command '{shell_check}' active — {serving}."

                return ArmHealthResult(
                    arm.id, arm.name, "READY", summary, {"stdout": res.stdout[:200], "serving": serving}
                )

            # A health check that ran and failed is a verdict, not a missing
            # verdict. Falling through to "executable found in PATH" would
            # green-light a dead arm on the strength of its binary existing.
            #
            # NOT_RUNNING rather than OFFLINE: the tool is installed and
            # answered, and told us its backend is down. That is a different
            # instruction to the operator -- start the backend, or fall back
            # to this CLI -- than "this tool does not exist here".
            detail = summarize_failure(res.stdout, res.stderr)

            # Both resolvers agreeing the binary is absent is the only case
            # where "this tool does not exist here" is the honest verdict.
            if not executable:
                return ArmHealthResult(
                    arm.id,
                    arm.name,
                    "OFFLINE",
                    f"CLI executable '{cmd_name}' not found in PATH, and health check "
                    f"'{shell_check}' failed (exit {res.returncode}): {detail}",
                    {"returncode": res.returncode, "stderr": res.stderr[:200]},
                )

            return ArmHealthResult(
                arm.id,
                arm.name,
                "NOT_RUNNING",
                f"Health check '{shell_check}' failed (exit {res.returncode}): {detail}",
                {"returncode": res.returncode, "stderr": res.stderr[:200]},
            )
        except subprocess.TimeoutExpired:
            # A command that hung is a command that ran, whatever this
            # process's PATH says about it.
            located = f"found at {executable}" if executable else "resolved by the child shell"
            return ArmHealthResult(
                arm.id, arm.name, "ASSUMED_READY", f"Executable '{cmd_name}' {located} (health check timed out).", {}
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


def speaks_mcp_over_http(url: str, timeout: int = 2) -> tuple[bool, str]:
    """POST a JSON-RPC `initialize` and check for a JSON-RPC reply.

    HTTP 200 proves only that something answered. Accepting that as READY
    would make the tool built to detect P4 green lights emit one: a plain web
    server on the right port reports a healthy MCP arm.
    """
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mcp-cocktail-doctor", "version": "1.0"},
        },
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "mcp-cocktail-doctor",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read(4096).decode("utf-8", errors="replace")
        except Exception:
            return False, f"HTTP {e.code} to initialize"
    except Exception as e:
        return False, f"initialize failed ({e})"

    if "jsonrpc" in body:
        return True, "JSON-RPC initialize acknowledged"

    return False, "no JSON-RPC response to initialize"


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
                # "advertised", not "available": a catalogue is not a
                # capability. The Unity MCP advertises ~140 tools with no
                # Editor running, and every one of them then blocks 60s.
                tool_msg = (
                    f"initialized cleanly, {tool_count} tools advertised"
                    if tool_count > 0
                    else "initialized cleanly"
                )
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

        # Something is listening. What it answers to a *GET* settles nothing:
        # MCP's Streamable HTTP transport carries every request over POST, and
        # a spec-compliant server rejects a GET that does not ask for an event
        # stream -- 405 and 406 are the signature of a correct server, not a
        # broken one. Reading them as a verdict made cocktail report
        # BOUND_ONLY (P4) for healthy arms with a live session attached, which
        # is the false negative twin of the false positive this branch exists
        # to prevent. Ask the question the transport actually asks.
        is_mcp, detail = speaks_mcp_over_http(url)
        if is_mcp:
            return ArmHealthResult(
                arm.id, arm.name, "READY",
                f"MCP server reachable at {url} and {detail} (GET returned {status_code}).",
                {"status": status_code, "handshake": detail},
            )

        if status_code in (401, 403):
            return ArmHealthResult(
                arm.id,
                arm.name,
                "SOCKET_BOUND_ONLY",
                f"P4 Warning: Listener bound at {url} but rejected the handshake with HTTP "
                f"{status_code} ({msg}). Session token or Editor registration required.",
                {"status": status_code, "handshake": detail},
            )

        if status_code in (200, 204, 405, 406):
            return ArmHealthResult(
                arm.id,
                arm.name,
                "SOCKET_BOUND_ONLY",
                f"P4 Warning: {url} answers HTTP {status_code} but did not complete an MCP "
                f"handshake ({detail}). Something is listening on that port; it is not a "
                f"usable MCP session.",
                {"status": status_code, "handshake": detail},
            )

        return ArmHealthResult(
            arm.id, arm.name, "UNCONFIGURED",
            f"Server returned HTTP {status_code} at {url} and did not complete an MCP handshake ({detail}).",
            {"status": status_code, "handshake": detail},
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


READY_STATUSES = ("READY", "ASSUMED_READY")


def evaluate_requirements(
    results: list[ArmHealthResult], required: list[str]
) -> tuple[list[ArmHealthResult], list[str]]:
    """Check the arms a caller declared it depends on. Returns (unmet, unknown).

    Deliberately opt-in. A manifest is a survey of competing arms -- the Unity
    preset lists eleven and nobody has all eleven -- so failing because "some
    arm is down" would fail permanently for every real user, and a check that
    always fails gets tuned out. Callers name what they actually need.
    """
    by_id = {r.arm_id: r for r in results}

    unknown = [arm_id for arm_id in required if arm_id not in by_id]
    unmet = [
        by_id[arm_id]
        for arm_id in required
        if arm_id in by_id and by_id[arm_id].status not in READY_STATUSES
    ]

    return unmet, unknown


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

    labels = {
        "READY": "[READY]",
        "ASSUMED_READY": "[ASSUMED_READY]",
        "NOT_RUNNING": "[NOT_RUNNING]",
        "SOCKET_BOUND_ONLY": "[BOUND_ONLY (P4)]",
        "BOUND_ELSEWHERE": "[WRONG_PROJECT (P4)]",
        "UNCONFIGURED": "[UNCONFIGURED]",
        "OFFLINE": "[OFFLINE]",
    }

    tally: Counter[str] = Counter()
    for r in results:
        tally[r.status] += 1
        print(f"{r.arm_id:<18} {r.arm_name:<24} {labels.get(r.status, '[OFFLINE]'):<20} {r.message}")

    ready_count = sum(tally[s] for s in READY_STATUSES)

    # Break the rest out by status: "0/11 READY" alone cannot tell an operator
    # whether to start a backend or install a tool.
    breakdown = ", ".join(
        f"{count} {status}" for status, count in tally.most_common() if status not in READY_STATUSES
    )
    summary = f"\nDoctor Summary: {ready_count}/{len(results)} arms READY"
    print(f"{summary} ({breakdown})." if breakdown else f"{summary}.")

    sys.stdout.flush()
