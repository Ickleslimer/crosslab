"""Tests for probe attach freshness validation."""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from crosslab.engine.barrier import BarrierCoordinator, BarrierPhase
from crosslab.engine.probe_validation import validate_instrumentation_payload
from crosslab.engine.session import InvestigationSession
from crosslab.protocol.actions import ActionType, AgentRole
from crosslab.protocol.models import MessageEnvelope
from crosslab.transport.node import A2ANode


@pytest.fixture
def session(tmp_path):
    return InvestigationSession(
        session_id="test-session",
        db_path=str(tmp_path / "probe.db"),
    )


def test_validate_missing_pid_non_strict():
    result = validate_instrumentation_payload({}, strict=False)
    assert result["ok"] is True


def test_validate_missing_pid_strict():
    result = validate_instrumentation_payload({}, strict=True)
    assert result["ok"] is False
    assert "missing pid" in result["reason"]


def test_validate_stale_pid():
    with patch("crosslab.engine.probe_validation.is_process_alive", return_value=False):
        result = validate_instrumentation_payload({"pid": 99999}, strict=False)
    assert result["ok"] is False
    assert "not running" in result["reason"]


def test_validate_pid_with_matching_start_time():
    with patch("crosslab.engine.probe_validation.is_process_alive", return_value=True):
        with patch("crosslab.engine.probe_validation.get_process_start_time", return_value=1000.0):
            result = validate_instrumentation_payload(
                {"pid": 1234, "process_start_time": 1000.5},
                strict=True,
            )
    assert result["ok"] is True


def test_validate_pid_with_mismatched_start_time():
    with patch("crosslab.engine.probe_validation.is_process_alive", return_value=True):
        with patch("crosslab.engine.probe_validation.get_process_start_time", return_value=1000.0):
            result = validate_instrumentation_payload(
                {"pid": 1234, "process_start_time": 1010.0},
                strict=True,
            )
    assert result["ok"] is False
    assert "mismatch" in result["reason"]


def test_validate_remote_peer_skips_process_check():
    result = validate_instrumentation_payload(
        {"pid": 99999},
        strict=False,
        validate_local_process=False,
    )
    assert result["ok"] is True
    assert result["reason"] == "remote_peer_unverified"


def test_barrier_strict_rejects_stale_pid(session):
    coordinator = BarrierCoordinator(
        session,
        strict_instrumentation=True,
        local_agent_id="agent-client",
    )
    with patch("crosslab.engine.probe_validation.is_process_alive", return_value=False):
        coordinator.on_message(
            MessageEnvelope(
                message_id="inst_stale",
                session_id="test-session",
                sender_id="agent-client",
                action=ActionType.REPORT_INSTRUMENTATION_READY,
                natural_language="Frida attached PID 8076 for Run 14",
                payload={"run_id": 14, "pid": 8076, "process_start_time": 1000.0},
            )
        )
    state = coordinator.get_barrier_state(14)
    assert state.ready["client"] is False
    assert state.instrumentation["client"]["validation"]["ok"] is False


def test_barrier_valid_pid_sets_ready(session):
    coordinator = BarrierCoordinator(
        session,
        strict_instrumentation=True,
        local_agent_id="agent-client",
    )
    with patch("crosslab.engine.probe_validation.is_process_alive", return_value=True):
        with patch("crosslab.engine.probe_validation.get_process_start_time", return_value=1000.0):
            coordinator.on_message(
                MessageEnvelope(
                    message_id="inst_ok",
                    session_id="test-session",
                    sender_id="agent-client",
                    action=ActionType.REPORT_INSTRUMENTATION_READY,
                    natural_language="Frida attached PID 8076 for Run 14",
                    payload={"run_id": 14, "pid": 8076, "process_start_time": 1000.0},
                )
            )
    state = coordinator.get_barrier_state(14)
    assert state.ready["client"] is True
    assert state.instrumentation["client"]["validation"]["ok"] is True
    assert state.instrumentation["client"]["pid"] == 8076


def test_barrier_remote_ready_accepted(session):
    coordinator = BarrierCoordinator(
        session,
        strict_instrumentation=True,
        local_agent_id="agent-host",
    )
    coordinator.on_message(
        MessageEnvelope(
            message_id="inst_remote",
            session_id="test-session",
            sender_id="agent-client",
            action=ActionType.REPORT_INSTRUMENTATION_READY,
            natural_language="Frida attached PID 8076 for Run 14",
            payload={"run_id": 14, "pid": 8076},
        )
    )
    state = coordinator.get_barrier_state(14)
    assert state.ready["client"] is True
    assert state.instrumentation["client"]["validation"]["reason"] == "remote_peer_unverified"


@pytest.mark.asyncio
async def test_node_strict_rejects_local_stale_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("CROSSLAB_STRICT_INSTRUMENTATION", "1")
    node = A2ANode(
        agent_id="agent-client",
        role=AgentRole.CLIENT,
        db_path=str(tmp_path / "strict.db"),
        session_id="test-session",
    )
    transport = ASGITransport(app=node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("crosslab.engine.probe_validation.is_process_alive", return_value=False):
            res = await client.post(
                "/v1/a2a/messages",
                json={
                    "message_id": "local_stale",
                    "session_id": "test-session",
                    "sender_id": "agent-client",
                    "action": ActionType.REPORT_INSTRUMENTATION_READY.value,
                    "natural_language": "READY Run 14 PID 99999",
                    "payload": {"run_id": 14, "pid": 99999, "process_start_time": 1000.0},
                },
            )
        assert res.status_code == 422
        assert res.json()["detail"]["status"] == "rejected"


@pytest.mark.asyncio
async def test_node_strict_accepts_remote_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("CROSSLAB_STRICT_INSTRUMENTATION", "1")
    node = A2ANode(
        agent_id="agent-host",
        role=AgentRole.HOST,
        db_path=str(tmp_path / "remote.db"),
        session_id="test-session",
    )
    transport = ASGITransport(app=node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/v1/a2a/messages",
            json={
                "message_id": "remote_ok",
                "session_id": "test-session",
                "sender_id": "agent-client",
                "action": ActionType.REPORT_INSTRUMENTATION_READY.value,
                "natural_language": "READY Run 14 PID 8076",
                "payload": {"run_id": 14, "pid": 8076},
            },
        )
        assert res.status_code == 200
        assert res.json()["status"] == "received"
