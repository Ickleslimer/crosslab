"""
Tests for CrossLab Protocol Models and Actions.
"""

from crosslab.protocol.actions import (
    ActionType,
    AgentRole,
    ExperimentStatus,
    HypothesisStatus,
    RunOutcome,
)
from crosslab.protocol.models import (
    AgentPeer,
    ArtifactPayload,
    CorrelationResult,
    Discrepancy,
    Experiment,
    HandshakeRequest,
    HandshakeResponse,
    Hypothesis,
    InstrumentationRequest,
    MessageEnvelope,
    Observation,
    RunRecord,
    SyncRunSignal,
)


def test_hypothesis_model() -> None:
    hyp = Hypothesis(
        title="Host receive timeout occurs despite successful client sends",
        description="Watchdog expires while client sends continue",
        creator="agent-host",
        confidence=0.6,
    )
    assert hyp.id.startswith("hyp_")
    assert hyp.status == HypothesisStatus.PROPOSED
    assert hyp.confidence == 0.6

    dump = hyp.model_dump()
    assert dump["title"] == "Host receive timeout occurs despite successful client sends"
    reloaded = Hypothesis(**dump)
    assert reloaded.id == hyp.id


def test_experiment_model() -> None:
    exp = Experiment(
        run_id=14,
        title="Trace Steam session packets",
        rationale="Check packet drops",
        host_role="trace receive path",
        client_role="trace send path",
        creator="agent-host",
    )
    assert exp.run_id == 14
    assert exp.status == ExperimentStatus.PROPOSED
    assert exp.id.startswith("exp_")


def test_message_envelope() -> None:
    msg = MessageEnvelope(
        sender_id="host-agent",
        action=ActionType.PROPOSE_EXPERIMENT,
        natural_language="Let's repeat as Run 14",
        payload={"run_id": 14},
    )
    assert msg.message_id.startswith("msg_")
    assert msg.action == ActionType.PROPOSE_EXPERIMENT
    assert msg.payload["run_id"] == 14


def test_artifact_payload_sha256() -> None:
    content = "diff --git a/file b/file\n+fix"
    art = ArtifactPayload(
        filename="fix.patch",
        content_type="text/x-patch",
        content=content,
        author_id="agent-host",
    )
    assert art.sha256 != ""
    assert len(art.sha256) == 64
