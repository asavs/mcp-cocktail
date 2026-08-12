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
    assert "plan_trial" in tool_names


def test_plan_trial_tool_is_explicit_that_nothing_was_executed(tmp_path, monkeypatch):
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".agents" / "manifest.json").write_text(
        '{"name":"t","description":"","arms":[{"id":"a","name":"A","type":"cli"}]}',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    request = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "plan_trial",
            "arguments": {"trial_id": "T-MCP", "task_description": "task"},
        },
    }

    response = handle_rpc_request(request)

    text = response["result"]["content"][0]["text"]
    assert "Planned trial" in text
    assert "no agents or tools were executed" in text


def test_plan_trial_tool_returns_structured_error_for_unsafe_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    request = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "plan_trial",
            "arguments": {"trial_id": "../escape", "task_description": "task"},
        },
    }

    response = handle_rpc_request(request)

    assert response["error"]["code"] == -32001
    assert "Invalid trial ID" in response["error"]["message"]
    assert not (tmp_path / "docs").exists()


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
