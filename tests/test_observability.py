"""Tests for session observability reporting."""

import pytest
from httpx import ASGITransport, AsyncClient

from crosslab.engine.observability import build_observability_report
from crosslab.engine.session import InvestigationSession
from crosslab.protocol.actions import ActionType, AgentRole
from crosslab.protocol.models import MessageEnvelope
from crosslab.transport.node import A2ANode


def test_observability_report_counts_messages(tmp_path):
    session = InvestigationSession(
        session_id="obs-test",
        db_path=str(tmp_path / "obs.db"),
        transcript_dir=str(tmp_path / "transcripts"),
    )
    session.record_message(
        MessageEnvelope(
            message_id="msg1",
            session_id="obs-test",
            sender_id="agent-host",
            action=ActionType.CHAT,
            natural_language="hello",
        )
    )
    report = build_observability_report(session, "agent-host")
    assert report["message_count"] == 1
    assert report["transcript_enabled"] is True
    assert report["last_message_age_s"] is not None
    assert report["peer_count"] == 0


@pytest.mark.asyncio
async def test_observability_endpoint(tmp_path):
    node = A2ANode(
        agent_id="agent-host",
        role=AgentRole.HOST,
        db_path=str(tmp_path / "api_obs.db"),
        transcript_dir=str(tmp_path / "transcripts"),
        session_id="obs-api",
    )
    node.session.record_message(
        MessageEnvelope(
            message_id="api_msg",
            session_id="obs-api",
            sender_id="agent-host",
            action=ActionType.CHAT,
            natural_language="observability test",
        )
    )
    transport = ASGITransport(app=node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/v1/a2a/observability")
        assert res.status_code == 200
        data = res.json()
        assert data["message_count"] == 1
        assert "db_path" in data

        health = await client.get("/health")
        assert health.status_code == 200
        health_data = health.json()
        assert "observability_ok" in health_data
        assert health_data["message_count"] == 1
