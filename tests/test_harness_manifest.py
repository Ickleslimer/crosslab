"""Tests for harness thread manifest API."""

import pytest
from httpx import ASGITransport, AsyncClient

from crosslab.engine.manifest import HarnessLinks, load_harness_links, save_harness_links
from crosslab.protocol.actions import AgentRole
from crosslab.transport.node import A2ANode


@pytest.mark.asyncio
async def test_manifest_round_trip(tmp_path):
    data_dir = str(tmp_path / "session-data")
    links = HarnessLinks(antigravity="28a6fca6-test", codex="01a045f3-test")
    save_harness_links(data_dir, links)
    loaded = load_harness_links(data_dir)
    assert loaded.antigravity == "28a6fca6-test"
    assert loaded.codex == "01a045f3-test"


@pytest.mark.asyncio
async def test_manifest_api(tmp_path):
    db_path = str(tmp_path / "manifest.db")
    node = A2ANode(
        agent_id="test-host",
        role=AgentRole.HOST,
        db_path=db_path,
        session_id="test-session",
    )
    transport = ASGITransport(app=node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        put_res = await client.put(
            "/v1/a2a/session/manifest",
            json={"antigravity": "ag-1", "opencode": "oc-1"},
        )
        assert put_res.status_code == 200
        get_res = await client.get("/v1/a2a/session/manifest")
        data = get_res.json()
        assert data["antigravity"] == "ag-1"
        assert data["opencode"] == "oc-1"
