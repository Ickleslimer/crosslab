"""Tests for topology health and handshake warnings."""

import pytest
from httpx import ASGITransport, AsyncClient

from crosslab.protocol.actions import AgentRole
from crosslab.protocol.models import HandshakeRequest
from crosslab.transport.node import A2ANode
from crosslab.transport.topology import is_loopback_url, topology_warning
from crosslab.protocol.models import AgentPeer


def test_is_loopback_url():
    assert is_loopback_url("http://127.0.0.1:8766")
    assert not is_loopback_url("http://192.168.0.5:8765")


def test_topology_warning_different_machine():
    peer = AgentPeer(
        agent_id="remote",
        role=AgentRole.CLIENT,
        endpoint_url="http://127.0.0.1:8766",
        machine_name="Machine-B",
    )
    warn = topology_warning("Machine-A", peer)
    assert warn is not None
    assert "loopback" in warn.lower()


@pytest.mark.asyncio
async def test_health_extended_fields(tmp_path):
    node = A2ANode(
        agent_id="test-host",
        role=AgentRole.HOST,
        db_path=str(tmp_path / "health.db"),
        session_id="test",
        host="127.0.0.1",
        port=8765,
        machine_name="Machine-A",
    )
    transport = ASGITransport(app=node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/health")
        data = res.json()
        assert "advertised_url" in data
        assert data["advertised_reachable_externally"] is False
        assert "peers" in data


@pytest.mark.asyncio
async def test_handshake_topology_warning(tmp_path):
    host = A2ANode(
        agent_id="host-a",
        role=AgentRole.HOST,
        db_path=str(tmp_path / "host.db"),
        session_id="test",
        machine_name="Machine-A",
    )
    transport = ASGITransport(app=host.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        req = HandshakeRequest(
            agent_id="client-b",
            role=AgentRole.CLIENT,
            endpoint_url="http://127.0.0.1:8766",
            machine_name="Machine-B",
        )
        res = await client.post("/v1/a2a/handshake", json=req.model_dump())
        data = res.json()
        assert res.status_code == 200
        assert len(data.get("warnings", [])) >= 1
