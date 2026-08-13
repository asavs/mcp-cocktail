"""Arm health verification and diagnostic engine for mcp-cocktail.

Probes HTTP URLs, shell commands, and stdio MCP servers directly by speaking the JSON-RPC
MCP protocol, verifying initialize responses and available tool counts honestly.
"""

from __future__ import annotations

import glob
import json
import os
import queue
import re
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_cocktail.config import CocktailConfig, ArmConfig
from mcp_cocktail.console import ensure_utf8_streams
from mcp_cocktail.evidence import append_operational_observation, latest_operational_observation


@dataclass
class ArmHealthResult:
    arm_id: str
    arm_name: str
    # "READY", "ASSUMED_READY", "INSTALLED_ONLY", "NOT_RUNNING", "SOCKET_BOUND_ONLY",
    # "BOUND_ELSEWHERE", "EXTERNAL_CHECK_REQUIRED", "UNCONFIGURED", "OFFLINE"
    status: str
    message: str
    details: dict[str, Any]


OBSERVATION_FAILURE_TTL_SECONDS = 300
OBSERVATION_CLOCK_SKEW_SECONDS = 5


def record_health_observation(
    workspace_root: Path,
    result: ArmHealthResult,
    *,
    source: str = "doctor",
    capability: str = "basic",
    observed_at: float | None = None,
) -> None:
    """Atomically persist an arm observation for doctor and future runners.

    Execution adapters can call this with ``source="execution"`` after a real
    operation. Doctor intentionally does not erase that stronger evidence with
    a shallower transport-only result.
    """
    previous = latest_operational_observation(workspace_root, result.arm_id, capability)
    shallow = result.status in {
        "TRANSPORT_ONLY", "TARGET_ONLY", "SOCKET_BOUND_ONLY", "INSTALLED_ONLY", "AMBIGUOUS_IDENTITY"
    }
    if source == "doctor" and shallow and previous and previous.get("operation") != "doctor":
        return
    outcome = (
        "succeeded" if result.status in {"READY", "OPERATIONAL", "TRANSPORT_ONLY"}
        else "timed_out" if result.details.get("timeout") else "failed"
    )
    append_operational_observation(workspace_root, {
        "arm": result.arm_id,
        "capability": capability,
        "layer": "target_operation" if result.status in {"READY", "OPERATIONAL", "DEGRADED"} else "transport",
        "operation": "doctor" if source == "doctor" else source,
        "outcome": outcome,
        "observed_at": datetime.fromtimestamp(
            observed_at if observed_at is not None else time.time(), timezone.utc
        ).isoformat().replace("+00:00", "Z"),
        "classification": result.status,
        "detail": result.message,
        "project_identity": str(workspace_root),
    })


def apply_recent_health_observation(
    result: ArmHealthResult,
    workspace_root: Path,
    *,
    now: float | None = None,
) -> ArmHealthResult:
    """Let a recent real failure override a shallow successful handshake."""
    # A later transport handshake must not erase a target failure. Recovery is
    # established only by a newer target-operation observation.
    observation = latest_operational_observation(
        workspace_root, result.arm_id, layer="target_operation",
        project_identity=str(workspace_root),
        not_after=(now if now is not None else time.time()) + OBSERVATION_CLOCK_SKEW_SECONDS,
    )
    if not isinstance(observation, dict) or observation.get("operation") == "doctor":
        return result
    stamp = observation.get("observed_at", 0)
    try:
        observed = (
            float(stamp) if isinstance(stamp, (int, float)) else
            datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
        )
    except (TypeError, ValueError):
        observed = 0
    age = (now if now is not None else time.time()) - observed
    failed = observation.get("outcome") in {"failed", "timed_out", "cancelled"}
    shallow = result.status in {
        "TRANSPORT_ONLY", "TARGET_ONLY", "SOCKET_BOUND_ONLY", "INSTALLED_ONLY", "AMBIGUOUS_IDENTITY"
    }
    if not failed or not shallow or age > OBSERVATION_FAILURE_TTL_SECONDS:
        return result
    return ArmHealthResult(
        result.arm_id,
        result.arm_name,
        "DEGRADED",
        f"Transport responds, but a target operation failed {max(0, int(age))}s ago: "
        f"{observation.get('detail', 'operation failed')}",
        {**result.details, "transport_status": result.status, "recent_observation": observation},
    )


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
    if hc and not hc.startswith(("http://", "https://", "ws://", "wss://")):
        first_token = first_command_token(hc)
        if first_token:
            return first_token

    return arm.command or arm.mcp_server or arm.id


VERSION_ONLY_FLAGS = {"--version", "-v", "-V", "--v", "-version", "version"}


def proves_installation_only(health_check: str) -> bool:
    """Whether a health check can only establish that the binary exists.

    `uloop --version` answering says a program is installed. It says nothing
    about whether the editor-side package it drives is present -- and the field
    report caught exactly that: READY on the version flag, then the first real
    call failed because the Unity package had never been added. A version probe
    is evidence of installation and must not be dressed up as capability.
    """
    if not health_check:
        return False

    try:
        tokens = [t.strip("\"'") for t in shlex.split(health_check, posix=False)]
    except ValueError:
        tokens = health_check.split()

    return len(tokens) == 2 and tokens[1].lower() in VERSION_ONLY_FLAGS


