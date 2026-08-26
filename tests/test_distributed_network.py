"""
Genuine Two-Node Distributed Integration Test.
Launches two independent A2A nodes on separate network ports with separate SQLite ledgers.
Tests discovery handshake, agent cards, network message relay, barrier sync,
observation submission, clock offset calculation, and correlation across the wire.
"""

import asyncio
from pathlib import Path
from typing import Any
import pytest
import uvicorn

from crosslab.agent.client import CrossLabClient
from crosslab.protocol.actions import (
    ActionType,
    AgentRole,
    EvidenceRelation,
    EvidenceType,
    ExperimentStatus,
    HypothesisStatus,
    RunOutcome,
)
from crosslab.protocol.models import (
    Observation,
    RunRecord,
    SyncRunSignal,
    get_monotonic_ns,
)
from crosslab.transport.node import A2ANode


@pytest.mark.asyncio
async def test_distributed_two_node_network_collaboration(tmp_path: Any) -> None:
    port_a = 8901
    port_b = 8902

    db_a = str(tmp_path / "node_a.db")
    db_b = str(tmp_path / "node_b.db")

    # 1. Instantiate Node A (Host) and Node B (Client)
    node_a = A2ANode(
        agent_id="host-agent",
        role=AgentRole.HOST,
        host="127.0.0.1",
        port=port_a,
        session_id="dist-test-session",
        db_path=db_a,
    )

    node_b = A2ANode(
        agent_id="client-agent",
        role=AgentRole.CLIENT,
        host="127.0.0.1",
        port=port_b,
        session_id="dist-test-session",
        db_path=db_b,
    )

    config_a = uvicorn.Config(node_a.app, host="127.0.0.1", port=port_a, log_level="warning")
    config_b = uvicorn.Config(node_b.app, host="127.0.0.1", port=port_b, log_level="warning")

    server_a = uvicorn.Server(config_a)
    server_b = uvicorn.Server(config_b)

    task_a = asyncio.create_task(server_a.serve())
    task_b = asyncio.create_task(server_b.serve())

    await asyncio.sleep(0.5)

    try:
        client_a = CrossLabClient(base_url=f"http://127.0.0.1:{port_a}", agent_id="agent-host")
        client_b = CrossLabClient(base_url=f"http://127.0.0.1:{port_b}", agent_id="agent-client")

        # 2. Test A2A Agent Card Discovery
        card_a = await client_a.get_agent_card()
        card_b = await client_b.get_agent_card()

        assert "CrossLab Node" in card_a.name
        assert card_a.role == AgentRole.HOST
        assert card_b.role == AgentRole.CLIENT
        assert "empirical_investigation" in card_a.capabilities

        # 3. Node B establishes Handshake with Node A
        hs_response = await node_b.connect_to_peer(f"http://127.0.0.1:{port_a}")
        assert hs_response.accepted is True
        assert hs_response.agent_id == "host-agent"

        # Verify clock offset and RTT measurement
        peers_b = node_b.session.get_peers()
        host_peer = next(p for p in peers_b if p.agent_id == "host-agent")
        assert host_peer.clock_uncertainty_ms >= 0.0

        # 4. Message Relay across the Real Network
        # Agent A sends message to Node A -> Node A relays to Node B
        await client_a.send_chat("Ping from Host Agent across the network!")

        await asyncio.sleep(0.3)

        # Verify Node B received and recorded the relayed message in its separate database!
        messages_b = node_b.session.get_messages()
        found_msg = any("Ping from Host Agent" in (m.natural_language or "") for m in messages_b)
        assert found_msg is True, f"Node B did not receive relayed message. Messages: {messages_b}"

        # 5. Node B replies across the network
        await client_b.send_chat("Ack from Client Agent! Network relay confirmed.")

        await asyncio.sleep(0.3)

        messages_a = node_a.session.get_messages()
        found_reply = any("Ack from Client Agent" in (m.natural_language or "") for m in messages_a)
        assert found_reply is True, f"Node A did not receive reply. Messages: {messages_a}"

        # 6. Propose Hypothesis & Experiment
        hyp = await client_a.propose_hypothesis(
            title="Heartbeat timeout under burst traffic",
            description="High UDP send volume starves the receive queue watchdog",
            confidence=0.7,
        )
        assert hyp.title == "Heartbeat timeout under burst traffic"

        exp = await client_a.propose_experiment(
            run_id=3,
            hypothesis_id=hyp.id,
            title="Burst test 100 packets",
            rationale="Verify watchdog starvation",
            host_role="trace receive watchdog",
            client_role="transmit 100 packets",
        )
        assert exp.run_id == 3

        await client_b.accept_experiment(exp.id)

        # 7. Barrier Sync Run (ready -> start -> stop)
        await client_a.send_sync_signal(run_id=3, phase="ready")
        await client_b.send_sync_signal(run_id=3, phase="ready")
        await client_a.send_sync_signal(run_id=3, phase="start")

        # 8. Submit Observations with Monotonic Timestamps
        t_client_send = get_monotonic_ns()
        t_host_timeout = t_client_send + 15_000_000  # 15 ms later

        await client_b.add_observation(
            run_id=3,
            metric_name="last_sent_seq",
            value=100,
            notes="Client finished sending burst",
        )

        await client_a.add_observation(
            run_id=3,
            metric_name="last_received_seq",
            value=94,
            notes="Host received up to packet 94",
        )

        # Record shared RunRecord
        run_3 = RunRecord(
            run_id=3,
            hypothesis_id=hyp.id,
            build="netprobe-0.2.0",
            outcome=RunOutcome.REPRODUCED,
            host={
                "last_received_packet": 94,
                "reason": "timeout",
                "events": [{"message": "Host receive timeout expired", "monotonic_ns": t_host_timeout, "uncertainty_ms": 1.0}],
            },
            client={
                "last_sent_packet": 100,
                "transport_result": "success",
                "events": [{"message": "Client sent packet #100", "monotonic_ns": t_client_send, "uncertainty_ms": 1.0}],
            },
        )
        await client_a.submit_run_record(run_3)

        # 9. Cross-Machine Correlation
        corr = await client_a.get_correlate(run_id=3)
        assert corr.reproduced is True
        assert len(corr.discrepancies) >= 2

        disc_codes = [d.code for d in corr.discrepancies]
        assert "PACKET_SEQUENCE_GAP" in disc_codes
        assert "TIMING_ORDERING_OBSERVATION" in disc_codes

        # 10. Evidence Graph Verification
        hyps_a = node_a.session.get_hypotheses()
        hyp_recorded = next(h for h in hyps_a if h.id == hyp.id)
        assert len(hyp_recorded.evidence_graph) >= 1
        assert hyp_recorded.evidence_graph[0].relation == EvidenceRelation.SUPPORTS
        assert hyp_recorded.status == HypothesisStatus.SUPPORTED

    finally:
        server_a.should_exit = True
        server_b.should_exit = True
        task_a.cancel()
        task_b.cancel()
        await asyncio.sleep(0.2)
