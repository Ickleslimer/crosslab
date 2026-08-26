"""
Tests for FEAR 3 Multi-Agent Diagnostic Scenario.
"""

import pytest
from crosslab.cases.fear3.scenario import run_fear3_investigation_demo
from crosslab.protocol.actions import HypothesisStatus, RunOutcome


@pytest.mark.asyncio
async def test_fear3_investigation_scenario() -> None:
    session = await run_fear3_investigation_demo(interactive=False)

    summary = session.get_session_summary()
    assert summary["session_id"] == "fear3-coop-investigation"
    assert summary["total_hypotheses"] == 1
    assert summary["total_experiments"] == 1
    assert summary["total_runs"] == 1
    assert summary["latest_reproduced_run_id"] == 14

    runs = session.get_runs()
    assert len(runs) == 1
    run_14 = runs[0]
    assert run_14.outcome == RunOutcome.REPRODUCED
    assert run_14.host["last_received_packet"] == 8831
    assert run_14.client["last_sent_packet"] == 8835

    hyps = session.get_hypotheses()
    assert len(hyps) == 1
    assert hyps[0].status == HypothesisStatus.SUPPORTED
    assert 14 in hyps[0].supporting_run_ids

    artifacts = session.get_artifacts()
    assert len(artifacts) == 1
    assert artifacts[0].filename == "fear3_keepalive_probe.patch"
