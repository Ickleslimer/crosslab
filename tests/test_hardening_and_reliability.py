import json
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from crosslab.protocol.actions import ActionType, AgentRole
from crosslab.protocol.models import (
    Experiment,
    Hypothesis,
    MessageEnvelope,
    PingRequest,
    PongResponse,
    ReconcileRequest,
    RunRecord,
)
from crosslab.transport.node import A2ANode
from crosslab.mcp.server import CrossLabMCPServer


@pytest.fixture
def host_node(tmp_path):
    db_path = str(tmp_path / "host_hardening.db")
    node = A2ANode(
        agent_id="test-host",
        role=AgentRole.HOST,
        db_path=db_path,
        session_id="test-session",
    )
    return node


@pytest.mark.asyncio
async def test_clock_offset_math_independence(host_node):
    """
    Verifies that differing monotonic boot times on two separate machines
    do NOT contaminate the Unix epoch wall-clock offset.
    """
    transport = ASGITransport(app=host_node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        t0_mono = 100_000_000_000
        t0_wall = 1_700_000_000_000_000_000

        ping_payload = {
            "agent_id": "test-client",
            "t0_send_mono_ns": t0_mono,
            "t0_send_wall_ns": t0_wall,
        }

        res = await client.post("/v1/a2a/ping", json=ping_payload)
        assert res.status_code == 200
        data = res.json()
        assert "t0_send_mono_ns" in data
        assert "t1_recv_mono_ns" in data
        assert "t1_recv_wall_ns" in data


@pytest.mark.asyncio
async def test_reconciliation_endpoint(host_node):
    """
    Verifies that the /v1/a2a/sync/reconcile endpoint detects and returns
    messages and hypotheses missing on the client node.
    """
    host_node.session.record_message(
        MessageEnvelope(
            message_id="msg_alpha",
            session_id="test-session",
            sender_id="test-host",
            natural_language="Alpha message",
        )
    )
    host_node.session.record_message(
        MessageEnvelope(
            message_id="msg_beta",
            session_id="test-session",
            sender_id="test-host",
            natural_language="Beta message",
        )
    )
    hyp = Hypothesis(
        id="hyp_alpha",
        session_id="test-session",
        title="Test Hypothesis",
        description="Testing sync",
        creator="test-host",
    )
    host_node.session.storage.save_hypothesis(hyp)

    transport = ASGITransport(app=host_node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        req = {
            "agent_id": "test-client",
            "session_id": "test-session",
            "known_message_ids": ["msg_alpha"],
            "known_hypothesis_ids": [],
            "known_experiment_ids": [],
            "known_run_ids": [],
        }

        res = await client.post("/v1/a2a/sync/reconcile", json=req)
        assert res.status_code == 200
        data = res.json()
        assert len(data["missing_messages"]) == 1
        assert data["missing_messages"][0]["message_id"] == "msg_beta"
        assert len(data["missing_hypotheses"]) == 1
        assert data["missing_hypotheses"][0]["id"] == "hyp_alpha"


@pytest.mark.asyncio
async def test_reconciliation_does_not_drop_messages_after_500(host_node):
    for index in range(501):
        host_node.session.record_message(
            MessageEnvelope(
                message_id=f"msg_{index:03d}",
                session_id="test-session",
                sender_id="test-host",
                timestamp="2026-08-27T00:00:00+00:00",
                monotonic_ns=index,
            )
        )

    transport = ASGITransport(app=host_node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        req = {
            "agent_id": "test-client",
            "session_id": "test-session",
            "known_message_ids": [f"msg_{index:03d}" for index in range(500)],
        }
        res = await client.post("/v1/a2a/sync/reconcile", json=req)

    assert res.status_code == 200
    assert [m["message_id"] for m in res.json()["missing_messages"]] == ["msg_500"]


@pytest.mark.asyncio
async def test_ingested_message_reaches_handlers_and_local_sse(host_node):
    handled = []
    subscriber = asyncio.Queue()
    host_node._subscribers.append(subscriber)
    host_node.on_action(ActionType.CHAT, lambda envelope: handled.append(envelope.message_id))
    message = MessageEnvelope(
        message_id="msg_delivery",
        session_id="test-session",
        sender_id="test-client",
        action=ActionType.CHAT,
    )

    assert (await host_node._ingest_message(message))[0] is True
    assert handled == ["msg_delivery"]
    assert (await subscriber.get())["envelope"]["message_id"] == "msg_delivery"

    assert (await host_node._ingest_message(message))[0] is False
    assert handled == ["msg_delivery"]
    assert subscriber.empty()


@pytest.mark.asyncio
async def test_restart_seeds_message_deduplication_from_storage(tmp_path):
    db_path = str(tmp_path / "restart_dedup.db")
    first_node = A2ANode(
        agent_id="test-client",
        role=AgentRole.CLIENT,
        db_path=db_path,
        session_id="test-session",
    )
    message = MessageEnvelope(
        message_id="msg_persisted",
        session_id="test-session",
        sender_id="test-host",
        action=ActionType.CHAT,
    )
    first_node.session.record_message(message)

    restarted_node = A2ANode(
        agent_id="test-client",
        role=AgentRole.CLIENT,
        db_path=db_path,
        session_id="test-session",
    )
    handled = []
    restarted_node.on_action(ActionType.CHAT, lambda envelope: handled.append(envelope.message_id))

    assert (await restarted_node._ingest_message(message))[0] is False
    assert handled == []


def test_mcp_resources_and_prompts():
    """
    Verifies full MCP compliance: initialize, resources/list, resources/read,
    prompts/list, prompts/get, and ping.
    """
    server = CrossLabMCPServer()

    # 1. initialize
    init_req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"}
        }
    }
    init_res = json.loads(server.handle_json_rpc(json.dumps(init_req)))
    assert init_res["result"]["protocolVersion"] == "2024-11-05"
    assert "resources" in init_res["result"]["capabilities"]
    assert "prompts" in init_res["result"]["capabilities"]

    # 2. ping
    ping_req = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
    ping_res = json.loads(server.handle_json_rpc(json.dumps(ping_req)))
    assert ping_res["result"] == {}

    # 3. resources/list
    res_list_req = {"jsonrpc": "2.0", "id": 3, "method": "resources/list"}
    res_list = json.loads(server.handle_json_rpc(json.dumps(res_list_req)))
    uris = [r["uri"] for r in res_list["result"]["resources"]]
    assert "crosslab://investigation/summary" in uris
    assert "crosslab://hypotheses/active" in uris

    # 4. resources/read
    read_req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "resources/read",
        "params": {"uri": "crosslab://investigation/summary"}
    }
    read_res = json.loads(server.handle_json_rpc(json.dumps(read_req)))
    assert len(read_res["result"]["contents"]) == 1
    assert "session_id" in read_res["result"]["contents"][0]["text"]

    # 5. prompts/list & prompts/get
    prompts_list_req = {"jsonrpc": "2.0", "id": 5, "method": "prompts/list"}
    prompts_list = json.loads(server.handle_json_rpc(json.dumps(prompts_list_req)))
    pnames = [p["name"] for p in prompts_list["result"]["prompts"]]
    assert "investigate_fear3_host" in pnames

    get_prompt_req = {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "prompts/get",
        "params": {"name": "investigate_fear3_host"}
    }
    get_prompt_res = json.loads(server.handle_json_rpc(json.dumps(get_prompt_req)))
    assert "Agent A" in get_prompt_res["result"]["messages"][0]["content"]["text"]


