"""Tests for agent profile model, API, and handshake propagation."""

import pytest
from httpx import ASGITransport, AsyncClient

from crosslab.engine.agent_profile import (
    AgentProfile,
    format_profile_label,
    load_agent_profile,
    profile_from_env,
    resolve_local_profile,
    save_agent_profile,
)
from crosslab.protocol.actions import AgentRole
from crosslab.transport.node import A2ANode


def test_profile_from_env(monkeypatch):
    monkeypatch.setenv("CROSSLAB_HARNESS", "codex")
    monkeypatch.setenv("CROSSLAB_AGENT_MODEL", "gpt-5.6-sol")
    monkeypatch.setenv("CROSSLAB_AGENT_MODEL_DISPLAY", "GPT Sol 5.6")
    profile = profile_from_env()
    assert profile.harness == "codex"
    assert profile.model_id == "gpt-5.6-sol"
    assert profile.model_display == "GPT Sol 5.6"
    assert profile.source == "env"
    assert profile.confidence == 1.0


def test_profile_round_trip(tmp_path):
    data_dir = str(tmp_path / "session-data")
    profile = AgentProfile(
        harness="cursor",
        model_id="composer-2.5",
        model_display="Composer 2.5",
        source="manual",
        confidence=1.0,
    )
    save_agent_profile(data_dir, profile)
    loaded = load_agent_profile(data_dir)
    assert loaded.harness == "cursor"
    assert loaded.model_display == "Composer 2.5"
    assert loaded.source == "manual"


def test_resolve_local_profile_manual_wins_over_env(monkeypatch):
    monkeypatch.setenv("CROSSLAB_HARNESS", "codex")
    monkeypatch.setenv("CROSSLAB_AGENT_MODEL", "other-model")
    stored = AgentProfile(
        harness="antigravity",
        model_id="gemini-flash",
        model_display="Gemini Flash",
        source="manual",
        confidence=1.0,
    )
    resolved = resolve_local_profile(stored)
    assert resolved.harness == "antigravity"
    assert resolved.model_id == "gemini-flash"


def test_format_profile_label():
    assert format_profile_label(AgentProfile()) == "Unknown"
    label = format_profile_label(
        AgentProfile(harness="codex", model_display="GPT Sol 5.6")
    )
    assert label == "codex / GPT Sol 5.6"


@pytest.mark.asyncio
async def test_profile_api(tmp_path):
    db_path = str(tmp_path / "profile.db")
    node = A2ANode(
        agent_id="test-host",
        role=AgentRole.HOST,
        db_path=db_path,
        session_id="test-session",
    )
    transport = ASGITransport(app=node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        get_res = await client.get("/v1/a2a/session/profile")
        assert get_res.status_code == 200

        put_res = await client.put(
            "/v1/a2a/session/profile",
            json={
                "harness": "codex",
                "model_id": "gpt-5.6-sol",
                "model_display": "GPT Sol 5.6",
            },
        )
        assert put_res.status_code == 200
        data = put_res.json()
        assert data["harness"] == "codex"
        assert data["model_display"] == "GPT Sol 5.6"
        assert data["source"] == "manual"

        card_res = await client.get("/.well-known/agent-card.json")
        card = card_res.json()
        assert card["metadata"]["agent_profile"]["harness"] == "codex"


@pytest.mark.asyncio
async def test_profile_from_env_on_node_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("CROSSLAB_HARNESS", "opencode")
    monkeypatch.setenv("CROSSLAB_AGENT_MODEL", "claude-sonnet")
    monkeypatch.setenv("CROSSLAB_AGENT_MODEL_DISPLAY", "Claude Sonnet")
    db_path = str(tmp_path / "env-profile.db")
    node = A2ANode(
        agent_id="env-host",
        role=AgentRole.HOST,
        db_path=db_path,
        session_id="env-session",
    )
    assert node.agent_profile.harness == "opencode"
    assert node.agent_profile.model_display == "Claude Sonnet"


@pytest.mark.asyncio
async def test_handshake_propagates_profile(tmp_path):
    host_db = str(tmp_path / "host.db")
    client_db = str(tmp_path / "client.db")

    host = A2ANode(
        agent_id="host-agent",
        role=AgentRole.HOST,
        host="127.0.0.1",
        port=18765,
        db_path=host_db,
        session_id="profile-session",
    )
    host.agent_profile = AgentProfile(
        harness="codex",
        model_id="gpt-5.6-sol",
        model_display="GPT Sol 5.6",
        source="manual",
        confidence=1.0,
    )
    host._apply_profile_to_self()

    client = A2ANode(
        agent_id="client-agent",
        role=AgentRole.CLIENT,
        host="127.0.0.1",
        port=18766,
        db_path=client_db,
        session_id="profile-session",
    )
    client.agent_profile = AgentProfile(
        harness="cursor",
        model_id="claude-sonnet",
        model_display="Claude Sonnet",
        source="manual",
        confidence=1.0,
    )
    client._apply_profile_to_self()

    host_transport = ASGITransport(app=host.app)
    client_transport = ASGITransport(app=client.app)

    async with AsyncClient(transport=host_transport, base_url="http://test") as host_client:
        async with AsyncClient(transport=client_transport, base_url="http://test") as cli_client:
            hs_req = {
                "agent_id": "client-agent",
                "role": "client",
                "endpoint_url": "http://127.0.0.1:18766",
                "agent_card": client.agent_card.model_dump(),
            }
            res = await host_client.post("/v1/a2a/handshake", json=hs_req)
            assert res.status_code == 200

            peers_res = await host_client.get("/v1/a2a/peers/detailed")
            peers = peers_res.json()
            client_peer = next(p for p in peers if p["agent_id"] == "client-agent")
            assert client_peer["harness"] == "cursor"
            assert client_peer["model_display"] == "Claude Sonnet"

            hs_req_host = {
                "agent_id": "host-agent",
                "role": "host",
                "endpoint_url": "http://127.0.0.1:18765",
                "agent_card": host.agent_card.model_dump(),
            }
            res2 = await cli_client.post("/v1/a2a/handshake", json=hs_req_host)
            assert res2.status_code == 200

            peers_res2 = await cli_client.get("/v1/a2a/peers/detailed")
            host_peer = next(p for p in peers_res2.json() if p["agent_id"] == "host-agent")
            assert host_peer["harness"] == "codex"
            assert host_peer["model_display"] == "GPT Sol 5.6"


@pytest.mark.asyncio
async def test_health_includes_agent_profile(tmp_path):
    db_path = str(tmp_path / "health.db")
    node = A2ANode(
        agent_id="health-host",
        role=AgentRole.HOST,
        db_path=db_path,
    )
    node.agent_profile = AgentProfile(
        harness="codex",
        model_id="gpt-5",
        model_display="GPT-5",
        source="manual",
        confidence=1.0,
    )
    node._apply_profile_to_self()

    transport = ASGITransport(app=node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/health")
        data = res.json()
        assert data["agent_profile"]["harness"] == "codex"
        assert data["agent_profile"]["model_display"] == "GPT-5"
