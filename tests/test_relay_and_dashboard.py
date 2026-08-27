"""
Tests for Central Relay Hub and Embedded HTML5 Dashboard.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from crosslab.protocol.models import AgentPeer, MessageEnvelope
from crosslab.transport.node import A2ANode
from crosslab.transport.relay import CrossLabRelay


@pytest.mark.asyncio
async def test_embedded_dashboard_route() -> None:
    node = A2ANode(agent_id="test-hud-node")
    transport = ASGITransport(app=node.app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # GET /
        res1 = await client.get("/")
        assert res1.status_code == 200
        assert "CrossLab: Multi-Machine Investigation HUD" in res1.text

        # GET /dashboard
        res2 = await client.get("/dashboard")
        assert res2.status_code == 200
        assert "Evidence Graph" in res2.text


@pytest.mark.asyncio
async def test_central_relay_hub_routing() -> None:
    relay = CrossLabRelay(port=8080)
    transport = ASGITransport(app=relay.app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Health
        res = await client.get("/health")
        assert res.status_code == 200
        assert res.json()["service"] == "crosslab-relay"

        # Register node
        peer = AgentPeer(
            agent_id="node-uk",
            role="host",
            endpoint_url="http://192.168.1.50:8765",
        )
        res = await client.post("/relay/register?session_id=transatlantic", json=peer.model_dump())
        assert res.status_code == 200
        assert res.json()["status"] == "registered"
        assert len(res.json()["peers"]) == 1

        # Relay message
        msg = MessageEnvelope(
            session_id="transatlantic",
            sender_id="node-uk",
            natural_language="Hello from UK through central relay!",
        )
        res = await client.post("/relay/messages", json=msg.model_dump())
        assert res.status_code == 200
        assert res.json()["status"] == "relayed"
