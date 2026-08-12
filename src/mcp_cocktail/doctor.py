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
import socket
import subprocess
import sys
import urllib.parse
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
    if hc and not hc.startswith(("http://", "https://", "ws://", "wss://")):
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
            return "READY", f"WebSocket listener answered the handshake ({first})"

        # A clean close is still the accept loop doing its job.
        return "READY", "WebSocket listener accepted and closed the probe cleanly"

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


def probe_websocket_arm(arm: ArmConfig, url: str) -> ArmHealthResult:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port

    if not port:
        return ArmHealthResult(
            arm.id, arm.name, "UNCONFIGURED",
            f"health_check '{url}' names no port, so there is nothing to probe.", {},
        )

    status, detail = probe_websocket_listener(host, port)
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

    # 0. A ws:// endpoint is not reachable by any HTTP or PATH probe. Several
    #    Unity arms host the session inside the Editor over WebSocket, so
    #    without this branch their only honest setting was "cannot be checked".
    if hc.startswith(("ws://", "wss://")):
        return probe_websocket_arm(arm, hc)

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
                    arm.id, arm.name, "READY",
                    f"Health endpoint {url} answered HTTP {status_code}.",
                    {"status": status_code},
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
    for arm in config.arms:
        if arm.probe != "auto":
            continue
        hc = (arm.health_check or "").strip()
        if hc.startswith(("http://", "https://", "ws://", "wss://")):
            continue
        binary = resolve_probe_binary(arm)
        if binary:
            claims.setdefault(binary, []).append(arm.id)

    return {binary: ids for binary, ids in claims.items() if len(ids) > 1}


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

    labels = {
        "READY": "[READY]",
        "ASSUMED_READY": "[ASSUMED_READY]",
        "NOT_RUNNING": "[NOT_RUNNING]",
        "SOCKET_BOUND_ONLY": "[BOUND_ONLY (P4)]",
        "BOUND_ELSEWHERE": "[WRONG_PROJECT (P4)]",
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

    # Break the rest out by status: "0/11 READY" alone cannot tell an operator
    # whether to start a backend or install a tool.
    breakdown = ", ".join(
        f"{count} {status}" for status, count in tally.most_common() if status not in READY_STATUSES
    )
    summary = f"\nDoctor Summary: {ready_count}/{len(results)} arms READY"
    print(f"{summary} ({breakdown})." if breakdown else f"{summary}.")

    # A collision is invisible per-arm: each row is individually correct and
    # the set is a lie. Report it next to the count it inflates.
    ready_ids = {r.arm_id for r in results if r.status in READY_STATUSES}
    for binary, arm_ids in sorted(shared_probe_binaries(config).items()):
        colliding = [a for a in arm_ids if a in ready_ids]
        if len(colliding) > 1:
            print(f"\n[P4 Warning] {len(colliding)} arms all report READY on the same binary "
                  f"'{binary}': {', '.join(colliding)}.")
            print("Only one program can own that name on PATH, so at most one of these arms is")
            print("really installed -- the others are reporting on someone else's executable.")

    # Say once what the row marker means, rather than on every row that
    # carries it.
    no_route = sum(1 for r in results if NO_ROUTE_MARKER in r.message)
    if no_route:
        print(f"\n{no_route} arm(s) marked ({NO_ROUTE_MARKER}) declare neither a setup_script nor an")
        print("install_hint, so cocktail cannot say how to obtain them. In a survey preset that is")
        print("expected -- they are arms you do not have, not arms that broke. Add an install_hint")
        print("to the manifest for any you intend to use.")

    sys.stdout.flush()