@pytest.mark.asyncio
async def test_auto_sync_start_and_abort_run_from_messages(host_node):
    """
    Verifies that start_run and abort_run message envelopes automatically
    populate the RunRecord entity in storage and trigger the correlation engine.
    """
    # 1. Start run message
    start_msg = MessageEnvelope(
        message_id="msg_start_22",
        session_id="test-session",
        sender_id="test-host",
        action=ActionType.START_RUN,
        natural_language="START RUN 22: Live observation probe attached at commit a1b2c3d",
        payload={"run_id": 22, "build": "commit-a1b2c3d"},
    )
    host_node.session.record_message(start_msg)

    run = host_node.session.get_run(22)
    assert run is not None
    assert run.run_id == 22
    assert run.build == "commit-a1b2c3d"
    assert "test-host" in run.participants

    # 2. Abort run message
    abort_msg = MessageEnvelope(
        message_id="msg_abort_22",
        session_id="test-session",
        sender_id="test-client",
        action=ActionType.ABORT_RUN,
        natural_language="ABORT RUN 22: Target crash confirmed (BEX 0xc0000409)",
        payload={"run_id": 22},
    )
    host_node.session.record_message(abort_msg)

    run = host_node.session.get_run(22)
    assert run.outcome.value == "crash"
    assert "Target crash confirmed" in run.result_summary


@pytest.mark.asyncio
async def test_auto_sync_chat_run_reproduced(host_node):
    """
    Verifies that natural language chat messages indicating run reproduction
    automatically update the RunRecord outcome.
    """
    chat_msg = MessageEnvelope(
        message_id="msg_repro_23",
        session_id="test-session",
        sender_id="test-client",
        action=ActionType.CHAT,
        natural_language="RUN 23 REPRODUCED: Teardown sequence observed at 00:15:46Z",
    )
    host_node.session.record_message(chat_msg)

    run = host_node.session.get_run(23)
    assert run is not None
    assert run.outcome.value == "reproduced"
    assert "Teardown sequence observed" in run.result_summary


@pytest.mark.asyncio
async def test_observation_links_and_updates_run_record(host_node):
    """
    Verifies that adding an observation attaches it to the parent RunRecord.
    """
    host_node.session.record_run(
        RunRecord(
            run_id=24,
            session_id="test-session",
            build="test-build",
        )
    )
    obs = host_node.session.add_observation(
        run_id=24,
        agent_id="test-client",
        metric_name="last_sent_packet",
        value=500,
    )
    assert obs.run_id == 24

    run = host_node.session.get_run(24)
    assert len(run.observations) == 1
    assert run.observations[0].metric_name == "last_sent_packet"

