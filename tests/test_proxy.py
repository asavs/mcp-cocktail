"""Tests for mcp_cocktail.proxy module."""

import json
from unittest.mock import MagicMock
from mcp_cocktail.config import TrapRule, TrapsConfig
from mcp_cocktail.proxy import process_jsonrpc_message


def test_process_jsonrpc_message_intercept():
    traps = TrapsConfig(
        version="1.0",
        domain="test",
        rules=[
            TrapRule(
                id="r1",
                tool_matcher="mcp__.*",
                target_matcher="eval",
                read_only_ignore=False,
                message="TRAP R1 INTERCEPTED",
            )
        ],
    )

    state = {}
    mock_proc = MagicMock()

    # Case 1: Intercepted tool call
    raw_req = json.dumps({
        "jsonrpc": "2.0",
        "id": 100,
        "method": "tools/call",
        "params": {
            "name": "mcp__unity__eval",
            "arguments": {"code": "eval()"},
        },
    })

    resp = process_jsonrpc_message(raw_req, mock_proc, traps, state, "test_proxy_sess")
    assert resp is not None
    data = json.loads(resp)
    assert data["id"] == 100
    assert data["result"]["isError"] is True
    assert "TRAP R1 INTERCEPTED" in data["result"]["content"][0]["text"]

    # Case 2: Safe non-matching tool call passes through (returns None)
    raw_safe = json.dumps({
        "jsonrpc": "2.0",
        "id": 101,
        "method": "tools/call",
        "params": {
            "name": "mcp__unity__get_hierarchy",
            "arguments": {},
        },
    })

    resp_safe = process_jsonrpc_message(raw_safe, mock_proc, traps, state, "test_proxy_sess")
    assert resp_safe is None
