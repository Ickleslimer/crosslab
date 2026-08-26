"""
Tests for Evidence Graphs, Subjective Agent Assessments, and Time Uncertainty.
"""

from crosslab.engine.analyzers import TemporalAnalyzer
from crosslab.engine.session import InvestigationSession
from crosslab.protocol.actions import EvidenceRelation, EvidenceType, HypothesisStatus
from crosslab.protocol.models import (
    EvidenceItem,
    Hypothesis,
    Observation,
    RunRecord,
    get_monotonic_ns,
)


def test_evidence_graph_and_assessments() -> None:
    session = InvestigationSession(session_id="test-evidence")

    # 1. Propose hypothesis
    hyp = session.propose_hypothesis(
        title="Socket buffer overflow causes silent packet drop",
        description="Receive buffer fills up faster than application thread polls",
        creator="agent-a",
        confidence=0.5,
    )
    assert hyp.status == HypothesisStatus.ACTIVE
    assert "agent-a" in hyp.agent_assessments
    assert hyp.agent_assessments["agent-a"].confidence_score == 0.5

    # 2. Agent B assesses hypothesis with higher confidence
    session.assess_hypothesis(
        hypothesis_id=hyp.id,
        agent_id="agent-b",
        confidence_score=0.8,
        rationale="Matches observed high CPU load on host receiver thread",
    )
    reloaded = session.storage.get_hypothesis(hyp.id)
    assert reloaded is not None
    assert len(reloaded.agent_assessments) == 2
    assert reloaded.confidence == 0.65  # (0.5 + 0.8) / 2

    # 3. Add supporting evidence from a run
    ev1 = session.add_evidence(
        hypothesis_id=hyp.id,
        evidence_type=EvidenceType.RUN,
        relation=EvidenceRelation.SUPPORTS,
        source_agent_id="agent-a",
        source_id="14",
        rationale="Run 14 showed packet drop at packet #8831",
    )
    assert ev1 is not None
    reloaded = session.storage.get_hypothesis(hyp.id)
    assert reloaded is not None
    assert len(reloaded.evidence_graph) == 1
    assert reloaded.status == HypothesisStatus.SUPPORTED

    # 4. Challenge hypothesis (adds CONTRADICTS evidence to graph)
    session.challenge_hypothesis(
        hypothesis_id=hyp.id,
        challenger="agent-b",
        reason="CPU usage dropped before timeout in Run 16",
        counter_evidence="run-16-telemetry",
    )
    reloaded = session.storage.get_hypothesis(hyp.id)
    assert reloaded is not None
    assert len(reloaded.evidence_graph) == 2
    # Has both SUPPORTS and CONTRADICTS -> INCONCLUSIVE
    assert reloaded.status == HypothesisStatus.INCONCLUSIVE


def test_temporal_analyzer_uncertainty_window() -> None:
    analyzer = TemporalAnalyzer()

    t_client_send = 1_000_000_000
    t_host_timeout = 1_020_000_000  # 20ms later

    run = RunRecord(
        run_id=5,
        host={
            "events": [
                {
                    "message": "Host watchdog timeout triggered",
                    "monotonic_ns": t_host_timeout,
                    "uncertainty_ms": 1.5,
                }
            ]
        },
        client={
            "events": [
                {
                    "message": "Client send packet #50",
                    "monotonic_ns": t_client_send,
                    "uncertainty_ms": 2.0,
                }
            ]
        },
    )

    discrepancies = analyzer.analyze(run)
    assert len(discrepancies) == 1
    disc = discrepancies[0]
    assert disc.code == "TIMING_ORDERING_OBSERVATION"
    assert "20.0 ms" in disc.description
    assert "+/-2.0 ms" in disc.description
