"""
A2A Node and Transport Layer for CrossLab.
Provides HTTP/REST, Server-Sent Events (SSE), and P2P communication between agent nodes.
"""

import asyncio
from datetime import datetime
import json
import logging
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import httpx
import uvicorn

from crosslab.engine.session import InvestigationSession
from crosslab.protocol.actions import ActionType, AgentRole
from crosslab.protocol.models import (
    AgentPeer,
    ArtifactPayload,
    CorrelationResult,
    Experiment,
    HandshakeRequest,
    HandshakeResponse,
    Hypothesis,
    InstrumentationRequest,
    MessageEnvelope,
    Observation,
    RunRecord,
    SyncRunSignal,
    utc_now_iso,
)

logger = logging.getLogger("crosslab.transport")


class A2ANode:
    def __init__(
        self,
        agent_id: str,
        role: AgentRole,
        host: str = "127.0.0.1",
        port: int = 8000,
        session_id: str = "default",
        db_path: str = ":memory:",
        machine_name: Optional[str] = None,
    ):
        self.agent_id = agent_id
        self.role = role
        self.host = host
        self.port = port
        self.endpoint_url = f"http://{host}:{port}"
        self.session_id = session_id
        self.machine_name = machine_name or f"Machine-{agent_id}"
        self.session = InvestigationSession(session_id=session_id, db_path=db_path)

        self.self_peer = AgentPeer(
            agent_id=self.agent_id,
            role=self.role,
            endpoint_url=self.endpoint_url,
            machine_name=self.machine_name,
        )
        self.session.register_peer(self.self_peer)

        # Message queues for SSE subscribers
        self._subscribers: List[asyncio.Queue] = []
        # Handlers for incoming action events
        self._action_handlers: Dict[ActionType, List[Callable[[MessageEnvelope], Any]]] = {}

        self.app = FastAPI(title=f"CrossLab A2A Node - {agent_id}", version="0.1.0")
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

        @app.get("/health")
        async def health() -> Dict[str, str]:
            return {"status": "ok", "agent_id": self.agent_id, "role": self.role.value}

        @app.post("/v1/a2a/handshake", response_model=HandshakeResponse)
        async def handshake(req: HandshakeRequest) -> HandshakeResponse:
            peer = AgentPeer(
                agent_id=req.agent_id,
                role=req.role,
                endpoint_url=req.endpoint_url,
                machine_name=req.machine_name,
                capabilities=req.capabilities,
            )
            self.session.register_peer(peer)
            logger.info(f"[{self.agent_id}] Handshake from {req.agent_id} ({req.role.value}) at {req.endpoint_url}")

            # Notify local subscribers
            await self._broadcast_event({
                "event": "peer_joined",
                "peer": peer.model_dump(),
            })

            peers = self.session.get_peers()
            return HandshakeResponse(
                agent_id=self.agent_id,
                role=self.role,
                session_id=self.session_id,
                accepted=True,
                message=f"Welcome {req.agent_id} to session {self.session_id}",
                peers=peers,
            )

        @app.get("/v1/a2a/peers", response_model=List[AgentPeer])
        async def get_peers() -> List[AgentPeer]:
            return self.session.get_peers()

        @app.post("/v1/a2a/messages")
        async def receive_message(envelope: MessageEnvelope) -> Dict[str, Any]:
            self.session.record_message(envelope)
            logger.info(f"[{self.agent_id}] Ingested message from {envelope.sender_id}: {envelope.action.value}")

            # Trigger custom action handlers
            handlers = self._action_handlers.get(envelope.action, [])
            for handler in handlers:
                try:
                    res = handler(envelope)
                    if asyncio.iscoroutine(res):
                        asyncio.create_task(res)
                except Exception as e:
                    logger.error(f"Error executing action handler: {e}")

            # Broadcast to SSE streams
            await self._broadcast_event({
                "event": "message",
                "envelope": envelope.model_dump(),
            })
            return {"status": "received", "message_id": envelope.message_id}

        @app.get("/v1/a2a/messages", response_model=List[MessageEnvelope])
        async def get_messages(limit: int = 100) -> List[MessageEnvelope]:
            return self.session.get_messages(limit=limit)

        @app.get("/v1/a2a/events")
        async def sse_events(request: Request) -> StreamingResponse:
            """SSE stream for real-time agent notifications and reactive wakeup."""
            q: asyncio.Queue = asyncio.Queue()
            self._subscribers.append(q)

            async def event_generator() -> AsyncGenerator[str, None]:
                try:
                    # Initial connection ping
                    yield f"data: {json.dumps({'event': 'connected', 'agent_id': self.agent_id})}\n\n"
                    while True:
                        if await request.is_disconnected():
                            break
                        data = await q.get()
                        yield f"data: {json.dumps(data)}\n\n"
                finally:
                    if q in self._subscribers:
                        self._subscribers.remove(q)

            return StreamingResponse(event_generator(), media_type="text/event-stream")

        @app.post("/v1/a2a/runs/sync")
        async def sync_run(signal: SyncRunSignal) -> Dict[str, Any]:
            logger.info(f"[{self.agent_id}] Run {signal.run_id} sync signal: phase='{signal.phase}' from {signal.sender_id}")
            await self._broadcast_event({
                "event": "sync_signal",
                "signal": signal.model_dump(),
            })
            return {"status": "ok", "signal": signal.model_dump()}

        @app.post("/v1/a2a/runs")
        async def record_run(run: RunRecord) -> Dict[str, Any]:
            saved_run = self.session.record_run(run)
            await self._broadcast_event({
                "event": "run_recorded",
                "run": saved_run.model_dump(),
            })
            return {"status": "ok", "run": saved_run.model_dump()}

        @app.get("/v1/a2a/runs", response_model=List[RunRecord])
        async def get_runs() -> List[RunRecord]:
            return self.session.get_runs()

        @app.get("/v1/a2a/runs/{run_id}", response_model=Optional[RunRecord])
        async def get_run(run_id: int) -> Optional[RunRecord]:
            run = self.session.get_run(run_id)
            if not run:
                raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
            return run

        @app.get("/v1/a2a/correlate/{run_id}", response_model=CorrelationResult)
        async def correlate_run(run_id: int) -> CorrelationResult:
            run = self.session.get_run(run_id)
            if not run:
                raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
            return self.session.correlator.correlate_run(run)

        @app.post("/v1/a2a/hypotheses", response_model=Hypothesis)
        async def propose_hypothesis(hyp: Hypothesis) -> Hypothesis:
            self.session.storage.save_hypothesis(hyp)
            await self._broadcast_event({
                "event": "hypothesis_proposed",
                "hypothesis": hyp.model_dump(),
            })
            return hyp

        @app.get("/v1/a2a/hypotheses", response_model=List[Hypothesis])
        async def get_hypotheses() -> List[Hypothesis]:
            return self.session.get_hypotheses()

        @app.post("/v1/a2a/experiments", response_model=Experiment)
        async def propose_experiment(exp: Experiment) -> Experiment:
            self.session.storage.save_experiment(exp)
            await self._broadcast_event({
                "event": "experiment_proposed",
                "experiment": exp.model_dump(),
            })
            return exp

        @app.get("/v1/a2a/experiments", response_model=List[Experiment])
        async def get_experiments() -> List[Experiment]:
            return self.session.get_experiments()

        @app.post("/v1/a2a/observations", response_model=Observation)
        async def add_observation(obs: Observation) -> Observation:
            self.session.storage.save_observation(obs)
            await self._broadcast_event({
                "event": "observation_added",
                "observation": obs.model_dump(),
            })
            return obs

        @app.get("/v1/a2a/observations", response_model=List[Observation])
        async def get_observations(run_id: Optional[int] = None) -> List[Observation]:
            return self.session.get_observations(run_id=run_id)

        @app.post("/v1/a2a/artifacts", response_model=ArtifactPayload)
        async def share_artifact(art: ArtifactPayload) -> ArtifactPayload:
            self.session.storage.save_artifact(art)
            await self._broadcast_event({
                "event": "artifact_shared",
                "artifact": art.model_dump(),
            })
            return art

        @app.get("/v1/a2a/artifacts", response_model=List[ArtifactPayload])
        async def get_artifacts() -> List[ArtifactPayload]:
            return self.session.get_artifacts()

        @app.get("/v1/a2a/summary")
        async def get_summary() -> Dict[str, Any]:
            return self.session.get_session_summary()

    async def _broadcast_event(self, data: Dict[str, Any]) -> None:
        for q in list(self._subscribers):
            try:
                await q.put(data)
            except Exception:
                pass

    def on_action(self, action: ActionType, handler: Callable[[MessageEnvelope], Any]) -> None:
        if action not in self._action_handlers:
            self._action_handlers[action] = []
        self._action_handlers[action].append(handler)

    # --- Outbound P2P Communication ---

    async def connect_to_peer(self, peer_url: str) -> HandshakeResponse:
        """Initiates handshake with a remote peer node."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            req = HandshakeRequest(
                agent_id=self.agent_id,
                role=self.role,
                endpoint_url=self.endpoint_url,
                machine_name=self.machine_name,
                capabilities=self.self_peer.capabilities,
                session_id=self.session_id,
            )
            resp = await client.post(f"{peer_url.rstrip('/')}/v1/a2a/handshake", json=req.model_dump())
            resp.raise_for_status()
            data = resp.json()
            response = HandshakeResponse(**data)

            # Register all peers learned from remote
            for p in response.peers:
                if p.agent_id != self.agent_id:
                    self.session.register_peer(p)

            # Also register remote peer directly
            remote_peer = AgentPeer(
                agent_id=response.agent_id,
                role=response.role,
                endpoint_url=peer_url,
            )
            self.session.register_peer(remote_peer)
            return response

    async def send_message_to_peer(self, peer_url: str, envelope: MessageEnvelope) -> Dict[str, Any]:
        """Transmits a structured message envelope to a specific peer."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{peer_url.rstrip('/')}/v1/a2a/messages",
                json=envelope.model_dump(),
            )
            resp.raise_for_status()
            return resp.json()

    async def broadcast_message(self, envelope: MessageEnvelope) -> List[Dict[str, Any]]:
        """Broadcasts a message to all known registered peers (except self)."""
        self.session.record_message(envelope)
        peers = self.session.get_peers()
        results = []
        for peer in peers:
            if peer.agent_id == self.agent_id:
                continue
            try:
                res = await self.send_message_to_peer(peer.endpoint_url, envelope)
                results.append({"peer_id": peer.agent_id, "status": "sent", "response": res})
            except Exception as e:
                logger.warning(f"Failed to send message to peer {peer.agent_id} ({peer.endpoint_url}): {e}")
                results.append({"peer_id": peer.agent_id, "status": "error", "error": str(e)})
        return results

    async def send_sync_signal(self, peer_url: str, signal: SyncRunSignal) -> Dict[str, Any]:
        """Sends a synchronized run coordinate signal."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{peer_url.rstrip('/')}/v1/a2a/runs/sync",
                json=signal.model_dump(),
            )
            resp.raise_for_status()
            return resp.json()
