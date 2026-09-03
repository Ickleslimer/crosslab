"""Tests for ledger consistency probe."""

import pytest
from httpx import ASGITransport, AsyncClient

from crosslab.protocol.actions import ActionType, AgentRole
from crosslab.protocol.models import MessageEnvelope
from crosslab.transport.node import A2ANode


@pytest.mark.asyncio
async def test_compare_ledgers_mismatch(tmp_path):
    host = A2ANode(
        agent_id="agent-host",
        role=AgentRole.HOST,
        db_path=str(tmp_path / "host.db"),
        session_id="probe-session",
    )
    client = A2ANode(
        agent_id="agent-client",
        role=AgentRole.CLIENT,
        db_path=str(tmp_path / "client.db"),
        session_id="probe-session",
    )
    host.session.record_message(
        MessageEnvelope(
            message_id="host_only",
            session_id="probe-session",
            sender_id="agent-host",
            action=ActionType.CHAT,
            natural_language="host message",
        )
    )
    client.session.record_message(
        MessageEnvelope(
            message_id="client_only",
            session_id="probe-session",
            sender_id="agent-client",
            action=ActionType.CHAT,
            natural_language="client message",
        )
    )

    host_transport = ASGITransport(app=host.app)
    client_transport = ASGITransport(app=client.app)

    async with AsyncClient(transport=host_transport, base_url="http://host") as hc:
        host_msgs = (await hc.get("/v1/a2a/messages", params={"limit": 1000})).json()
    async with AsyncClient(transport=client_transport, base_url="http://client") as cc:
        client_msgs = (await cc.get("/v1/a2a/messages", params={"limit": 1000})).json()

    host_ids = {m["message_id"] for m in host_msgs}
    client_ids = {m["message_id"] for m in client_msgs}
    assert "host_only" in host_ids
    assert "client_only" in client_ids
    assert host_ids != client_ids


@pytest.mark.asyncio
async def test_fix_ledger_pulls_missing(tmp_path):
    host = A2ANode(
        agent_id="agent-host",
        role=AgentRole.HOST,
        db_path=str(tmp_path / "fix_host.db"),
        session_id="fix-session",
    )
    client = A2ANode(
        agent_id="agent-client",
        role=AgentRole.CLIENT,
        db_path=str(tmp_path / "fix_client.db"),
        session_id="fix-session",
    )
    host.session.record_message(
        MessageEnvelope(
            message_id="shared_msg",
            session_id="fix-session",
            sender_id="agent-host",
            action=ActionType.CHAT,
            natural_language="shared",
        )
    )
    client.session.record_message(
        MessageEnvelope(
            message_id="shared_msg",
            session_id="fix-session",
            sender_id="agent-host",
            action=ActionType.CHAT,
            natural_language="shared",
        )
    )
    client.session.record_message(
        MessageEnvelope(
            message_id="peer_extra",
            session_id="fix-session",
            sender_id="agent-client",
            action=ActionType.CHAT,
            natural_language="extra on client",
        )
    )

    host_transport = ASGITransport(app=host.app)
    client_transport = ASGITransport(app=client.app)

    async with AsyncClient(transport=client_transport, base_url="http://client") as cc:
        peer_msgs = (await cc.get("/v1/a2a/messages", params={"limit": 1000})).json()
    async with AsyncClient(transport=host_transport, base_url="http://host") as hc:
        host_before = (await hc.get("/v1/a2a/messages", params={"limit": 1000})).json()
        host_ids_before = {m["message_id"] for m in host_before}
        assert "peer_extra" not in host_ids_before

        extra = next(m for m in peer_msgs if m["message_id"] == "peer_extra")
        await hc.post("/v1/a2a/messages", json=extra)
        host_after = (await hc.get("/v1/a2a/messages", params={"limit": 1000})).json()
        host_ids_after = {m["message_id"] for m in host_after}
        assert "peer_extra" in host_ids_after
