"""
Harness-specific agent wakeup backends for CrossLab event watcher.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol, runtime_checkable

import httpx


@dataclass
class WakeupEvent:
    kind: str  # message | peer_joined | sync_signal
    sender_id: str
    action: str
    summary: str
    envelope: Dict[str, Any] = field(default_factory=dict)
    message_id: Optional[str] = None


@runtime_checkable
class WakeupBackend(Protocol):
    async def wake(self, event: WakeupEvent) -> None: ...


class StdoutBackend:
    async def wake(self, event: WakeupEvent) -> None:
        payload = {
            "kind": event.kind,
            "sender_id": event.sender_id,
            "action": event.action,
            "summary": event.summary,
            "message_id": event.message_id,
        }
        print(f"[CROSSLAB_WAKEUP] {json.dumps(payload)}", flush=True)


class FileBackend:
    def __init__(self, path: Optional[str] = None) -> None:
        default = os.path.join(tempfile.gettempdir(), "crosslab_wakeup.json")
        self.path = path or os.environ.get("CROSSLAB_WAKEUP_FILE", default)

    async def wake(self, event: WakeupEvent) -> None:
        payload = {
            "timestamp": time.time(),
            "kind": event.kind,
            "sender_id": event.sender_id,
            "action": event.action,
            "summary": event.summary,
            "envelope": event.envelope,
            "message_id": event.message_id,
        }
        tmp_path = f"{self.path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_path, self.path)


class WebhookBackend:
    def __init__(self, url: Optional[str] = None) -> None:
        self.url = url or os.environ.get("CROSSLAB_WAKEUP_WEBHOOK", "")
        if not self.url:
            raise ValueError("Webhook URL required (pass url or set CROSSLAB_WAKEUP_WEBHOOK)")

    async def wake(self, event: WakeupEvent) -> None:
        payload = {
            "kind": event.kind,
            "sender_id": event.sender_id,
            "action": event.action,
            "summary": event.summary,
            "envelope": event.envelope,
            "message_id": event.message_id,
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(self.url, json=payload)


class AntigravityBackend:
    """File + stdout prompt formatted for Antigravity schedule hooks."""

    def __init__(self, wake_file: Optional[str] = None) -> None:
        self._file = FileBackend(wake_file)
        self._stdout = StdoutBackend()

    async def wake(self, event: WakeupEvent) -> None:
        prompt = (
            f"Check CrossLab: {event.summary}. "
            "Use crosslab_wait_for_message if you need to block for the next peer reply."
        )
        ag_event = WakeupEvent(
            kind=event.kind,
            sender_id=event.sender_id,
            action=event.action,
            summary=prompt,
            envelope=event.envelope,
            message_id=event.message_id,
        )
        await self._file.wake(ag_event)
        await self._stdout.wake(ag_event)


def create_wakeup_backend(
    mode: str,
    *,
    webhook_url: Optional[str] = None,
    wake_file: Optional[str] = None,
) -> WakeupBackend:
    mode = mode.lower()
    if mode == "auto":
        harness = os.environ.get("CROSSLAB_HARNESS", "stdout").lower()
        mode = harness if harness in ("antigravity", "opencode", "codex", "file", "webhook") else "stdout"
    if mode == "stdout":
        return StdoutBackend()
    if mode in ("file", "opencode"):
        return FileBackend(wake_file)
    if mode == "webhook" or mode == "codex":
        return WebhookBackend(webhook_url)
    if mode == "antigravity":
        return AntigravityBackend(wake_file)
    raise ValueError(f"Unknown wakeup mode: {mode}")
