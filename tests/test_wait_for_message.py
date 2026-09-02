"""
Tests for crosslab_wait_for_message long-poll and since_id cursor.
"""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from crosslab.mcp.server import CrossLabMCPServer
from crosslab.protocol.actions import ActionType, AgentRole
from crosslab.protocol.models import MessageEnvelope
from crosslab.transport.node import A2ANode


@pytest.fixture
def host_node(tmp_path):
    db_path = str(tmp_path / "wait_test.db")
    return A2ANode(
        agent_id="test-host",
        role=AgentRole.HOST,
        db_path=db_path,
        session_id="test-session",
    )


@pytest.mark.asyncio
async def test_get_messages_since_id(host_node):
    host_node.session.record_message(
        MessageEnvelope(
            message_id="msg_alpha",
            session_id="test-session",
            sender_id="peer-client",
            action=ActionType.CHAT,
            natural_language="Alpha",
        )
    )
    host_node.session.record_message(
        MessageEnvelope(
            message_id="msg_beta",
            session_id="test-session",
            sender_id="peer-client",
            action=ActionType.CHAT,
            natural_language="Beta",
        )
    )

    msgs = host_node.session.get_messages(since_id="msg_alpha")
    assert len(msgs) == 1
    assert msgs[0].message_id == "msg_beta"


@pytest.mark.asyncio
async def test_get_messages_action_filter(host_node):
    host_node.session.record_message(
        MessageEnvelope(
            message_id="msg_chat",
            session_id="test-session",
            sender_id="peer-client",
            action=ActionType.CHAT,
            natural_language="Hello",
        )
    )
    host_node.session.record_message(
        MessageEnvelope(
            message_id="msg_ready",
            session_id="test-session",
            sender_id="peer-client",
            action=ActionType.SYNC_READY,
            natural_language="READY",
        )
    )

    msgs = host_node.session.get_messages(actions=["sync_ready"])
    assert len(msgs) == 1
    assert msgs[0].message_id == "msg_ready"


@pytest.mark.asyncio
async def test_wait_for_message_returns_existing(host_node):
    host_node.session.record_message(
        MessageEnvelope(
            message_id="msg_existing",
            session_id="test-session",
            sender_id="peer-client",
            action=ActionType.CHAT,
            natural_language="Already here",
        )
    )

    transport = ASGITransport(app=host_node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/v1/a2a/messages/wait", params={"timeout_s": 1})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["message"]["message_id"] == "msg_existing"


@pytest.mark.asyncio
async def test_wait_for_message_concurrent_delivery(host_node):
    transport = ASGITransport(app=host_node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:

        async def waiter():
            return await client.get("/v1/a2a/messages/wait", params={"timeout_s": 5})

        wait_task = asyncio.create_task(waiter())
        await asyncio.sleep(0.1)

        envelope = MessageEnvelope(
            message_id="msg_incoming",
            session_id="test-session",
            sender_id="peer-client",
            action=ActionType.CHAT,
            natural_language="Peer reply",
        )
        post_res = await client.post("/v1/a2a/messages", json=envelope.model_dump())
        assert post_res.status_code == 200

        res = await wait_task
        data = res.json()
        assert data["status"] == "ok"
        assert data["message"]["message_id"] == "msg_incoming"


@pytest.mark.asyncio
async def test_wait_for_message_timeout(host_node):
    transport = ASGITransport(app=host_node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/v1/a2a/messages/wait", params={"timeout_s": 0.2})
        assert res.status_code == 200
        assert res.json()["status"] == "timeout"


@pytest.mark.asyncio
async def test_wait_excludes_self_messages(host_node):
    host_node.session.record_message(
        MessageEnvelope(
            message_id="msg_self",
            session_id="test-session",
            sender_id="test-host",
            origin_sender_id="test-host",
            action=ActionType.CHAT,
            natural_language="My own message",
        )
    )

    transport = ASGITransport(app=host_node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            "/v1/a2a/messages/wait",
            params={"timeout_s": 0.2, "exclude_self": "true"},
        )
        assert res.json()["status"] == "timeout"


def test_mcp_wait_for_message_tool_definition():
    server = CrossLabMCPServer()
    tools = server.get_tool_definitions()
    names = [t["name"] for t in tools]
    assert "crosslab_wait_for_message" in names