def run_capability_check(arm: ArmConfig) -> ArmHealthResult | None:
    """Run the arm's proof-of-work command. None when it declares none."""
    if not arm.capability_check:
        return None

    try:
        res = subprocess.run(
            arm.capability_check, shell=True, capture_output=True, text=True, timeout=20
        )
    except subprocess.TimeoutExpired:
        return ArmHealthResult(
            arm.id, arm.name, "NOT_RUNNING",
            f"Capability check '{arm.capability_check}' timed out; the arm is installed but not answering.",
            {},
        )
    except Exception as e:
        return ArmHealthResult(arm.id, arm.name, "NOT_RUNNING", f"Capability check failed: {e}", {})

    if res.returncode != 0:
        return ArmHealthResult(
            arm.id, arm.name, "NOT_RUNNING",
            f"Installed, but capability check '{arm.capability_check}' failed "
            f"(exit {res.returncode}): {summarize_failure(res.stdout, res.stderr)}",
            {"returncode": res.returncode},
        )

    return ArmHealthResult(
        arm.id, arm.name, "OPERATIONAL",
        f"Capability check '{arm.capability_check}' succeeded — this arm can do real work.",
        {"capability": True},
    )


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

                # An arm that says how to prove itself gets held to that.
                proven = run_capability_check(arm)
                if proven:
                    return proven

                # Otherwise, do not promote a version flag into a capability
                # claim. INSTALLED_ONLY sits outside READY_STATUSES on purpose:
                # the headline count is the number the field report caught
                # lying, and a binary existing is not an arm that works.
                if proves_installation_only(shell_check) and not serving:
                    return ArmHealthResult(
                        arm.id, arm.name, "INSTALLED_ONLY",
                        f"'{shell_check}' answered, so the binary is installed — but nothing here "
                        f"proves this arm can act on the target. Declare a capability_check to "
                        f"settle it.",
                        {"stdout": res.stdout[:200]},
                    )

                status = "OPERATIONAL" if arm.health_check_layer == "target_operation" else "TRANSPORT_ONLY"
                if status == "TRANSPORT_ONLY":
                    summary += " The manifest does not declare this check as a target operation."
                return ArmHealthResult(
                    arm.id, arm.name, status, summary,
                    {"stdout": res.stdout[:200], "serving": serving, "layer": arm.health_check_layer},
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
                arm.id, arm.name, "DEGRADED",
                f"Executable '{cmd_name}' {located}, but its health check timed out; no target operation was proven.",
                {"timeout": True},
            )
        except Exception as e:
            return ArmHealthResult(
                arm.id, arm.name, "UNCONFIGURED", f"Health check failed: {e}", {}
            )

    return ArmHealthResult(
        arm.id, arm.name, "INSTALLED_ONLY",
        f"Executable '{cmd_name}' found in PATH at {executable}, but no target health check is declared.",
        {"executable": executable},
    )


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


def _decode_jsonrpc_body(body: str, expected_id: Any = None) -> dict[str, Any] | None:
    """Decode ordinary JSON or the matching response event in an SSE body.

    MCP servers may emit progress/log notifications before the response.  A
    notification proves neither completion nor success, so callers supplying a
    request id must ignore every JSON-RPC object with a different or absent id.
    """
    candidates = [body]
    candidates.extend(
        line[5:].strip() for line in body.splitlines() if line.startswith("data:")
    )
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        if (
            isinstance(value, dict)
            and value.get("jsonrpc") == "2.0"
            and (expected_id is None or value.get("id") == expected_id)
        ):
            return value
    return None


