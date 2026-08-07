"""Inline MCP Proxy and Router for mcp-cocktail.

Acts as a transparent stdio JSON-RPC proxy between an MCP client and a target MCP server.
Evaluates traps.json rules in-flight, intercepts dangerous tool calls before they hit the
downstream server, and logs telemetry invisibly without requiring harness hooks.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from mcp_cocktail.config import TrapsConfig
from mcp_cocktail.guardrail import evaluate_rules, load_state, save_state, get_state_path


def process_jsonrpc_message(
    raw_line: str,
    target_proc: subprocess.Popen[str],
    traps: TrapsConfig,
    state: dict[str, float],
    session_id: str,
) -> str | None:
    """Process incoming JSON-RPC request line from client.

    Returns response string if intercepted/handled locally, or None if forwarded.
    """
    try:
        msg = json.loads(raw_line)
    except Exception:
        return None

    if not isinstance(msg, dict):
        return None

    method = msg.get("method")
    req_id = msg.get("id")

    # Intercept tool calls
    if method == "tools/call":
        params = msg.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        now = time.time()
        fired_messages = evaluate_rules(tool_name, arguments, traps, state, now)

        if fired_messages:
            save_state(get_state_path(session_id), state)
            warning_text = "INTERCEPTED BY MCP-COCKTAIL PROXY:\n\n" + "\n\n".join(fired_messages)

            # Return local JSON-RPC result indicating blocked/shielded call
            local_resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": warning_text,
                        }
                    ],
                    "isError": True,
                },
            }
            return json.dumps(local_resp, ensure_ascii=False)

    return None


def run_proxy(target_cmd: list[str]) -> int:
    """Run transparent stdio proxy wrapping a target MCP server command."""
    if not target_cmd:
        sys.stderr.write("Error: No target command specified for proxy.\n")
        return 1

    # Ensure UTF-8 streams
    for stream in (sys.stdout, sys.stdin, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore
        except (AttributeError, OSError):
            pass

    traps = TrapsConfig.load()
    session_id = "proxy_session"
    state_file = get_state_path(session_id)
    state = load_state(state_file)

    try:
        # Spawn target downstream MCP server process
        proc = subprocess.Popen(
            target_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
    except Exception as e:
        sys.stderr.write(f"Failed to spawn target MCP server '{target_cmd}': {e}\n")
        return 1

    # Main stdio loop reading requests from parent client
    try:
        for line in sys.stdin:
            line_str = line.strip()
            if not line_str:
                continue

            intercepted_resp = process_jsonrpc_message(line_str, proc, traps, state, session_id)

            if intercepted_resp:
                sys.stdout.write(intercepted_resp + "\n")
                sys.stdout.flush()
            else:
                # Forward request straight to target downstream server
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.write(line_str + "\n")
                    proc.stdin.flush()

                # Read response from target server stdout
                if proc.stdout and not proc.stdout.closed:
                    resp_line = proc.stdout.readline()
                    if resp_line:
                        sys.stdout.write(resp_line)
                        sys.stdout.flush()

    except (KeyboardInterrupt, BrokenPipeError):
        pass
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()

    return 0
