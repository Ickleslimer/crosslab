"""
Tests for CrossLab MCP Server Tools and JSON-RPC Handler.
"""

import json
from crosslab.mcp.server import CrossLabMCPServer


def test_mcp_tool_definitions() -> None:
    server = CrossLabMCPServer()
    tools = server.get_tool_definitions()
    tool_names = [t["name"] for t in tools]

    assert "crosslab_propose_hypothesis" in tool_names
    assert "crosslab_challenge_hypothesis" in tool_names
    assert "crosslab_propose_experiment" in tool_names
    assert "crosslab_record_run" in tool_names
    assert "crosslab_correlate_run" in tool_names
    assert "crosslab_query_investigation" in tool_names
    assert "crosslab_share_patch" in tool_names
    assert "crosslab_wait_for_message" in tool_names
    assert "crosslab_get_run_state" in tool_names


def test_mcp_json_rpc_tools_list() -> None:
    server = CrossLabMCPServer()

    # 1. Initialize
    init_req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}})
    init_resp = json.loads(server.handle_json_rpc(init_req))
    assert init_resp["id"] == 1
    assert init_resp["result"]["protocolVersion"] == "2024-11-05"

    # 2. Notification initialized
    notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert server.handle_json_rpc(notif) is None

    # 3. Ping
    ping_req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    ping_resp = json.loads(server.handle_json_rpc(ping_req))
    assert ping_resp["id"] == 2

    # 4. Tools list
    req = json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    resp_str = server.handle_json_rpc(req)
    resp = json.loads(resp_str)
    assert resp["id"] == 3
    assert "tools" in resp["result"]
    assert len(resp["result"]["tools"]) >= 7


def test_mcp_tool_execution_flow() -> None:
    server = CrossLabMCPServer()

    # 1. Propose hypothesis
    res1 = server.execute_tool(
        "crosslab_propose_hypothesis",
        {
            "title": "Watchdog timeout hypothesis",
            "description": "5000ms silence causes kick",
            "creator": "host-agent",
            "confidence": 0.6,
        },
    )
    assert res1["status"] == "ok"
    hyp_id = res1["hypothesis"]["id"]

    # 2. Propose experiment
    res2 = server.execute_tool(
        "crosslab_propose_experiment",
        {
            "run_id": 14,
            "hypothesis_id": hyp_id,
            "title": "Run 14 experiment",
            "rationale": "Verify packet counts",
            "host_role": "trace recv",
            "client_role": "trace send",
            "creator": "host-agent",
        },
    )
    assert res2["status"] == "ok"

    # 3. Record run
    res3 = server.execute_tool(
        "crosslab_record_run",
        {
            "run_id": 14,
            "hypothesis_id": hyp_id,
            "host": {"last_received_packet": 8831, "reason": "connection_lost"},
            "client": {"last_sent_packet": 8835, "transport_result": "success", "displayed_reason": "kicked_by_host"},
        },
    )
    assert res3["status"] == "ok"

    # 4. Correlate run
    res4 = server.execute_tool("crosslab_correlate_run", {"run_id": 14})
    assert res4["status"] == "ok"
    assert len(res4["correlation"]["discrepancies"]) >= 2

    # 5. Query state
    res5 = server.execute_tool("crosslab_query_investigation", {"query_type": "summary"})
    assert res5["total_hypotheses"] == 1
    assert res5["total_runs"] == 1
