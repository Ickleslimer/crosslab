"""
Pure-Python Central Relay Hub for CrossLab.
Bridges distributed nodes across NATs and firewalls (e.g. UK to North America)
without requiring third-party VPNs or port forwarding.
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
import uvicorn

from crosslab.protocol.models import AgentPeer, MessageEnvelope, utc_now_iso

logger = logging.getLogger("crosslab.relay")


class CrossLabRelay:
    """
    Central hub that routes A2A messages and SSE events between NATed machines.
    """

    def __init__(self, port: int = 8080):
        self.port = port
        self.app = FastAPI(title="CrossLab P2P Relay Hub", version="0.2.0")
        self._sessions: Dict[str, Dict[str, AgentPeer]] = {}
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._setup_middleware()
        self._setup_routes()

    def _setup_middleware(self) -> None:
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _setup_routes(self) -> None:
        app = self.app

        @app.get("/")
        async def root() -> HTMLResponse:
            total_sessions = len(self._sessions)
            total_nodes = sum(len(nodes) for nodes in self._sessions.values())
            html = f"""
            <html>
                <body style="background:#0b0f19;color:#e2e8f0;font-family:monospace;padding:2rem;">
                    <h1>CrossLab P2P Relay Hub</h1>
                    <p>Status: <span style="color:#10b981;">ONLINE</span></p>
                    <p>Active Sessions: <strong>{total_sessions}</strong> | Registered Nodes: <strong>{total_nodes}</strong></p>
                </body>
            </html>
            """
            return HTMLResponse(content=html)

        @app.get("/health")
        async def health() -> Dict[str, Any]:
            return {"status": "ok", "service": "crosslab-relay", "sessions": len(self._sessions)}

        @app.post("/relay/register")
        async def register_node(peer: AgentPeer, session_id: str = "default") -> Dict[str, Any]:
            if session_id not in self._sessions:
                self._sessions[session_id] = {}
                self._subscribers[session_id] = []

            self._sessions[session_id][peer.agent_id] = peer
            logger.info(f"[Relay] Registered node {peer.agent_id} in session {session_id}")

            # Broadcast peer joined to all subscribers in this session
            await self._broadcast_to_session(session_id, {
                "event": "peer_joined",
                "peer": peer.model_dump(),
            })

            peers_list = list(self._sessions[session_id].values())
            return {"status": "registered", "session_id": session_id, "peers": [p.model_dump() for p in peers_list]}

        @app.post("/relay/messages")
        async def relay_message(envelope: MessageEnvelope) -> Dict[str, Any]:
            session_id = envelope.session_id
            logger.info(f"[Relay] Routing message {envelope.message_id} from {envelope.sender_id} in session {session_id}")

            await self._broadcast_to_session(session_id, {
                "event": "message",
                "envelope": envelope.model_dump(),
            })
            return {"status": "relayed", "message_id": envelope.message_id}

        @app.get("/relay/events")
        async def stream_events(request: Request, session_id: str = "default") -> StreamingResponse:
            if session_id not in self._subscribers:
                self._subscribers[session_id] = []

            q: asyncio.Queue = asyncio.Queue()
            self._subscribers[session_id].append(q)

            async def event_generator() -> AsyncGenerator[str, None]:
                try:
                    yield f"data: {json.dumps({'event': 'connected', 'session_id': session_id})}\n\n"
                    while True:
                        if await request.is_disconnected():
                            break
                        data = await q.get()
                        yield f"data: {json.dumps(data)}\n\n"
                finally:
                    if session_id in self._subscribers and q in self._subscribers[session_id]:
                        self._subscribers[session_id].remove(q)

            return StreamingResponse(event_generator(), media_type="text/event-stream")

    async def _broadcast_to_session(self, session_id: str, data: Dict[str, Any]) -> None:
        subscribers = self._subscribers.get(session_id, [])
        for q in list(subscribers):
            try:
                await q.put(data)
            except Exception:
                pass


def run_relay(port: int = 8080, host: str = "0.0.0.0") -> None:
    relay = CrossLabRelay(port=port)
    print(f"[CrossLab Relay] Starting on http://{host}:{port}")
    uvicorn.run(relay.app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_relay()
