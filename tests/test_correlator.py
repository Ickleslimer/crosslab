"""
Tests for Correlation and Differential Analysis Engine.
"""

from crosslab.engine.correlator import CorrelationEngine
from crosslab.protocol.actions import RunOutcome
from crosslab.protocol.models import RunRecord


def test_correlation_packet_drop_and_asymmetric_disconnect() -> None:
    run = RunRecord(
        run_id=14,
        session_id="fear3-test",
        build="netprobe-0.2.1",
        outcome=RunOutcome.REPRODUCED,
        host={
            "disconnect_time": "18:42:19.331",
            "reason": "connection_lost",
            "last_received_packet": 8831,
        },
        client={
            "last_sent_packet": 8835,
            "transport_result": "success",
            "displayed_reason": "kicked_by_host",
        },
    )

    corr = CorrelationEngine().correlate_run(run)
    assert corr.run_id == 14
    assert corr.reproduced is True
    assert len(corr.discrepancies) >= 2

    codes = [d.code for d in corr.discrepancies]
    assert "PACKET_SEQUENCE_GAP" in codes
    assert "FEAR3_ASYMMETRIC_UI_MISINFORMATION" in codes
    assert "UNRECIPROCATED_TRANSPORT_SUCCESS" in codes

    assert "SUPPORTED" in (corr.hypothesis_verdict or "")
    assert len(corr.suggested_next_steps) >= 2


def test_diff_runs() -> None:
    run_12 = RunRecord(
        run_id=12,
        build="netprobe-0.1.0",
        outcome=RunOutcome.NOT_REPRODUCED,
        host={"last_received_packet": 8500, "reason": "clean_exit"},
        client={"last_sent_packet": 8500, "transport_result": "success"},
    )
    run_14 = RunRecord(
        run_id=14,
        build="netprobe-0.2.1",
        outcome=RunOutcome.REPRODUCED,
        host={"last_received_packet": 8831, "reason": "connection_lost"},
        client={"last_sent_packet": 8835, "transport_result": "success"},
    )

    diff = CorrelationEngine.diff_runs(run_12, run_14)
    assert diff["run_a_id"] == 12
    assert diff["run_b_id"] == 14
    assert diff["build_changed"] is True
    assert diff["build_a"] == "netprobe-0.1.0"
    assert diff["build_b"] == "netprobe-0.2.1"
    assert "last_received_packet" in diff["host_diff"]
    assert diff["host_diff"]["last_received_packet"]["run_a"] == 8500
    assert diff["host_diff"]["last_received_packet"]["run_b"] == 8831
