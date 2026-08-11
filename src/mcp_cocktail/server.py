"""Native MCP Server implementation for mcp-cocktail over stdio JSON-RPC.

Exposes mcp-cocktail tools directly into agent tool palettes:
  - note_friction
  - check_guardrail
  - get_scorecard
  - run_trial
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from mcp_cocktail import __version__
from mcp_cocktail.config import CocktailConfig, TrapsConfig
from mcp_cocktail.guardrail import evaluate_rules, load_state, save_state, get_state_path
from mcp_cocktail.inbox import append_note
from mcp_cocktail.runner import create_trial
from mcp_cocktail.scorecard import generate_scorecard
from mcp_cocktail.weakness import derive_weakest_rule
from mcp_cocktail.console import ensure_utf8_streams


TOOLS_MANIFEST = [
    {
        "name": "note_friction",
        "description": "Log a friction observation, trap, or bug mid-task and auto-derive a Weakness-Maximized guardrail rule.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "observation": {"type": "string", "description": "Verbatim description of the trap or failure"},
                "cost_mins": {"type": "integer", "description": "Estimated minutes lost to this friction"},
            },
            "required": ["observation"],
        },
    },
    {
        "name": "check_guardrail",
        "description": "Evaluate a candidate tool call against active traps.json rules before execution.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_name": {"type": "string", "description": "Target tool name (e.g. Bash, mcp__unity__eval)"},
                "tool_input": {"type": "object", "description": "Tool parameters dictionary"},
            },
            "required": ["tool_name", "tool_input"],
        },
    },
    {
        "name": "get_scorecard",
        "description": "Query the comparative scorecard and performance rankings across all tool arms.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "run_trial",
        "description": "Generate multi-arm trial briefs and task payloads for benchmark execution.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trial_id": {"type": "string", "description": "Trial identifier (e.g. T-001)"},
                "task_description": {"type": "string", "description": "Detailed task requirements for benchmark"},
            },
            "required": ["trial_id", "task_description"],
        },
    },
]


def handle_rpc_request(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mcp-cocktail-server", "version": __version__},
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS_MANIFEST},
        }

    if method == "tools/call":
        params = request.get("params", {})
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if tool_name == "note_friction":
            obs = arguments.get("observation", "")
            cost = arguments.get("cost_mins")
            p = append_note(obs, cost_mins=cost)
            rule = derive_weakest_rule(obs)

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Logged friction to {p}.\nDerived Weakness Rule ID: {rule.id}\nTarget Matcher: {rule.target_matcher}",
                        }
                    ]
                },
            }

        elif tool_name == "check_guardrail":
            t_name = arguments.get("tool_name", "")
            t_input = arguments.get("tool_input", {})
            traps = TrapsConfig.load()
            state = load_state(get_state_path("mcp_server_session"))
            messages = evaluate_rules(t_name, t_input, traps, state)

            text_out = "\n\n".join(messages) if messages else "NO TRAPS DETECTED."
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": text_out}]
                },
            }

        elif tool_name == "get_scorecard":
            config = CocktailConfig.load()
            scorecard = generate_scorecard(config)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": scorecard}]
                },
            }

        elif tool_name == "run_trial":
            trial_id = arguments.get("trial_id", "T-001")
            task_desc = arguments.get("task_description", "")
            config = CocktailConfig.load()
            res = create_trial(trial_id, task_desc, config)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Created trial {trial_id}.\nTask Manifest: {res['tasks_file']}\nBriefs generated: {len(res['briefs'])}",
                        }
                    ]
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Tool '{tool_name}' not found"},
        }

    return None


def run_mcp_server() -> int:
    """Stdio JSON-RPC server loop."""
    ensure_utf8_streams()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_rpc_request(request)
            if response:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except Exception as e:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {str(e)}"},
            }
            sys.stdout.write(json.dumps(err_resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    return 0
