"""
Tests for A2A Transport Layer, Handshake, and Sync Signals.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from crosslab.protocol.actions import ActionType, AgentRole
from crosslab.protocol.models import HandshakeRequest, MessageEnvelope, SyncRunSignal
from crosslab.transport.node import A2ANode


@pytest.mark.asyncio
async def test_a2a_node_endpoints() -> None:
    node = A2ANode(
        agent_id="host-agent",
        role=AgentRole.HOST,
        session_id="test-session",
    )

    transport = ASGITransport(app=node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Health check
        res = await client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"
        assert res.json()["role"] == "host"

        # Handshake
        hs_req = HandshakeRequest(
            agent_id="client-agent",
            role=AgentRole.CLIENT,
            endpoint_url="http://127.0.0.1:8766",
            capabilities=["reasoning", "instrumentation"],
        )
        res = await client.post("/v1/a2a/handshake", json=hs_req.model_dump())
        assert res.status_code == 200
        data = res.json()
        assert data["accepted"] is True
        assert len(data["peers"]) >= 2

        # Ingest message
        msg = MessageEnvelope(
            sender_id="client-agent",
            action=ActionType.CHAT,
            natural_language="Transport test message",
        )
        res = await client.post("/v1/a2a/messages", json=msg.model_dump())
        assert res.status_code == 200
        assert res.json()["status"] == "received"

        # Sync signal
        sync_sig = SyncRunSignal(
            run_id=14,
            sender_id="client-agent",
            phase="ready",
        )
        res = await client.post("/v1/a2a/runs/sync", json=sync_sig.model_dump())
        assert res.status_code == 200
        assert res.json()["signal"]["phase"] == "ready"

        # Query summary
        res = await client.get("/v1/a2a/summary")
        assert res.status_code == 200
        summary = res.json()
        assert summary["session_id"] == "test-session"
        assert summary["peers_count"] >= 2
