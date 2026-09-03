"""Tests for friction heatmap aggregation."""

import pytest
from httpx import ASGITransport, AsyncClient

from crosslab.engine.friction_heatmap import (
    build_heatmap_matrix,
    parse_harness,
    parse_taxonomies,
)
from crosslab.protocol.actions import AgentRole
from crosslab.transport.node import A2ANode


def test_parse_harness():
    assert parse_harness("Antigravity 28a6fca6 / schedule") == "antigravity"
    assert parse_harness("Codex 01a045f3 / user") == "codex"
    assert parse_harness("OpenCode ses_fba270") == "opencode"
    assert parse_harness("fear3-debug.md / Agent B") == "fear3-debug"


def test_parse_taxonomies():
    assert parse_taxonomies("T-TRANSPORT|T-OBS") == ["T-TRANSPORT", "T-OBS"]


def test_build_heatmap_matrix_fixture():
    rows = [
        {
            "id": "E001",
            "source": "Antigravity thread",
            "taxonomy": "T-AGENT-ATTN|T-TRANSPORT",
            "status": "open",
            "severity": "critical",
        },
        {
            "id": "E002",
            "source": "fear3-debug.md",
            "taxonomy": "T-TRANSPORT",
            "status": "fixed",
            "severity": "high",
        },
    ]
    matrix = build_heatmap_matrix(rows)
    assert matrix["total_events"] == 2
    assert "antigravity" in matrix["harnesses"]
    assert "fear3-debug" in matrix["harnesses"]
    assert matrix["counts"]["T-TRANSPORT"]["antigravity"] == 1
    assert matrix["counts"]["T-TRANSPORT"]["fear3-debug"] == 1


def test_build_heatmap_from_committed_csv():
    matrix = build_heatmap_matrix()
    assert matrix["total_events"] == 30
    assert len(matrix["taxonomies"]) > 0
    assert len(matrix["harnesses"]) > 0


@pytest.mark.asyncio
async def test_friction_heatmap_endpoint(tmp_path):
    node = A2ANode(
        agent_id="test-host",
        role=AgentRole.HOST,
        db_path=str(tmp_path / "heatmap.db"),
        session_id="test",
    )
    transport = ASGITransport(app=node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/v1/a2a/friction-heatmap")
        assert res.status_code == 200
        data = res.json()
        assert data["total_events"] == 30
        assert "matrix" in data
