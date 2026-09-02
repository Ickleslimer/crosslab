"""Tests for human operator runbook coordination."""

import pytest
from httpx import ASGITransport, AsyncClient

from crosslab.engine.runbook import RunbookCoordinator
from crosslab.engine.session import InvestigationSession
from crosslab.protocol.actions import ActionType, AgentRole
from crosslab.protocol.models import MessageEnvelope
from crosslab.transport.node import A2ANode


def test_runbook_pending_repro(tmp_path):
    session = InvestigationSession(session_id="test", db_path=str(tmp_path / "rb.db"))
    session.record_message(
        MessageEnvelope(
            message_id="repro1",
            session_id="test",
            sender_id="agent-host",
            action=ActionType.HUMAN_REPRO_REQUEST,
            natural_language="Please reproduce Run 14",
            payload={
                "run_id": 14,
                "title": "Run 14 repro",
                "steps": [{"role": "host", "instruction": "Create lobby"}],
            },
        )
    )
    coordinator = RunbookCoordinator(session)
    state = coordinator.get_runbook(run_id=14)
    assert len(state.pending) == 1
    assert state.pending[0].steps[0].instruction == "Create lobby"


def test_runbook_ack_completed(tmp_path):
    session = InvestigationSession(session_id="test", db_path=str(tmp_path / "rb2.db"))
    session.record_message(
        MessageEnvelope(
            message_id="repro2",
            session_id="test",
            sender_id="agent-host",
            action=ActionType.HUMAN_REPRO_REQUEST,
            natural_language="Repro",
            payload={"run_id": 14, "steps": [{"role": "both", "instruction": "Wait"}]},
        )
    )
    session.record_message(
        MessageEnvelope(
            message_id="ack1",
            session_id="test",
            sender_id="human-host",
            action=ActionType.HUMAN_SIGNAL,
            natural_language="Done",
            payload={"ack_message_id": "repro2", "signal": "ack", "run_id": 14},
        )
    )
    state = RunbookCoordinator(session).get_runbook()
    assert len(state.pending) == 0
    assert len(state.completed) == 1


@pytest.mark.asyncio
async def test_runbook_api(tmp_path):
    node = A2ANode(
        agent_id="test-host",
        role=AgentRole.HOST,
        db_path=str(tmp_path / "api_rb.db"),
        session_id="test",
    )
    transport = ASGITransport(app=node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/v1/a2a/messages",
            json=MessageEnvelope(
                message_id="api_repro",
                session_id="test",
                sender_id="agent-host",
                action=ActionType.HUMAN_REPRO_REQUEST,
                natural_language="Repro steps",
                payload={
                    "run_id": 20,
                    "steps": [{"role": "client", "instruction": "Join lobby"}],
                },
            ).model_dump(),
        )
        res = await client.get("/v1/a2a/runbook", params={"run_id": 20})
        data = res.json()
        assert len(data["pending"]) == 1


def test_transcript_human_section(tmp_path):
    session = InvestigationSession(session_id="test", db_path=str(tmp_path / "tx.db"))
    session.record_message(
        MessageEnvelope(
            message_id="h1",
            session_id="test",
            sender_id="human-host",
            action=ActionType.HUMAN_SIGNAL,
            natural_language="Disconnect after entering the game",
            payload={"run_id": 14, "signal": "disconnect"},
        )
    )
    md = session.export_transcript_markdown()
    assert "Human Operator Runbook" in md
    assert "disconnect" in md.lower()
