"""Tests for MCP install and doctor commands."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from crosslab.mcp.doctor import run_doctor
from crosslab.mcp.install import SUPPORTED_HARNESSES, merge_config, render_config
from crosslab.transport.topology import is_loopback_url
from crosslab.protocol.actions import AgentRole
from crosslab.transport.node import A2ANode


@pytest.mark.parametrize("harness", SUPPORTED_HARNESSES)
def test_render_config_all_harnesses(harness):
    config = render_config(harness, node_url="http://127.0.0.1:8765")
    assert config
    if harness == "antigravity":
        assert "crosslab" in config
    else:
        assert "mcpServers" in config
        assert "crosslab" in config["mcpServers"]


def test_render_config_with_project_root():
    config = render_config("cursor", node_url="http://127.0.0.1:8765", project_root="D:/crosslab")
    args = config["mcpServers"]["crosslab"]["args"]
    assert "--directory" in args
    assert "D:/crosslab" in args


def test_merge_config_cursor():
    existing = {"mcpServers": {"other": {"command": "echo"}}}
    rendered = render_config("cursor")
    merged = merge_config(existing, rendered, "cursor")
    assert "other" in merged["mcpServers"]
    assert "crosslab" in merged["mcpServers"]


def test_is_loopback_url():
    assert is_loopback_url("http://127.0.0.1:8765")
    assert is_loopback_url("http://localhost:8765")
    assert not is_loopback_url("http://192.168.1.10:8765")


@pytest.mark.asyncio
async def test_doctor_against_node(tmp_path):
    node = A2ANode(
        agent_id="test-host",
        role=AgentRole.HOST,
        db_path=str(tmp_path / "doctor.db"),
        session_id="test",
        host="127.0.0.1",
        port=8000,
        transcript_dir=str(tmp_path / "transcripts"),
    )
    transport = ASGITransport(app=node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        config = render_config("codex")
        parsed = json.loads(json.dumps(config))
        assert "mcpServers" in parsed

    results = await run_doctor(node_url="http://127.0.0.1:1")  # unreachable
    assert results["ok"] is False
    assert any(c["name"] == "node_health" and not c["ok"] for c in results["checks"])


@pytest.mark.asyncio
async def test_doctor_observability(tmp_path, monkeypatch):
    node = A2ANode(
        agent_id="test-host",
        role=AgentRole.HOST,
        db_path=str(tmp_path / "obs_doctor.db"),
        session_id="test",
        transcript_dir=str(tmp_path / "transcripts"),
    )
    transport = ASGITransport(app=node.app)
    asgi_client = AsyncClient(transport=transport, base_url="http://test")

    class _ClientCtx:
        async def __aenter__(self):
            return asgi_client

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr("crosslab.mcp.doctor.httpx.AsyncClient", lambda *a, **k: _ClientCtx())

    results = await run_doctor(
        node_url="http://test",
        observability=True,
    )
    check_names = {c["name"] for c in results["checks"]}
    assert "transcript_endpoint" in check_names
    assert "transcript_file" in check_names
    assert "observability_peer_count" in check_names
    assert any(c["name"] == "node_health" and c["ok"] for c in results["checks"])