def _post_mcp_jsonrpc(
    url: str,
    payload: dict[str, Any],
    timeout: float,
    session_id: str | None = None,
) -> tuple[dict[str, Any] | None, str | None, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "mcp-cocktail-doctor",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST", headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(65536).decode("utf-8", errors="replace")
            returned_session = response.headers.get("Mcp-Session-Id") or session_id
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(4096).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return None, session_id, f"HTTP {exc.code}: {body[:160] or exc.reason}"
    except Exception as exc:
        return None, session_id, str(exc)
    decoded = _decode_jsonrpc_body(body, payload.get("id"))
    if decoded is None:
        return None, returned_session, "no JSON-RPC response"
    return decoded, returned_session, ""


def probe_mcp_target(
    url: str, spec: dict[str, Any], workspace_root: Path | None = None
) -> tuple[bool, str, dict[str, Any]]:
    """Run a configured, bounded, read-only MCP operation through the target."""
    if spec.get("kind") != "mcp_tool" or not isinstance(spec.get("name"), str):
        return False, "target_check must declare kind=mcp_tool and a tool name", {}
    try:
        timeout = min(20.0, max(0.25, float(spec.get("timeout_seconds", 5))))
    except (TypeError, ValueError):
        timeout = 5.0
    deadline = time.monotonic() + timeout

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError(f"target_check exceeded its {timeout:g}s total deadline")
        return value
    initialize = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "mcp-cocktail-doctor", "version": "1.0"},
        },
    }
    try:
        init, session_id, error = _post_mcp_jsonrpc(url, initialize, remaining())
    except TimeoutError as exc:
        return False, str(exc), {"timeout": True}
    if init is None or "error" in init:
        return False, f"initialize failed: {error or init.get('error')}", {}

    # Streamable HTTP servers may allocate a session during initialize. The
    # subsequent call must carry that opaque id. Sending initialized is not
    # required by every implementation, but is required by MCP's lifecycle;
    # its empty 202 response is intentionally not parsed as JSON-RPC.
    notification = {
        "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}
    }
    try:
        request = urllib.request.Request(
            url, data=json.dumps(notification).encode("utf-8"), method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "User-Agent": "mcp-cocktail-doctor",
                **({"Mcp-Session-Id": session_id} if session_id else {}),
            },
        )
        with urllib.request.urlopen(request, timeout=remaining()):
            pass
    except urllib.error.HTTPError as exc:
        if exc.code not in (200, 202, 204):
            return False, f"initialized notification failed: HTTP {exc.code}", {}
    except Exception as exc:
        return False, f"initialized notification failed: {exc}", {}

    identity_resource = spec.get("identity_resource")
    if identity_resource:
        if workspace_root is None:
            return False, "target identity cannot be verified without a workspace root", {}
        identity_call = {
            "jsonrpc": "2.0", "id": 2, "method": "resources/read",
            "params": {"uri": identity_resource},
        }
        try:
            identity_reply, _, error = _post_mcp_jsonrpc(
                url, identity_call, remaining(), session_id
            )
        except TimeoutError as exc:
            return False, str(exc), {"timeout": True}
        if identity_reply is None or "result" not in identity_reply:
            return False, f"target identity resource failed: {error or identity_reply}", {}
        def project_roots(value: Any) -> list[str]:
            roots: list[str] = []
            if isinstance(value, dict):
                for key, child in value.items():
                    if key.casefold() in {"projectroot", "project_root"} and isinstance(child, str):
                        roots.append(child)
                    else:
                        roots.extend(project_roots(child))
            elif isinstance(value, list):
                for child in value:
                    roots.extend(project_roots(child))
            elif isinstance(value, str):
                try:
                    decoded = json.loads(value)
                except (TypeError, ValueError):
                    return roots
                roots.extend(project_roots(decoded))
            return roots

        expected_identity = os.path.normcase(os.path.normpath(str(workspace_root.resolve())))
        observed_roots = {
            os.path.normcase(os.path.normpath(root))
            for root in project_roots(identity_reply["result"])
        }
        if expected_identity not in observed_roots:
            return False, (
                f"target identity resource did not name this workspace ({workspace_root})"
            ), {"identity_resource": identity_resource, "project_roots": sorted(observed_roots)}

    call = {
        "jsonrpc": "2.0", "id": 3 if identity_resource else 2, "method": "tools/call",
        "params": {"name": spec["name"], "arguments": spec.get("arguments") or {}},
    }
    try:
        reply, _, error = _post_mcp_jsonrpc(url, call, remaining(), session_id)
    except TimeoutError as exc:
        return False, str(exc), {"timeout": True}
    if reply is None:
        return False, f"target tool '{spec['name']}' failed: {error}", {}
    if "error" in reply:
        return False, f"target tool '{spec['name']}' returned {reply['error']}", {"reply": reply}
    if "result" not in reply:
        return False, f"target tool '{spec['name']}' returned no result", {"reply": reply}
    result = reply.get("result")
    if isinstance(result, dict) and result.get("isError") is True:
        return False, f"target tool '{spec['name']}' reported an error", {"reply": reply}
    reject_match = spec.get("reject_match")
    if isinstance(reject_match, str) and reject_match:
        rendered = json.dumps(result, ensure_ascii=False)
        try:
            rejected = re.search(reject_match, rendered, re.I) is not None
        except re.error as exc:
            return False, f"target_check reject_match is invalid: {exc}", {"reply": reply}
        if rejected:
            return False, (
                f"target tool '{spec['name']}' returned a configured failure signal"
            ), {"reply": reply, "reject_match": reject_match}
    return True, f"target tool '{spec['name']}' completed", {"reply": reply, "session": bool(session_id)}


LIVENESS_PATH = "/__mcp_liveness__"


