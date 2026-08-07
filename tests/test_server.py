"""Tests for mcp_cocktail.server module."""

from mcp_cocktail.server import handle_rpc_request


def test_handle_rpc_request():
    init_req = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    resp = handle_rpc_request(init_req)
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "mcp-cocktail-server"

    list_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    resp2 = handle_rpc_request(list_req)
    assert resp2["id"] == 2
    tools = resp2["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "note_friction" in tool_names
    assert "check_guardrail" in tool_names
    assert "get_scorecard" in tool_names
    assert "run_trial" in tool_names


def test_handle_rpc_tool_call():
    call_req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "check_guardrail",
            "arguments": {"tool_name": "Bash", "tool_input": {"command": "git diff"}},
        },
    }
    resp = handle_rpc_request(call_req)
    assert resp["id"] == 3
    assert "content" in resp["result"]
