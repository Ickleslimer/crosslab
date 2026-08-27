"""
CrossLab Event Watcher and Auto-Wakeup Daemon.
Subscribes to the local A2A SSE event stream and emits alerts when remote peers interact,
triggering automatic agent wakeup in Antigravity.
"""

import asyncio
import json
import sys
import httpx


async def watch_events(node_url: str = "http://127.0.0.1:8765") -> None:
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

                            # Ignore self-pings or empty connected events
                            if ev_type == "connected":
                                continue

                            if ev_type == "message":
                                env = event.get("envelope", {})
                                sender = env.get("sender_id", "unknown")
                                if "host" not in sender:  # Incoming from peer!
                                    print(f"\n[A2A EVENT] Incoming message from peer '{sender}':", flush=True)
                                    print(f"  Action: {env.get('action')}", flush=True)
                                    print(f"  Text: {env.get('natural_language')}", flush=True)
                                    print(f"  Payload: {json.dumps(env.get('payload', {}))}", flush=True)

                            elif ev_type == "peer_joined":
                                peer = event.get("peer", {})
                                print(f"\n[A2A EVENT] Remote Peer Connected: {peer.get('agent_id')} ({peer.get('role')}) at {peer.get('endpoint_url')}", flush=True)

                            elif ev_type == "sync_signal":
                                sig = event.get("signal", {})
                                if "host" not in sig.get("sender_id", ""):
                                    print(f"\n[A2A EVENT] Run #{sig.get('run_id')} Sync Signal: phase='{sig.get('phase')}' from {sig.get('sender_id')}", flush=True)

                        except Exception as e:
                            pass
        except Exception as e:
            print(f"[Watcher] Connection dropped: {e}. Reconnecting in 3s...", flush=True)
            await asyncio.sleep(3.0)


if __name__ == "__main__":
    node_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
    asyncio.run(watch_events(node_url))
