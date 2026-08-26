"""
Tests for SQLite Storage Engine.
"""

from crosslab.engine.storage import Storage
from crosslab.protocol.actions import AgentRole, ExperimentStatus, HypothesisStatus, RunOutcome
from crosslab.protocol.models import (
    AgentPeer,
    ArtifactPayload,
    Experiment,
    Hypothesis,
    InstrumentationRequest,
    MessageEnvelope,
    Observation,
    RunRecord,
)


def test_storage_peers_and_messages() -> None:
    storage = Storage(":memory:")
    peer = AgentPeer(
        agent_id="host-agent",
        role=AgentRole.HOST,
        endpoint_url="http://127.0.0.1:8765",
    )
    storage.upsert_peer(peer, session_id="test-session")
    peers = storage.get_peers(session_id="test-session")
    assert len(peers) == 1
    assert peers[0].agent_id == "host-agent"
    assert peers[0].role == AgentRole.HOST

    msg = MessageEnvelope(
        session_id="test-session",
        sender_id="host-agent",
        natural_language="Hello peer",
    )
    storage.save_message(msg)
    msgs = storage.get_messages(session_id="test-session")
    assert len(msgs) == 1
    assert msgs[0].natural_language == "Hello peer"


def test_storage_hypotheses_and_experiments() -> None:
    storage = Storage(":memory:")
    hyp = Hypothesis(
        session_id="test-session",
        title="Hypothesis 1",
        description="Description 1",
        creator="agent-1",
    )
    storage.save_hypothesis(hyp)
    hyps = storage.get_hypotheses(session_id="test-session")
    assert len(hyps) == 1
    assert hyps[0].title == "Hypothesis 1"

    exp = Experiment(
        session_id="test-session",
        run_id=14,
        hypothesis_id=hyp.id,
        title="Experiment 14",
        rationale="Test hypothesis 1",
        host_role="trace recv",
        client_role="trace send",
        creator="agent-1",
    )
    storage.save_experiment(exp)
    exps = storage.get_experiments(session_id="test-session")
    assert len(exps) == 1
    assert exps[0].run_id == 14


def test_storage_runs_and_observations() -> None:
    storage = Storage(":memory:")
    obs = Observation(
        session_id="test-session",
        run_id=14,
        agent_id="host-agent",
        metric_name="packets_received",
        value=8831,
    )
    storage.save_observation(obs)

    run = RunRecord(
        run_id=14,
        session_id="test-session",
        build="netprobe-0.2.1",
        outcome=RunOutcome.REPRODUCED,
        host={"last_received_packet": 8831},
        client={"last_sent_packet": 8835},
    )
    storage.save_run(run)

    loaded_run = storage.get_run(14, session_id="test-session")
    assert loaded_run is not None
    assert loaded_run.run_id == 14
    assert len(loaded_run.observations) == 1
    assert loaded_run.observations[0].metric_name == "packets_received"
    assert loaded_run.observations[0].value == 8831
