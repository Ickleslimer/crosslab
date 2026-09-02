"""
Tests for harness wakeup backends and watcher integration.
"""

import json
import os
from unittest.mock import AsyncMock, patch

import pytest

from crosslab.agent.wakeup import (
    AntigravityBackend,
    FileBackend,
    StdoutBackend,
    WakeupEvent,
    WebhookBackend,
    create_wakeup_backend,
)
from crosslab.agent.watcher import _is_peer_sender


def test_is_peer_sender_excludes_self():
    assert _is_peer_sender("agent-host", "agent-host", "host") is False
    assert _is_peer_sender("peer-client", "agent-host", "host") is True


@pytest.mark.asyncio
async def test_file_backend_writes_json(tmp_path):
    path = str(tmp_path / "wakeup.json")
    backend = FileBackend(path)
    event = WakeupEvent(
        kind="message",
        sender_id="peer-client",
        action="chat",
        summary="Hello from peer",
        message_id="msg_123",
    )
    await backend.wake(event)

    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["sender_id"] == "peer-client"
    assert data["summary"] == "Hello from peer"
    assert data["message_id"] == "msg_123"


@pytest.mark.asyncio
async def test_stdout_backend(capsys):
    backend = StdoutBackend()
    await backend.wake(WakeupEvent(
        kind="message",
        sender_id="peer-client",
        action="chat",
        summary="Test wakeup",
    ))
    captured = capsys.readouterr()
    assert "[CROSSLAB_WAKEUP]" in captured.out
    assert "peer-client" in captured.out


@pytest.mark.asyncio
async def test_webhook_backend_posts():
    backend = WebhookBackend("http://example.com/hook")
    mock_response = AsyncMock()
    mock_response.raise_for_status = lambda: None

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        await backend.wake(WakeupEvent(
            kind="message",
            sender_id="peer-client",
            action="chat",
            summary="Webhook test",
        ))

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[0][0] == "http://example.com/hook"
        assert call_kwargs[1]["json"]["sender_id"] == "peer-client"


@pytest.mark.asyncio
async def test_antigravity_backend_writes_file(tmp_path):
    path = str(tmp_path / "ag_wakeup.json")
    backend = AntigravityBackend(path)
    await backend.wake(WakeupEvent(
        kind="message",
        sender_id="peer-client",
        action="sync_ready",
        summary="READY Run 14",
    ))
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert "crosslab_wait_for_message" in data["summary"]


def test_create_wakeup_backend_stdout():
    backend = create_wakeup_backend("stdout")
    assert isinstance(backend, StdoutBackend)


def test_create_wakeup_backend_auto_env(monkeypatch):
    monkeypatch.setenv("CROSSLAB_HARNESS", "antigravity")
    backend = create_wakeup_backend("auto")
    assert isinstance(backend, AntigravityBackend)


def test_cli_watch_parser():
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    watch = sub.add_parser("watch")
    watch.add_argument("--wake", default="stdout")
    args = parser.parse_args(["watch", "--wake", "file"])
    assert args.command == "watch"
    assert args.wake == "file"