def probe_websocket_listener(host: str, port: int, timeout: float = 2.0) -> tuple[str, str]:
    """Liveness of a WebSocket listener, without opening a real session.

    Modelled on mcp-unity's own probe (McpUnityServer.cs). Two details are
    load-bearing and neither is guessable:

    A completed TCP connect is *not* proof of health. The documented Windows
    failure mode binds the port and accepts connections, then never answers --
    the Editor reports healthy while every client hangs forever. Connect-only
    checking reports a green light for exactly that state, which is the P4
    shape this tool exists to catch. So we write a handshake and require an
    answer, treating a held-open silent socket as bound-but-unusable.

    The request deliberately targets a bogus path rather than the real service
    path: a healthy server rejects it with 501 and closes, which proves the
    accept loop is alive without registering a client session in the Editor UI.
    Probing the real path would make the diagnostic show up as a connected
    client, changing what it measures.
    """
    request = (
        f"GET {LIVENESS_PATH} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Key: bWNwLWNvY2t0YWlsLXByb2Jl\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    ).encode("ascii")

    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(request)
            try:
                data = sock.recv(256)
            except socket.timeout:
                return "SOCKET_BOUND_ONLY", (
                    "accepted the connection then never answered the handshake -- the known "
                    "hung-listener state; restarting the server does not clear it, restarting "
                    "the Editor does"
                )

        if data:
            first = data.split(b"\r\n", 1)[0].decode("ascii", errors="replace")

            # A WebSocket-aware server answers an upgrade request with 101 when
            # it accepts, or a 4xx/5xx refusal when it will not -- never a plain
            # 200, which means an ordinary web server is serving the path and
            # ignoring the Upgrade header entirely. Reporting that READY would
            # green-light a squatter on the arm's port, the same mistake as
            # treating HTTP 200 as proof of MCP.
            if first.split(" ")[1:2] == ["200"]:
                return "SOCKET_BOUND_ONLY", (
                    f"answered a WebSocket upgrade with plain HTTP 200 ({first}) -- something is "
                    "listening on that port, but it is not a WebSocket endpoint"
                )

            return "TRANSPORT_ONLY", f"WebSocket listener answered the handshake ({first})"

        # A clean close is still the accept loop doing its job.
        return "TRANSPORT_ONLY", "WebSocket listener accepted and closed the probe cleanly"

    except ConnectionRefusedError:
        return "NOT_RUNNING", "nothing is listening on that port"
    except (socket.timeout, TimeoutError):
        # Not OFFLINE, and not the same as refused. Whether a closed loopback
        # port refuses or silently drops is platform- and firewall-dependent --
        # this box times out where Linux refuses -- so classifying the two
        # differently would make the verdict a property of the machine. Both
        # mean nothing usable is there, and for an Editor-hosted listener the
        # operator's next move is identical: open the project and start it.
        return "NOT_RUNNING", "nothing answered the connection attempt (not started, or a firewall dropped it)"
    except OSError as e:
        return "OFFLINE", f"connection failed ({e})"


STATUS_FIELD_PORT = "ws_port"
STATUS_FIELD_PROJECT = "project_path"
STATUS_FIELD_HEARTBEAT = "last_heartbeat"
STATUS_FIELD_RELOADING = "reloading"


def read_status_files(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Live Editor instances advertised by on-disk status files.

    Editors that move their port publish where they landed. Reading that is
    the difference between checking the arm and checking a port number the
    manifest happened to guess -- with two Editors open, the second lands on
    the next free port and a fixed probe reports healthy for the wrong
    project, or dead for a project that is running fine.

    Files are filtered on heartbeat age, matching what the vendor's own client
    does: the writer refreshes every few seconds, so a stale file is a crashed
    Editor rather than a live one.
    """
    pattern = os.path.expanduser(str(spec.get("status_glob", "")))
    if not pattern:
        return []

    max_age = float(spec.get("max_age_seconds", 30))
    now = datetime.now(timezone.utc)
    live: list[dict[str, Any]] = []

    for path in sorted(glob.glob(pattern)):
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            continue  # a half-written or foreign file is not an error

        if not isinstance(payload, dict) or not payload.get(STATUS_FIELD_PORT):
            continue

        stamp = payload.get(STATUS_FIELD_HEARTBEAT)
        if isinstance(stamp, str):
            try:
                beat = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                if beat.tzinfo is None:
                    beat = beat.replace(tzinfo=timezone.utc)
                if (now - beat).total_seconds() > max_age:
                    continue
            except ValueError:
                pass  # unparseable stamp: keep it, the probe still decides

        live.append(payload)

    return live


def resolve_discovered_target(
    arm: ArmConfig, workspace_root: Path | None
) -> tuple[dict[str, Any] | None, ArmHealthResult | None]:
    """Pick the advertised instance serving this workspace.

    Returns (instance, early_result). The directory is shared ecosystem-wide,
    so a file found there is not automatically this workspace's -- an instance
    serving another project is BOUND_ELSEWHERE, the same claim the CLI arms
    already make, reached by a different route.
    """
    instances = read_status_files(arm.discovery)
    if not instances:
        return None, ArmHealthResult(
            arm.id, arm.name, "NOT_RUNNING",
            "No Editor is publishing a status file, so nothing is serving this arm.",
            {"discovery": arm.discovery.get("status_glob", "")},
        )

    if workspace_root:
        for inst in instances:
            served = inst.get(STATUS_FIELD_PROJECT)
            if isinstance(served, str) and _same_location(served, str(workspace_root)):
                return inst, None

        detail = "; ".join(
            str(i.get(STATUS_FIELD_PROJECT)) for i in instances if i.get(STATUS_FIELD_PROJECT)
        )
        return None, ArmHealthResult(
            arm.id, arm.name, "BOUND_ELSEWHERE",
            f"P4 Warning: live but serving {detail} — not this workspace ({workspace_root}).",
            {"bound_to": detail, "workspace_root": str(workspace_root)},
        )

    return instances[0], None


def probe_websocket_arm(arm: ArmConfig, url: str, workspace_root: Path | None = None) -> ArmHealthResult:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    serving = ""

    if arm.discovery:
        instance, early = resolve_discovered_target(arm, workspace_root)
        if early:
            return early
        if instance:
            port = int(instance[STATUS_FIELD_PORT])
            serving = f" serving {instance.get(STATUS_FIELD_PROJECT, '')}".rstrip()

            # A domain reload takes the socket down for a few seconds by
            # design. Reporting that as a failure would train the operator to
            # ignore this row.
            if instance.get(STATUS_FIELD_RELOADING):
                return ArmHealthResult(
                    arm.id, arm.name, "TRANSPORT_ONLY",
                    f"{host}:{port} is mid domain-reload; the socket is legitimately down briefly.",
                    {"host": host, "port": port, "reloading": True},
                )

    if not port:
        return ArmHealthResult(
            arm.id, arm.name, "UNCONFIGURED",
            f"health_check '{url}' names no port, so there is nothing to probe.", {},
        )

    status, detail = probe_websocket_listener(host, port)
    detail = f"{detail}{serving}"
    prefix = "P4 Warning: " if status == "SOCKET_BOUND_ONLY" else ""

    return ArmHealthResult(
        arm.id, arm.name, status,
        f"{prefix}{host}:{port} {detail}.",
        {"host": host, "port": port},
    )


def probe_stdio_mcp_arm(arm: ArmConfig) -> ArmHealthResult:
    """Probe a stdio MCP server directly by spawning the process and sending JSON-RPC initialize."""
    target_cmd = arm.command or arm.mcp_server or arm.id
    executable = shutil.which(target_cmd)

    if not executable:
        return ArmHealthResult(
            arm.id, arm.name, "OFFLINE", f"Stdio MCP server binary '{target_cmd}' not found in PATH.", {}
        )

    proc: subprocess.Popen[str] | None = None

    def bounded_readline(stream: Any, timeout: float) -> str:
        result: queue.Queue[str] = queue.Queue(maxsize=1)
        threading.Thread(
            target=lambda: result.put(stream.readline()), daemon=True
        ).start()
        try:
            return result.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError("stdio MCP response timed out") from exc

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

            resp_line = bounded_readline(proc.stdout, 3.0)
            if resp_line and "jsonrpc" in resp_line:
                list_req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
                proc.stdin.write(list_req + "\n")
                proc.stdin.flush()

                list_line = bounded_readline(proc.stdout, 3.0)
                tool_count = 0
                if list_line and "tools" in list_line:
                    try:
                        list_data = json.loads(list_line)
                        tool_count = len(list_data.get("result", {}).get("tools", []))
                    except Exception:
                        pass

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
                    "TRANSPORT_ONLY",
                    f"Stdio MCP server '{target_cmd}' active ({tool_msg}).",
                    {"tools_count": tool_count},
                )

    except TimeoutError:
        return ArmHealthResult(
            arm.id, arm.name, "DEGRADED",
            f"Stdio MCP binary '{target_cmd}' started but did not answer within 3s.",
            {"timeout": True},
        )
    except Exception:
        pass
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1)

    # Fallback when executable exists in PATH but stdio probe requires full launch args
    return ArmHealthResult(
        arm.id, arm.name, "INSTALLED_ONLY", f"Stdio MCP binary '{target_cmd}' found in PATH at {executable}; no live target operation was proven.", {}
    )


def probe_mcp_arm(arm: ArmConfig, workspace_root: Path | None = None) -> ArmHealthResult:
    hc = (arm.health_check or "").strip()

    # 0. A ws:// endpoint is not reachable by any HTTP or PATH probe. Several
    #    Unity arms host the session inside the Editor over WebSocket, so
    #    without this branch their only honest setting was "cannot be checked".
    if hc.startswith(("ws://", "wss://")):
        return probe_websocket_arm(arm, hc, workspace_root)

    # 1. If health_check is an HTTP URL, probe HTTP
    if hc.startswith("http://") or hc.startswith("https://"):
        url = hc
        status_code, msg = probe_http_health(url)

        if status_code is None:
            return ArmHealthResult(
                arm.id, arm.name, "OFFLINE", f"Server unreachable at {url} ({msg}).", {}
            )

        # Not every URL worth checking is an MCP endpoint. Some arms expose a
        # plain liveness ping on the Unity side -- that endpoint answering is
        # exactly the "is this wired up" signal we want, and demanding a
        # JSON-RPC handshake of it would report a healthy service as a P4
        # warning. The arm says which kind it is; we do not guess from the URL.
        if arm.probe == "http":
            if status_code in (200, 204):
                return ArmHealthResult(
                    arm.id, arm.name, "TARGET_ONLY",
                    f"Health endpoint {url} answered HTTP {status_code}; this proves target-side liveness, not a complete operation through the arm.",
                    {"status": status_code, "evidence": "target-health-endpoint", "delivery": "unverified"},
                )
            return ArmHealthResult(
                arm.id, arm.name, "NOT_RUNNING",
                f"Health endpoint {url} answered HTTP {status_code} ({msg}).",
                {"status": status_code},
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
            if arm.target_check:
                operational, target_detail, target_evidence = probe_mcp_target(
                    url, arm.target_check, workspace_root
                )
                if operational:
                    return ArmHealthResult(
                        arm.id, arm.name, "OPERATIONAL",
                        f"MCP transport and target are responsive: {target_detail}.",
                        {"status": status_code, "handshake": detail, **target_evidence},
                    )
                if target_evidence.get("project_roots"):
                    return ArmHealthResult(
                        arm.id, arm.name, "WRONG_PROJECT",
                        f"MCP transport at {url} belongs to another Unity project: "
                        f"{', '.join(target_evidence['project_roots'])}. Refusing to treat the "
                        "fixed port as this workspace's arm.",
                        {"status": status_code, "handshake": detail, **target_evidence},
                    )
                return ArmHealthResult(
                    arm.id, arm.name, "DEGRADED",
                    f"MCP transport responds at {url}, but the target probe failed: {target_detail}.",
                    {"status": status_code, "handshake": detail, **target_evidence},
                )
            return ArmHealthResult(
                arm.id, arm.name, "TRANSPORT_ONLY",
                f"MCP server reachable at {url} and {detail} (GET returned {status_code}); "
                "no target_check is declared, so Editor responsiveness is unproven.",
                {"status": status_code, "handshake": detail, "evidence": "transport"},
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
        result = probe_cli_arm(arm, workspace_root)
        if result.status in READY_STATUSES:
            return ArmHealthResult(
                arm.id, arm.name, "TARGET_ONLY",
                f"{result.message} This verifies the shared target/backend path, not this "
                "arm's MCP delivery route; an MCP round-trip is still required.",
                {**result.details, "target_status": result.status, "delivery": "unverified"},
            )
        return result

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


NO_ROUTE_MARKER = "no install route declared"


def acquisition_note(arm: ArmConfig) -> str:
    """What an operator can do about an arm that is not installed.

    A preset manifest is a survey of competing arms and nobody has all of
    them, so most OFFLINE lines in a real run are arms the reader was never
    expected to have. Reported as a bare OFFLINE they are indistinguishable
    from a broken install, which makes the whole report look like a wall of
    failures and trains the reader to skim past the one line that matters.

    Deliberately terse. Spelling the explanation out per arm put the same
    three lines of prose on eight rows of a real report -- restating the
    wall of noise it was written to remove. The rows carry a marker; the
    summary explains it once.
    """
    if arm.install_hint:
        return f"Install: {arm.install_hint}"

    docs = arm.install.get("docs_url")
    if docs:
        return f"Install: see {docs} (`mcp-cocktail install {arm.id}` for steps)"

    if not arm.setup_script:
        return f"({NO_ROUTE_MARKER})"

    return ""


def append_note(message: str, note: str) -> str:
    """Join a probe message to its acquisition note without fusing sentences.

    Probe messages are frequently truncated mid-clause by summarize_failure,
    so they end on a comma as often as a full stop.
    """
    if not note:
        return message
    if not message.strip():
        return note

    return f"{message.rstrip().rstrip(',;.')}. {note}"


def doctor_check_arm(arm: ArmConfig, workspace_root: Path | None = None) -> ArmHealthResult:
    # GUI automation lives in the agent harness, not at an endpoint Cocktail
    # can interrogate. Calling it UNCONFIGURED implies a broken installation;
    # calling it READY from a binary/socket would confuse harness availability
    # with proof that the visible target application can complete an action.
    if arm.type.lower() == "gui" and arm.probe == "none":
        reason = f" {arm.probe_reason}" if arm.probe_reason else ""
        return ArmHealthResult(
            arm.id,
            arm.name,
            "EXTERNAL_CHECK_REQUIRED",
            append_note(
                "Not probed: GUI-arm availability must be established by the executing "
                f"agent harness, then target responsiveness must be verified by a visible operation.{reason}",
                acquisition_note(arm),
            ),
            {"probe": arm.probe, "availability": "external-harness"},
        )

    # Probing an arm we cannot honestly probe manufactures a precise-sounding
    # failure about an endpoint that was never real: "unreachable at
    # 127.0.0.1:9500" reads as a server that is down, not as an entry nobody
    # could substantiate. Say which one it is.
    if arm.probe in ("none", "unverified"):
        preamble = (
            "Not probed: this arm's entry could not be tied to a real upstream project, "
            "so any endpoint recorded for it is unverified."
            if arm.probe == "unverified"
            else "Not probed: no automatable health check exists for this arm."
        )
        reason = f" {arm.probe_reason}" if arm.probe_reason else ""
        return ArmHealthResult(
            arm.id,
            arm.name,
            "UNCONFIGURED",
            append_note(f"{preamble}{reason}", acquisition_note(arm)),
            {"probe": arm.probe},
        )

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
                append_note(
                    f"{result.message} Setup script '{arm.setup_script}' is missing ({absent}), "
                    f"so this arm cannot be started.",
                    acquisition_note(arm),
                ),
                {**result.details, "missing_setup_script": str(absent)},
            )

        return ArmHealthResult(
            arm.id,
            arm.name,
            result.status,
            append_note(result.message, acquisition_note(arm)),
            result.details,
        )

    return result


def shared_probe_binaries(config: CocktailConfig) -> dict[str, list[str]]:
    """Probe binaries that more than one arm claims, keyed by binary name.

    Three separate Unity CLI projects each install an executable named
    `unity-cli`. Only one of them can win a PATH lookup, but all three arms
    probe `unity-cli --version`, so whichever is installed answers for all of
    them and every one reports READY. That is a P4 green light manufactured by
    the manifest itself -- a rich surface implying three capabilities where at
    most one exists -- and no per-arm check can see it, because the collision
    is a property of the set.
    """
    claims: dict[str, list[str]] = {}
    groups: dict[str, set[str | None]] = {}

    for arm in config.arms:
        if arm.probe != "auto":
            continue
        hc = (arm.health_check or "").strip()
        if hc.startswith(("http://", "https://", "ws://", "wss://")):
            continue
        binary = resolve_probe_binary(arm)
        if binary:
            claims.setdefault(binary, []).append(arm.id)
            groups.setdefault(binary, set()).add(arm.binary_group)

    # Sharing a binary is only a collision between *different products*. The
    # official CLI and the official MCP are one install reached two ways, and
    # warning that "at most one of these is really installed" about them was
    # simply false -- reported from the field as a wrong claim, which costs
    # more trust than the real collision it was built to catch.
    return {
        binary: ids
        for binary, ids in claims.items()
        if len(ids) > 1 and not (len(groups[binary]) == 1 and None not in groups[binary])
    }


def run_doctor(config: CocktailConfig) -> list[ArmHealthResult]:
    results: list[ArmHealthResult] = []
    for arm in config.arms:
        result = doctor_check_arm(arm, config.root_dir)
        result = apply_recent_health_observation(result, config.root_dir)
        results.append(result)
    return mark_ambiguous_identities(results, config)


def capability_health_results(
    config: CocktailConfig,
    base_results: list[ArmHealthResult],
    capability: str,
    *,
    now: float | None = None,
    freshness_seconds: int = OBSERVATION_FAILURE_TTL_SECONDS,
) -> list[ArmHealthResult]:
    """Derive capability-scoped status from fresh target-operation evidence."""
    current = now if now is not None else time.time()
    base = {result.arm_id: result for result in base_results}
    currently_reachable = {"READY", "OPERATIONAL", "TRANSPORT_ONLY", "TARGET_ONLY"}
    derived: list[ArmHealthResult] = []
    for arm in config.arms:
        if capability not in arm.capabilities:
            continue
        observation = latest_operational_observation(
            config.root_dir, arm.id, capability, layer="target_operation",
            project_identity=str(config.root_dir),
            not_after=current + OBSERVATION_CLOCK_SKEW_SECONDS,
        )
        base_result = base.get(arm.id)
        if base_result is None or base_result.status not in currently_reachable:
            base_status = base_result.status if base_result else "UNKNOWN"
            derived.append(ArmHealthResult(
                arm.id, arm.name, base_status if base_result else "CAPABILITY_UNKNOWN",
                f"Capability '{capability}' cannot be operational while current arm health "
                f"is {base_status}.",
                {"capability": capability, "base_status": base_status, "observation": observation},
            ))
            continue
        # A target check is a live, project-bound operation performed by this
        # very doctor invocation.  Let the manifest state exactly which
        # capabilities that operation proves; do not infer every declared
        # capability merely because one target call answered.  This keeps the
        # capability gate useful without turning `read_console` into evidence
        # that, for example, an arm can run EditMode tests.
        live_probe_capabilities = arm.target_check.get("proves_capabilities", [])
        if isinstance(live_probe_capabilities, str):
            live_probe_capabilities = [live_probe_capabilities]
        if base_result.status == "OPERATIONAL" and capability in live_probe_capabilities:
            derived.append(ArmHealthResult(
                arm.id, arm.name, "OPERATIONAL",
                f"Capability '{capability}' is proven by the current live target probe.",
                {
                    "capability": capability,
                    "base_status": base_result.status,
                    "proof": "current_live_target_probe",
                    "probe": base_result.details,
                },
            ))
            continue
        if not observation:
            derived.append(ArmHealthResult(
                arm.id, arm.name, "CAPABILITY_UNKNOWN",
                f"No target-operation evidence exists for capability '{capability}'.",
                {"capability": capability, "base_status": base.get(arm.id).status if arm.id in base else None},
            ))
            continue
        stamp = observation.get("observed_at")
        try:
            observed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            observed = 0.0
        raw_age = int(current - observed)
        age = max(0, raw_age)
        fresh = -OBSERVATION_CLOCK_SKEW_SECONDS <= raw_age <= freshness_seconds
        outcome = observation.get("outcome")
        independently_probed = (
            observation.get("operation") == "doctor"
            and observation.get("classification") == "OPERATIONAL"
        )
        if outcome == "succeeded" and fresh:
            status = "OPERATIONAL" if independently_probed else "EXECUTION_REPORTED"
            proof = "independently probed" if independently_probed else "reported by an execution adapter"
            message = f"Capability '{capability}' succeeded against this project {age}s ago ({proof})."
        elif outcome in {"failed", "timed_out", "cancelled"} and fresh:
            status = "DEGRADED"
            message = f"Capability '{capability}' {outcome.replace('_', ' ')} {age}s ago: {observation.get('detail') or 'no detail'}"
        else:
            status = "CAPABILITY_UNKNOWN"
            reason = "from the future" if raw_age < -OBSERVATION_CLOCK_SKEW_SECONDS else "stale"
            message = f"Capability '{capability}' evidence is {reason} ({age}s old)."
        derived.append(ArmHealthResult(
            arm.id, arm.name, status, message,
            {"capability": capability, "age_seconds": age, "observation": observation},
        ))
    return derived


READY_STATUSES = ("READY", "OPERATIONAL")

# Statuses asserting the binary answered something. A collision is about which
# program owns a name on PATH, so it is just as real between three arms that
# each got INSTALLED_ONLY as between three that got READY -- demoting them out
# of the headline must not also silence the warning about them.
RESPONDING_STATUSES = READY_STATUSES + ("TRANSPORT_ONLY", "INSTALLED_ONLY")


def mark_ambiguous_identities(
    results: list[ArmHealthResult], config: CocktailConfig
) -> list[ArmHealthResult]:
    """Demote arms whose shared PATH name cannot identify their product."""
    collisions = shared_probe_binaries(config)
    ambiguous: set[str] = set()
    binaries: dict[str, str] = {}
    for binary, arm_ids in collisions.items():
        responding = [
            result for result in results
            if result.arm_id in arm_ids and result.status in RESPONDING_STATUSES
        ]
        if len(responding) > 1:
            ambiguous.update(result.arm_id for result in responding)
            binaries.update({result.arm_id: binary for result in responding})

    return [
        ArmHealthResult(
            result.arm_id, result.arm_name, "AMBIGUOUS_IDENTITY",
            f"'{binaries[result.arm_id]}' answered, but multiple arm definitions claim that "
            "PATH name; use an absolute executable path or identity check to disambiguate.",
            {**result.details, "previous_status": result.status, "binary": binaries[result.arm_id]},
        )
        if result.arm_id in ambiguous else result
        for result in results
    ]


def evaluate_requirements(
    results: list[ArmHealthResult], required: list[str]
) -> tuple[list[ArmHealthResult], list[str]]:
    """Check the arms a caller declared it depends on. Returns (unmet, unknown).

    Deliberately opt-in. A manifest is a survey of competing arms -- the Unity
    preset lists twelve and nobody has all twelve -- so failing because "some
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

    # Stamp the build into the report. A tester pasting output should not have
    # to be asked which version produced it, and "are you on the latest?" is
    # unanswerable without it.
    from mcp_cocktail import __version__

    print(f"\n=== mcp-cocktail {__version__} Doctor: Arm Health & Diagnostics ===")
    print(f"Domain: {config.name} ({len(results)} arms defined)\n")

    # "0/0 arms READY" reads as a pass. Nothing was checked because nothing is
    # configured, which is a setup failure, not a clean bill of health.
    if not results:
        print("[UNCONFIGURED] No arms defined — nothing was probed.")
        print(f"No manifest resolved under {config.root_dir}.")
        print("Run `mcp-cocktail init` or `mcp-cocktail setup --preset <domain>` first.")
        sys.stdout.flush()
        return

    labels = {
        "READY": "[READY]",
        "OPERATIONAL": "[OPERATIONAL]",
        "TRANSPORT_ONLY": "[TRANSPORT ONLY]",
        "TARGET_ONLY": "[DELIVERY UNVERIFIED]",
        "DEGRADED": "[DEGRADED]",
        "AMBIGUOUS_IDENTITY": "[AMBIGUOUS IDENTITY]",
        "CAPABILITY_UNKNOWN": "[CAPABILITY UNKNOWN]",
        "EXECUTION_REPORTED": "[EXECUTION REPORTED]",
        "ASSUMED_READY": "[LEGACY ASSUMED]",
        "NOT_RUNNING": "[NOT_RUNNING]",
        "INSTALLED_ONLY": "[INSTALLED?]",
        "SOCKET_BOUND_ONLY": "[BOUND_ONLY (P4)]",
        "BOUND_ELSEWHERE": "[WRONG_PROJECT (P4)]",
        "WRONG_PROJECT": "[WRONG_PROJECT (P4)]",
        "EXTERNAL_CHECK_REQUIRED": "[EXTERNAL CHECK]",
        "UNCONFIGURED": "[UNCONFIGURED]",
        "OFFLINE": "[OFFLINE]",
    }

    # Fixed widths truncated nothing and aligned nothing: real arm names run
    # to 43 characters, so every long row pushed the status and diagnostic
    # columns out of register and the table stopped being scannable.
    id_w = max(len("Arm ID"), *(len(r.arm_id) for r in results))
    name_w = max(len("Arm Name"), *(len(r.arm_name) for r in results))
    status_w = max(len(v) for v in labels.values())

    print(f"{'Arm ID':<{id_w}}  {'Arm Name':<{name_w}}  {'Status':<{status_w}}  Diagnostic Summary")
    print("-" * (id_w + name_w + status_w + 24))

    tally: Counter[str] = Counter()
    for r in results:
        tally[r.status] += 1
        label = labels.get(r.status, "[OFFLINE]")
        print(f"{r.arm_id:<{id_w}}  {r.arm_name:<{name_w}}  {label:<{status_w}}  {r.message}")

    ready_count = sum(tally[s] for s in READY_STATUSES)

    # The headline must not count arms the report is about to disown. Three
    # arms answering the same `unity-cli --version` produced three READYs and
    # a warning saying at most one of them is real -- the number and the prose
    # contradicting each other in the same screen. At most one member of a
    # collision group can be the installed program, so the group contributes
    # one, and the difference is stated rather than quietly absorbed.
    ready_ids = {r.arm_id for r in results if r.status in READY_STATUSES}
    responding_ids = {r.arm_id for r in results if r.status in RESPONDING_STATUSES}
    collisions = shared_probe_binaries(config)
    unverifiable = 0
    for arm_ids in collisions.values():
        colliding_ready = [a for a in arm_ids if a in ready_ids]
        if len(colliding_ready) > 1:
            unverifiable += len(colliding_ready) - 1

    confirmed_count = ready_count - unverifiable

    # Break the rest out by status: "0/11 READY" alone cannot tell an operator
    # whether to start a backend or install a tool.
    breakdown = ", ".join(
        f"{count} {status}" for status, count in tally.most_common() if status not in READY_STATUSES
    )
    summary = f"\nDoctor Summary: {confirmed_count}/{len(results)} arms READY"
    if unverifiable:
        summary += f", +{unverifiable} indistinguishable"
    print(f"{summary} ({breakdown})." if breakdown else f"{summary}.")

    # A collision is invisible per-arm: each row is individually correct and
    # the set is a lie. Report it next to the count it no longer inflates.
    for binary, arm_ids in sorted(collisions.items()):
        colliding = [a for a in arm_ids if a in responding_ids]
        if len(colliding) > 1:
            print(f"\n[P4 Warning] {len(colliding)} arms all answered on the same binary "
                  f"'{binary}': {', '.join(colliding)}.")
            print("Only one program can own that name on PATH, so at most one of these arms is")
            print("really installed -- the others are reporting on someone else's executable.")

            # The answer was already in hand and being thrown away: which()
            # returns the path, and the install location names the winner far
            # more reliably than any version string can. `go/bin` is the Go
            # arm, an npm prefix is the npm one. Print it and the ambiguity is
            # resolvable by eye instead of by experiment.
            resolved = shutil.which(binary)
            if resolved:
                print(f"That name currently resolves to: {resolved}")
                print("Point the other arms at their own absolute paths in .agents/manifest.json")
                print("to tell them apart, or ignore the ones you did not install.")

    # Say once what the row marker means, rather than on every row that
    # carries it.
    no_route = sum(1 for r in results if NO_ROUTE_MARKER in r.message)
    if no_route:
        print(f"\n{no_route} arm(s) marked ({NO_ROUTE_MARKER}) declare neither a setup_script nor an")
        print("install_hint, so cocktail cannot say how to obtain them. In a survey preset that is")
        print("expected -- they are arms you do not have, not arms that broke. Add an install_hint")
        print("to the manifest for any you intend to use.")

    sys.stdout.flush()
