"""
CrossLab Event Watcher and Auto-Wakeup Daemon.
Subscribes to the local A2A SSE event stream and triggers harness-specific wakeup backends.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Optional, Set

import httpx

from crosslab.agent.wakeup import (
    StdoutBackend,
    WakeupBackend,
    WakeupEvent,
    create_wakeup_backend,
)


def _is_peer_sender(sender_id: str, local_agent_id: str, local_role_hint: str) -> bool:
    """Return True if event originated from a remote peer (not self)."""
    if sender_id == local_agent_id:
        return False
    sid = sender_id.lower()
    role = local_role_hint.lower()
    if role == "host" and "host" in sid and local_agent_id.lower() in sid:
        return False
    if role == "client" and "client" in sid and local_agent_id.lower() in sid:
        return False
    return True


async def watch_events(
    node_url: str = "http://127.0.0.1:8765",
    *,
    backend: Optional[WakeupBackend] = None,
    agent_id: str = "agent-local",
    local_role_hint: str = "host",
    verbose: bool = False,
    dedupe_window_s: float = 5.0,
) -> None:
    wake_backend = backend or StdoutBackend()
    recent_wakes: dict[str, float] = {}
    print(f"[Watcher] Subscribed to SSE stream at {node_url}/v1/a2a/events", flush=True)

    while True:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", f"{node_url}/v1/a2a/events") as response:
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        try:
                            event = json.loads(data_str)
                            ev_type = event.get("event")

                            if ev_type == "connected":
                                continue

                            if ev_type == "message":
                                env = event.get("envelope", {})
                                sender = env.get("sender_id", "unknown")
                                origin = env.get("origin_sender_id") or sender
                                if not _is_peer_sender(origin, agent_id, local_role_hint):
                                    continue

                                msg_id = env.get("message_id")
                                now = time.time()
                                if msg_id:
                                    last = recent_wakes.get(msg_id, 0)
                                    if now - last < dedupe_window_s:
                                        continue
                                    recent_wakes[msg_id] = now

                                action = env.get("action", "chat")
                                text = (env.get("natural_language") or "")[:120]
                                summary = f"Message from {sender} ({action}): {text}"

                                if verbose:
                                    print(f"\n[A2A EVENT] Incoming message from peer '{sender}':", flush=True)
                                    print(f"  Action: {action}", flush=True)
                                    print(f"  Text: {env.get('natural_language')}", flush=True)

                                await wake_backend.wake(WakeupEvent(
                                    kind="message",
                                    sender_id=sender,
                                    action=action,
                                    summary=summary,
                                    envelope=event,
                                    message_id=msg_id,
                                ))

                            elif ev_type == "peer_joined":
                                peer = event.get("peer", {})
                                summary = f"Peer connected: {peer.get('agent_id')} ({peer.get('role')})"
                                if verbose:
                                    print(f"\n[A2A EVENT] Remote Peer Connected: {peer.get('agent_id')}", flush=True)
                                await wake_backend.wake(WakeupEvent(
                                    kind="peer_joined",
                                    sender_id=peer.get("agent_id", "unknown"),
                                    action="peer_joined",
                                    summary=summary,
                                    envelope=event,
                                ))

                            elif ev_type == "sync_signal":
                                sig = event.get("signal", {})
                                sender = sig.get("sender_id", "unknown")
                                if not _is_peer_sender(sender, agent_id, local_role_hint):
                                    continue
                                summary = (
                                    f"Run #{sig.get('run_id')} sync signal phase='{sig.get('phase')}' "
                                    f"from {sender}"
                                )
                                if verbose:
                                    print(f"\n[A2A EVENT] {summary}", flush=True)
                                await wake_backend.wake(WakeupEvent(
                                    kind="sync_signal",
                                    sender_id=sender,
                                    action=sig.get("phase", "sync"),
                                    summary=summary,
                                    envelope=event,
                                ))

                        except Exception:
                            pass
        except Exception as e:
            print(f"[Watcher] Connection dropped: {e}. Reconnecting in 3s...", flush=True)
            await asyncio.sleep(3.0)


if __name__ == "__main__":
    node_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
    asyncio.run(watch_events(node_url))
