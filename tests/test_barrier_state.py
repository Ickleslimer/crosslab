"""
Tests for barrier state coordination.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from crosslab.engine.barrier import BarrierCoordinator, BarrierPhase
from crosslab.engine.session import InvestigationSession
from crosslab.protocol.actions import ActionType, AgentRole
from crosslab.protocol.models import MessageEnvelope, RunRecord, RunOutcome, SyncRunSignal
from crosslab.transport.node import A2ANode


@pytest.fixture
def session(tmp_path):
    return InvestigationSession(
        session_id="test-session",
        db_path=str(tmp_path / "barrier.db"),
    )


@pytest.fixture
def coordinator(session):
    return BarrierCoordinator(session)


def _record(coordinator, session, envelope: MessageEnvelope) -> None:
    session.record_message(envelope)
    coordinator.on_message(envelope)


def test_ready_wait_single_side(coordinator, session):
    _record(
        coordinator,
        session,
        MessageEnvelope(
            message_id="msg1",
            session_id="test-session",
            sender_id="agent-host",
            action=ActionType.SYNC_READY,
            natural_language="READY for Run 14",
            payload={"run_id": 14},
        )
    )
    state = coordinator.get_barrier_state(14)
    assert state.phase in (BarrierPhase.READY_WAIT, BarrierPhase.READY)
    assert state.ready["host"] is True
    assert state.ready["client"] is False
    assert state.start_authorized is False


def test_ready_both_sides_start_authorized(coordinator, session):
    _record(
        coordinator,
        session,
        MessageEnvelope(
            message_id="msg_h",
            session_id="test-session",
            sender_id="agent-host",
            action=ActionType.SYNC_READY,
            natural_language="READY Run 14",
            payload={"run_id": 14},
        )
    )
    _record(
        coordinator,
        session,
        MessageEnvelope(
            message_id="msg_c",
            session_id="test-session",
            sender_id="agent-client",
            action=ActionType.SYNC_READY,
            natural_language="READY Run 14",
            payload={"run_id": 14},
        )
    )
    state = coordinator.get_barrier_state(14)
    assert state.ready["host"] is True
    assert state.ready["client"] is True
    assert state.start_authorized is True


def test_session_pause_blocks_start(coordinator, session):
    _record(
        coordinator,
        session,
        MessageEnvelope(
            message_id="msg_pause",
            session_id="test-session",
            sender_id="operator",
            action=ActionType.CHAT,
            natural_language="The session is formally PAUSED by operator directive.",
        )
    )
    _record(
        coordinator,
        session,
        MessageEnvelope(
            message_id="msg_h2",
            session_id="test-session",
            sender_id="agent-host",
            action=ActionType.SYNC_READY,
            natural_language="READY Run 14",
            payload={"run_id": 14},
        )
    )
    _record(
        coordinator,
        session,
        MessageEnvelope(
            message_id="msg_c2",
            session_id="test-session",
            sender_id="agent-client",
            action=ActionType.SYNC_READY,
            natural_language="READY Run 14",
            payload={"run_id": 14},
        )
    )
    state = coordinator.get_barrier_state(14)
    assert state.phase == BarrierPhase.PAUSED
    assert state.start_authorized is False
    assert state.pause_reason is not None


def test_unpause_restores_authorization(coordinator, session):
    _record(coordinator, session, MessageEnvelope(
        message_id="pause",
        session_id="test-session",
        sender_id="operator",
        action=ActionType.CHAT,
        natural_language="formally PAUSED",
    ))
    _record(coordinator, session, MessageEnvelope(
        message_id="unpause",
        session_id="test-session",
        sender_id="operator",
        action=ActionType.CHAT,
        natural_language="UNPAUSE DIRECTIVE RECEIVED",
    ))
    _record(coordinator, session, MessageEnvelope(
        message_id="rh",
        session_id="test-session",
        sender_id="agent-host",
        action=ActionType.SYNC_READY,
        natural_language="READY Run 14",
        payload={"run_id": 14},
    ))
    _record(coordinator, session, MessageEnvelope(
        message_id="rc",
        session_id="test-session",
        sender_id="agent-client",
        action=ActionType.SYNC_READY,
        natural_language="READY Run 14",
        payload={"run_id": 14},
    ))
    state = coordinator.get_barrier_state(14)
    assert state.start_authorized is True


def test_instrumentation_pid(coordinator, session):
    _record(coordinator, session, MessageEnvelope(
        message_id="inst",
        session_id="test-session",
        sender_id="agent-client",
        action=ActionType.REPORT_INSTRUMENTATION_READY,
        natural_language="Frida attached PID 8076 for Run 14",
        payload={"run_id": 14, "pid": 8076},
    ))
    state = coordinator.get_barrier_state(14)
    assert state.instrumentation.get("client", {}).get("pid") == 8076


def test_duplicate_ready_idempotent(coordinator, session):
    for i in range(2):
        _record(coordinator, session, MessageEnvelope(
            message_id=f"dup_{i}",
            session_id="test-session",
            sender_id="agent-host",
            action=ActionType.SYNC_READY,
            natural_language="READY Run 14",
            payload={"run_id": 14},
        ))
    state = coordinator.get_barrier_state(14)
    assert state.ready["host"] is True


def test_sync_signal_ready(coordinator):
    coordinator.on_sync_signal(
        SyncRunSignal(run_id=14, sender_id="agent-client", phase="ready")
    )
    state = coordinator.get_barrier_state(14)
    assert state.ready["client"] is True


@pytest.mark.asyncio
async def test_barrier_api_endpoint(tmp_path):
    node = A2ANode(
        agent_id="test-host",
        role=AgentRole.HOST,
        db_path=str(tmp_path / "api_barrier.db"),
        session_id="test-session",
    )
    node.session.record_run(
        RunRecord(run_id=14, session_id="test-session", outcome=RunOutcome.PENDING)
    )
    node.barrier.on_message(
        MessageEnvelope(
            message_id="api_h",
            session_id="test-session",
            sender_id="agent-host",
            action=ActionType.SYNC_READY,
            natural_language="READY Run 14",
            payload={"run_id": 14},
        )
    )

    transport = ASGITransport(app=node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/v1/a2a/runs/14/barrier")
        assert res.status_code == 200
        data = res.json()
        assert data["run_id"] == 14
        assert data["ready"]["host"] is True
