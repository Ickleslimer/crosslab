"""
A2A Node and Transport Layer for CrossLab.
Provides HTTP/REST, A2A Agent Card Discovery, Server-Sent Events (SSE),
bidirectional network relay, clock offset measurement, and P2P synchronization.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import json
import logging
import os
import re
import time
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
import httpx

from crosslab.engine.session import InvestigationSession
from crosslab.engine.barrier import BarrierCoordinator, BarrierState
from crosslab.engine.friction_heatmap import build_heatmap_matrix
from crosslab.engine.manifest import HarnessLinks
from crosslab.engine.agent_profile import AgentProfile, peer_profile_from_metadata
from crosslab.engine.observability import build_observability_report
from crosslab.engine.probe_validation import validate_instrumentation_payload
from crosslab.engine.runbook import RunbookCoordinator, RunbookState
from crosslab.protocol.actions import ActionType, AgentRole
from crosslab.protocol.models import (
    AgentCard,
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
    PingRequest,
    PongResponse,
    ReconcileRequest,
    ReconcileResponse,
    RunRecord,
    SyncRunSignal,
    get_monotonic_ns,
    get_wall_time_ns,
    utc_now_iso,
)
from crosslab.transport.dashboard import DASHBOARD_HTML
from crosslab.transport.message_wait import MessageWaitRegistry, MessageWaiter
from crosslab.transport.topology import is_loopback_url, topology_warning

logger = logging.getLogger("crosslab.transport")


class InstrumentationRejected(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class A2ANode:
    def __init__(
        self,
        agent_id: str,
        role: AgentRole = AgentRole.HOST,
        host: str = "127.0.0.1",
        port: int = 8000,
        session_id: str = "default",
        db_path: str = ":memory:",
        machine_name: Optional[str] = None,
        initial_peer_url: Optional[str] = None,
        transcript_dir: Optional[str] = None,
    ):
        self.agent_id = agent_id
        self.role = role
        self.host = host
        self.port = port
        self.endpoint_url = f"http://{host}:{port}"
        self.session_id = session_id
        self.machine_name = machine_name or f"Machine-{agent_id}"
        self.initial_peer_url = initial_peer_url
        self.session = InvestigationSession(
            session_id=session_id,
            db_path=db_path,
            transcript_dir=transcript_dir,
        )

        self.agent_card = AgentCard(
            name=f"CrossLab Node ({self.agent_id})",
            description=f"Empirical collaboration agent operating in role '{self.role.value}'",
            version="0.2.0",
            url=self.endpoint_url,
            role=self.role,
            machine_name=self.machine_name,
            endpoints={
                "agent_card": f"{self.endpoint_url}/.well-known/agent-card.json",
                "messages": f"{self.endpoint_url}/v1/a2a/messages",
                "events": f"{self.endpoint_url}/v1/a2a/events",
                "handshake": f"{self.endpoint_url}/v1/a2a/handshake",
                "runs_sync": f"{self.endpoint_url}/v1/a2a/runs/sync",
                "transcript": f"{self.endpoint_url}/v1/a2a/transcript",
            },
        )

        self.self_peer = AgentPeer(
            agent_id=self.agent_id,
            role=self.role,
            endpoint_url=self.endpoint_url,
            machine_name=self.machine_name,
            capabilities=self.agent_card.capabilities,
        )

        self.agent_profile = self.session.get_agent_profile()
        self._apply_profile_to_self()
        self.session.register_peer(self.self_peer)
        self.session.prune_remote_peers(self.agent_id)

        self.strict_instrumentation = os.environ.get("CROSSLAB_STRICT_INSTRUMENTATION", "").lower() in (
            "1", "true", "yes",
        )
        self.barrier = BarrierCoordinator(
            self.session,
            strict_instrumentation=self.strict_instrumentation,
            local_agent_id=self.agent_id,
        )

        # SSE Subscribers
        self._subscribers: List[asyncio.Queue] = []
        # Long-poll message waiters
        self._message_waiters = MessageWaitRegistry()
        # Action Event Handlers
        self._action_handlers: Dict[ActionType, List[Callable[[MessageEnvelope], Any]]] = {}
        # Seen message IDs for deduplication & echo loop prevention
        self._seen_message_ids: set = {
            message.message_id for message in self.session.get_messages(limit=None)
        }
        # Consecutive heartbeat misses before pruning a remote peer
        self._peer_miss_counts: Dict[str, int] = {}
        # Cached RTT/skew per peer agent_id from heartbeat
        self._peer_metrics: Dict[str, Dict[str, float]] = {}
        # Background tasks
        self._bg_tasks: List[asyncio.Task] = []

        # Setup FastAPI with Lifespan
        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
            # Startup phase in running event loop
            if self.initial_peer_url:
                task = asyncio.create_task(self._connect_peer_loop(self.initial_peer_url))
                self._bg_tasks.append(task)

            # Start periodic heartbeat & clock sync
            ping_task = asyncio.create_task(self._periodic_heartbeat_loop())
            self._bg_tasks.append(ping_task)

            yield

            # Shutdown phase
            for t in self._bg_tasks:
                t.cancel()

        self.app = FastAPI(
            title=f"CrossLab A2A Node - {agent_id}",
            version="0.2.0",
            lifespan=lifespan,
        )
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

        @app.get("/", response_class=HTMLResponse)
        @app.get("/dashboard", response_class=HTMLResponse)
        async def dashboard_page() -> HTMLResponse:
            return HTMLResponse(content=DASHBOARD_HTML)

        @app.get("/health")
        async def health() -> Dict[str, Any]:
            peer_health = []
            for peer in self.session.get_peers():
                if peer.agent_id == self.agent_id:
                    continue
                metrics = self._peer_metrics.get(peer.agent_id, {})
                warn = topology_warning(self.machine_name, peer)
                entry = {
                    "agent_id": peer.agent_id,
                    "endpoint_url": peer.endpoint_url,
                    "machine_name": peer.machine_name,
                    "rtt_ms": metrics.get("rtt_ms"),
                    "clock_skew_ms": metrics.get("offset_ms"),
                    "topology_warning": warn,
                }
                entry.update(self._peer_profile_fields(peer))
                peer_health.append(entry)
            obs = build_observability_report(self.session, self.agent_id)
            observability_ok = obs.get("ok", True)
            if self.role in (AgentRole.HOST, AgentRole.CLIENT) and obs.get("peer_count", 0) == 0:
                observability_ok = False
            return {
                "status": "ok",
                "agent_id": self.agent_id,
                "role": self.role.value,
                "session_id": self.session_id,
                "port": self.port,
                "version": "0.2.0",
                "advertised_url": self.endpoint_url,
                "advertised_reachable_externally": not is_loopback_url(self.endpoint_url),
                "agent_profile": self.agent_profile.model_dump(),
                "peers": peer_health,
                "observability_ok": observability_ok,
                "last_message_age_s": obs.get("last_message_age_s"),
                "message_count": obs.get("message_count"),
            }

        @app.get("/v1/a2a/observability")
        async def get_observability() -> Dict[str, Any]:
            return build_observability_report(self.session, self.agent_id)

        @app.get("/v1/a2a/friction-heatmap")
        async def get_friction_heatmap() -> Dict[str, Any]:
            return build_heatmap_matrix()

        # --- A2A 1.0 Agent Card Discovery ---

        @app.get("/.well-known/agent-card.json", response_model=AgentCard)
        @app.get("/agent-card.json", response_model=AgentCard)
        async def get_agent_card() -> AgentCard:
            return self.agent_card

        # --- Discovery & Handshake ---

        @app.post("/v1/a2a/handshake", response_model=HandshakeResponse)
        async def handshake(req: HandshakeRequest) -> HandshakeResponse:
            peer_metadata: Dict[str, Any] = {}
            if req.agent_card and req.agent_card.metadata:
                peer_metadata = dict(req.agent_card.metadata)
            peer = AgentPeer(
                agent_id=req.agent_id,
                role=req.role,
                endpoint_url=req.endpoint_url,
                machine_name=req.machine_name,
                capabilities=req.capabilities,
                metadata=peer_metadata,
            )
            self.session.register_peer(peer)
            self._peer_miss_counts[req.agent_id] = 0
            logger.info(f"[{self.agent_id}] Handshake accepted from {req.agent_id} ({req.role.value}) at {req.endpoint_url}")

            warnings: List[str] = []
            topo_warn = topology_warning(self.machine_name, peer)
            if topo_warn:
                warnings.append(topo_warn)
                await self._broadcast_event({
                    "event": "topology_warning",
                    "peer_id": req.agent_id,
                    "warning": topo_warn,
                })

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
                warnings=warnings,
                peers=peers,
                agent_card=self.agent_card,
            )

        @app.get("/v1/a2a/peers", response_model=List[AgentPeer])
        async def get_peers() -> List[AgentPeer]:
            return [
                peer for peer in self.session.get_peers()
                if peer.agent_id != self.agent_id
            ]

        @app.get("/v1/a2a/peers/detailed")
        async def get_peers_detailed() -> List[Dict[str, Any]]:
            result = []
            for peer in self.session.get_peers():
                if peer.agent_id == self.agent_id:
                    continue
                metrics = self._peer_metrics.get(peer.agent_id, {})
                data = peer.model_dump()
                data["rtt_ms"] = metrics.get("rtt_ms")
                data["clock_skew_ms"] = metrics.get("offset_ms")
                data["topology_warning"] = topology_warning(self.machine_name, peer)
                data.update(self._peer_profile_fields(peer))
                result.append(data)
            return result

        # --- Clock Sync & Ping/Pong ---

        @app.post("/v1/a2a/ping", response_model=PongResponse)
        async def ping(req: PingRequest) -> PongResponse:
            t1_mono = get_monotonic_ns()
            t1_wall = get_wall_time_ns()
            t2_mono = get_monotonic_ns()
            t2_wall = get_wall_time_ns()
            return PongResponse(
                agent_id=self.agent_id,
                t0_send_mono_ns=req.t0_send_mono_ns,
                t0_send_wall_ns=req.t0_send_wall_ns,
                t1_recv_mono_ns=t1_mono,
                t1_recv_wall_ns=t1_wall,
                t2_send_mono_ns=t2_mono,
                t2_send_wall_ns=t2_wall,
            )

        # --- Synchronization & Reconciliation ---

        @app.post("/v1/a2a/sync/reconcile", response_model=ReconcileResponse)
        async def reconcile(req: ReconcileRequest) -> ReconcileResponse:
            known_msgs = set(req.known_message_ids)
            known_hyps = set(req.known_hypothesis_ids)
            known_exps = set(req.known_experiment_ids)
            known_runs = set(req.known_run_ids)

            all_msgs = self.session.get_messages(limit=None)
            all_hyps = self.session.get_hypotheses()
            all_exps = self.session.get_experiments()
            all_runs = self.session.get_runs()

            missing_msgs = [m for m in all_msgs if m.message_id not in known_msgs]
            missing_hyps = [h for h in all_hyps if h.id not in known_hyps]
            missing_exps = [e for e in all_exps if e.id not in known_exps]
            missing_runs = [r for r in all_runs if r.run_id not in known_runs]

            return ReconcileResponse(
                agent_id=self.agent_id,
                session_id=self.session_id,
                missing_messages=missing_msgs,
                missing_hypotheses=missing_hyps,
                missing_experiments=missing_exps,
                missing_runs=missing_runs,
            )

        # --- Messaging & Network Relay ---

        @app.post("/v1/a2a/messages")
        async def receive_message(envelope: MessageEnvelope) -> Dict[str, Any]:
            try:
                ingested, ready_meta = await self._ingest_message(envelope)
            except InstrumentationRejected as exc:
                raise HTTPException(
                    status_code=422,
                    detail={"status": "rejected", "reason": exc.reason},
                ) from exc
            if not ingested:
                response: Dict[str, Any] = {
                    "status": "already_processed",
                    "message_id": envelope.message_id,
                }
                if ready_meta is None:
                    ready_meta = self.barrier.ready_response_for_envelope(envelope)
                if ready_meta:
                    response.update(ready_meta)
                return response

            # Relay to other remote peers across network if relay requested
            if envelope.relay and envelope.hops < 5:
                relayed_envelope = envelope.model_copy(deep=True)
                relayed_envelope.hops += 1
                relayed_envelope.sender_id = self.agent_id  # forwarder
                asyncio.create_task(self._relay_to_peers(relayed_envelope))

            response = {"status": "received", "message_id": envelope.message_id}
            if ready_meta:
                response.update(ready_meta)
            return response

        @app.get("/v1/a2a/messages", response_model=List[MessageEnvelope])
        async def get_messages(
            limit: int = 100,
            since_id: Optional[str] = None,
            actions: Optional[str] = None,
        ) -> List[MessageEnvelope]:
            action_list = [a.strip() for a in actions.split(",") if a.strip()] if actions else None
            if self.initial_peer_url and self.role != AgentRole.HOST:
                try:
                    async with httpx.AsyncClient(timeout=3.0) as client:
                        params: Dict[str, Any] = {"limit": limit}
                        if since_id:
                            params["since_id"] = since_id
                        if actions:
                            params["actions"] = actions
                        resp = await client.get(
                            f"{self.initial_peer_url.rstrip('/')}/v1/a2a/messages",
                            params=params,
                        )
                        if resp.status_code == 200:
                            for m_data in resp.json():
                                env = MessageEnvelope(**m_data)
                                await self._ingest_message(env)
                except Exception:
                    pass
            return self.session.get_messages(limit=limit, since_id=since_id, actions=action_list)

        @app.get("/v1/a2a/messages/wait")
        async def wait_for_message(
            since_id: Optional[str] = None,
            timeout_s: float = 60.0,
            actions: Optional[str] = None,
            exclude_self: bool = True,
        ) -> Dict[str, Any]:
            action_list = {a.strip() for a in actions.split(",") if a.strip()} if actions else None
            ordered = self.session.get_messages(limit=None)
            exclude_id = self.agent_id if exclude_self else None

            for msg in ordered:
                from crosslab.transport.message_wait import message_matches_filters
                if message_matches_filters(
                    msg,
                    since_id=since_id,
                    actions=action_list,
                    exclude_agent_id=exclude_id,
                    ordered_messages=ordered,
                ):
                    return {"status": "ok", "message": msg.model_dump()}

            loop = asyncio.get_event_loop()
            future: asyncio.Future = loop.create_future()
            waiter = MessageWaiter(
                since_id=since_id,
                actions=action_list,
                exclude_agent_id=exclude_id,
                future=future,
                ordered_messages=ordered,
            )
            self._message_waiters.register(waiter)
            try:
                msg = await asyncio.wait_for(future, timeout=timeout_s)
                return {"status": "ok", "message": msg.model_dump()}
            except asyncio.TimeoutError:
                return {"status": "timeout"}
            finally:
                self._message_waiters.unregister(waiter)

        @app.get("/v1/a2a/events")
        async def sse_events(request: Request) -> StreamingResponse:
            q: asyncio.Queue = asyncio.Queue()
            self._subscribers.append(q)

            async def event_generator() -> AsyncGenerator[str, None]:
                try:
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

        # --- Run Coordination & Barrier Sync ---

        @app.post("/v1/a2a/runs/sync")
        async def sync_run(signal: SyncRunSignal) -> Dict[str, Any]:
            signal.session_id = self.session_id
            logger.info(f"[{self.agent_id}] Run {signal.run_id} sync signal: phase='{signal.phase}' from {signal.sender_id}")
            ready_meta = self.barrier.on_sync_signal(signal)
            await self._broadcast_event({
                "event": "sync_signal",
                "signal": signal.model_dump(),
            })
            response: Dict[str, Any] = {"status": "ok", "signal": signal.model_dump()}
            if ready_meta:
                response.update(ready_meta)
            return response

        @app.post("/v1/a2a/runs")
        async def record_run(run: RunRecord) -> Dict[str, Any]:
            run.session_id = self.session_id
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

        @app.get("/v1/a2a/runs/{run_id}/barrier", response_model=BarrierState)
        async def get_run_barrier(run_id: int) -> BarrierState:
            try:
                return self.barrier.get_barrier_state(run_id)
            except KeyError:
                raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        @app.get("/v1/a2a/correlate/{run_id}", response_model=CorrelationResult)
        async def correlate_run(run_id: int) -> CorrelationResult:
            run = self.session.get_run(run_id)
            if not run:
                raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
            return self.session.correlator.correlate_run(run)

        # --- Hypotheses & Evidence Graph ---

        @app.post("/v1/a2a/hypotheses", response_model=Hypothesis)
        async def propose_hypothesis(hyp: Hypothesis) -> Hypothesis:
            hyp.session_id = self.session_id
            self.session.storage.save_hypothesis(hyp)
            await self._broadcast_event({
                "event": "hypothesis_proposed",
                "hypothesis": hyp.model_dump(),
            })
            return hyp

        @app.get("/v1/a2a/hypotheses", response_model=List[Hypothesis])
        async def get_hypotheses() -> List[Hypothesis]:
            if self.initial_peer_url and self.role != AgentRole.HOST:
                try:
                    async with httpx.AsyncClient(timeout=3.0) as client:
                        resp = await client.get(f"{self.initial_peer_url.rstrip('/')}/v1/a2a/hypotheses")
                        if resp.status_code == 200:
                            for h_data in resp.json():
                                hyp = Hypothesis(**h_data)
                                self.session.storage.save_hypothesis(hyp)
                except Exception:
                    pass
            return self.session.get_hypotheses()

        @app.post("/v1/a2a/experiments", response_model=Experiment)
        async def propose_experiment(exp: Experiment) -> Experiment:
            exp.session_id = self.session_id
            self.session.storage.save_experiment(exp)
            await self._broadcast_event({
                "event": "experiment_proposed",
                "experiment": exp.model_dump(),
            })
            return exp

        @app.get("/v1/a2a/experiments", response_model=List[Experiment])
        async def get_experiments() -> List[Experiment]:
            if self.initial_peer_url and self.role != AgentRole.HOST:
                try:
                    async with httpx.AsyncClient(timeout=3.0) as client:
                        resp = await client.get(f"{self.initial_peer_url.rstrip('/')}/v1/a2a/experiments")
                        if resp.status_code == 200:
                            for e_data in resp.json():
                                exp = Experiment(**e_data)
                                self.session.storage.save_experiment(exp)
                except Exception:
                    pass
            return self.session.get_experiments()

        @app.post("/v1/a2a/observations", response_model=Observation)
        async def add_observation(obs: Observation) -> Observation:
            obs.session_id = self.session_id
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
            art.session_id = self.session_id
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

        @app.get("/v1/a2a/transcript")
        async def get_transcript() -> HTMLResponse:
            md = self.session.export_transcript_markdown()
            return HTMLResponse(content=md, media_type="text/markdown; charset=utf-8")

        @app.get("/v1/a2a/session/manifest", response_model=HarnessLinks)
        async def get_session_manifest() -> HarnessLinks:
            return self.session.get_harness_links()

        @app.put("/v1/a2a/session/manifest", response_model=HarnessLinks)
        async def put_session_manifest(links: HarnessLinks) -> HarnessLinks:
            self.session.save_harness_links(links)
            return self.session.get_harness_links()

        @app.get("/v1/a2a/session/profile", response_model=AgentProfile)
        async def get_session_profile() -> AgentProfile:
            return self.agent_profile

        @app.put("/v1/a2a/session/profile", response_model=AgentProfile)
        async def put_session_profile(body: AgentProfile) -> AgentProfile:
            updated = AgentProfile(**self.agent_profile.model_dump())
            updated.apply_manual(
                harness=body.harness,
                model_id=body.model_id,
                model_display=body.model_display,
            )
            if not updated.is_set():
                raise HTTPException(status_code=400, detail="At least one of harness, model_id, or model_display is required")
            self.agent_profile = updated
            self.session.save_agent_profile(updated)
            self._apply_profile_to_self()
            return self.agent_profile

        @app.get("/v1/a2a/runbook", response_model=RunbookState)
        async def get_runbook(run_id: Optional[int] = None) -> RunbookState:
            coordinator = RunbookCoordinator(self.session)
            return coordinator.get_runbook(run_id=run_id)

        @app.post("/v1/a2a/runbook/ack")
        async def ack_runbook_item(body: Dict[str, Any]) -> Dict[str, Any]:
            message_id = body.get("message_id")
            human_role = body.get("human_role", "host")
            response_text = body.get("response", "Acknowledged")
            run_id = body.get("run_id")
            envelope = MessageEnvelope(
                sender_id=f"human-{human_role}",
                origin_sender_id=f"human-{human_role}",
                action=ActionType.HUMAN_SIGNAL,
                natural_language=response_text,
                payload={
                    "ack_message_id": message_id,
                    "human_role": human_role,
                    "signal": "ack",
                    "run_id": run_id,
                },
                relay=True,
            )
            await self._ingest_message(envelope)
            return {"status": "ok", "message_id": envelope.message_id}

    async def _broadcast_event(self, data: Dict[str, Any]) -> None:
        for q in list(self._subscribers):
            try:
                await q.put(data)
            except Exception:
                pass

    def _check_instrumentation_rejection(self, envelope: MessageEnvelope) -> Optional[str]:
        """Reject local stale READY in strict mode before persistence."""
        if envelope.action != ActionType.REPORT_INSTRUMENTATION_READY:
            return None
        if envelope.sender_id != self.agent_id:
            return None
        if not self.strict_instrumentation:
            return None
        payload = dict(envelope.payload or {})
        text = envelope.natural_language or ""
        if "pid" not in payload:
            pid_match = re.search(r"PID\s+(\d+)", text, re.IGNORECASE)
            if pid_match:
                payload["pid"] = int(pid_match.group(1))
        result = validate_instrumentation_payload(payload, strict=True, validate_local_process=True)
        if not result["ok"]:
            return result["reason"]
        return None

    async def _ingest_message(self, envelope: MessageEnvelope) -> tuple[bool, Optional[Dict[str, Any]]]:
        """Persist and publish one unseen message through every local delivery path."""
        if envelope.message_id in self._seen_message_ids:
            return False, self.barrier.ready_response_for_envelope(envelope)

        rejection = self._check_instrumentation_rejection(envelope)
        if rejection:
            raise InstrumentationRejected(rejection)

        self.session.record_message(envelope)
        self._seen_message_ids.add(envelope.message_id)
        ready_meta = self.barrier.on_message(envelope)
        logger.info(
            f"[{self.agent_id}] Ingested message {envelope.message_id} "
            f"from {envelope.sender_id}: {envelope.action.value}"
        )

        for handler in self._action_handlers.get(envelope.action, []):
            try:
                result = handler(envelope)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception as exc:
                logger.error(f"Error in action handler: {exc}")

        await self._broadcast_event({
            "event": "message",
            "envelope": envelope.model_dump(),
        })
        self._message_waiters.notify(envelope)
        return True, ready_meta

    def on_action(self, action: ActionType, handler: Callable[[MessageEnvelope], Any]) -> None:
        if action not in self._action_handlers:
            self._action_handlers[action] = []
        self._action_handlers[action].append(handler)

    # --- Background Loops & Peer Management ---

    def _apply_profile_to_self(self) -> None:
        profile_data = self.agent_profile.model_dump()
        self.agent_card.metadata["agent_profile"] = profile_data
        self.self_peer.metadata["agent_profile"] = profile_data
        self.session.register_peer(self.self_peer)

    @staticmethod
    def _peer_profile_fields(peer: AgentPeer) -> Dict[str, Any]:
        profile = peer_profile_from_metadata(peer.metadata)
        if not profile:
            return {}
        return {
            "harness": profile.harness,
            "model_id": profile.model_id,
            "model_display": profile.model_display,
            "profile_confidence": profile.confidence,
        }

    async def _connect_peer_loop(self, peer_url: str) -> None:
        await asyncio.sleep(0.2)
        delay = 1.0
        attempt = 1
        while True:
            try:
                await self.connect_to_peer(peer_url)
                logger.info(f"[{self.agent_id}] Successfully established handshake with initial peer {peer_url}")
                # Start persistent outbound SSE stream so NATed client receives all host events
                sse_task = asyncio.create_task(self._subscribe_peer_events_loop(peer_url))
                self._bg_tasks.append(sse_task)
                break
            except Exception as e:
                logger.debug(f"Handshake attempt {attempt} to {peer_url} failed: {e}. Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
                delay = min(delay * 1.5, 30.0)
                attempt += 1

    async def _subscribe_peer_events_loop(self, peer_url: str) -> None:
        """Maintains a persistent SSE stream to the peer node for inbound push notifications."""
        delay = 2.0
        while True:
            try:
                # Reconcile missing ledger items on connect/reconnect
                await self.reconcile_with_peer(peer_url)

                logger.info(f"Subscribing to remote peer SSE at {peer_url}/v1/a2a/events")
                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream("GET", f"{peer_url.rstrip('/')}/v1/a2a/events") as response:
                        if response.status_code != 200:
                            logger.debug(f"Peer SSE returned status {response.status_code}")
                            await asyncio.sleep(delay)
                            delay = min(delay * 1.5, 30.0)
                            continue

                        delay = 2.0  # Reset backoff on success
                        async for line in response.aiter_lines():
                            if not line or not line.startswith("data: "):
                                continue
                            raw_data = line[6:].strip()
                            if not raw_data:
                                continue
                            try:
                                event = json.loads(raw_data)
                                ev_type = event.get("event")

                                if ev_type == "message":
                                    env_data = event.get("envelope")
                                    if env_data:
                                        env = MessageEnvelope(**env_data)
                                        await self._ingest_message(env)

                                elif ev_type == "hypothesis_proposed":
                                    hyp_data = event.get("hypothesis")
                                    if hyp_data:
                                        hyp = Hypothesis(**hyp_data)
                                        self.session.storage.save_hypothesis(hyp)
                                        await self._broadcast_event(event)

                                elif ev_type == "experiment_proposed":
                                    exp_data = event.get("experiment")
                                    if exp_data:
                                        exp = Experiment(**exp_data)
                                        self.session.storage.save_experiment(exp)
                                        await self._broadcast_event(event)

                                elif ev_type == "sync_signal":
                                    sig_data = event.get("signal")
                                    if sig_data:
                                        sig = SyncRunSignal(**sig_data)
                                        await self._broadcast_event(event)

                                elif ev_type == "run_recorded":
                                    run_data = event.get("run")
                                    if run_data:
                                        run = RunRecord(**run_data)
                                        self.session.record_run(run)
                                        await self._broadcast_event(event)

                                elif ev_type == "observation_added":
                                    obs_data = event.get("observation")
                                    if obs_data:
                                        obs = Observation(**obs_data)
                                        self.session.storage.save_observation(obs)
                                        await self._broadcast_event(event)

                                elif ev_type == "artifact_shared":
                                    art_data = event.get("artifact")
                                    if art_data:
                                        art = ArtifactPayload(**art_data)
                                        self.session.storage.save_artifact(art)
                                        await self._broadcast_event(event)

                            except Exception as e:
                                logger.debug(f"Error parsing incoming peer SSE event: {e}")
            except Exception as e:
                logger.debug(f"Peer SSE connection to {peer_url} dropped: {e}. Reconnecting in {delay:.1f}s...")
                await asyncio.sleep(delay)
                delay = min(delay * 1.5, 30.0)

    async def reconcile_with_peer(self, peer_url: str) -> None:
        """Exchanges ledger hashes/IDs and pulls any missing records from the authoritative peer."""
        try:
            known_msgs = [m.message_id for m in self.session.get_messages(limit=None)]
            known_hyps = [h.id for h in self.session.get_hypotheses()]
            known_exps = [e.id for e in self.session.get_experiments()]
            known_runs = [r.run_id for r in self.session.get_runs()]

            req = ReconcileRequest(
                agent_id=self.agent_id,
                session_id=self.session_id,
                known_message_ids=known_msgs,
                known_hypothesis_ids=known_hyps,
                known_experiment_ids=known_exps,
                known_run_ids=known_runs,
            )
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(f"{peer_url.rstrip('/')}/v1/a2a/sync/reconcile", json=req.model_dump())
                if res.status_code == 200:
                    data = res.json()
                    rec = ReconcileResponse(**data)
                    for m_data in rec.missing_messages:
                        env = MessageEnvelope(**m_data) if isinstance(m_data, dict) else m_data
                        await self._ingest_message(env)

                    for h_data in rec.missing_hypotheses:
                        hyp = Hypothesis(**h_data) if isinstance(h_data, dict) else h_data
                        self.session.storage.save_hypothesis(hyp)
                        await self._broadcast_event({"event": "hypothesis_proposed", "hypothesis": hyp.model_dump()})

                    for e_data in rec.missing_experiments:
                        exp = Experiment(**e_data) if isinstance(e_data, dict) else e_data
                        self.session.storage.save_experiment(exp)
                        await self._broadcast_event({"event": "experiment_proposed", "experiment": exp.model_dump()})

                    for r_data in rec.missing_runs:
                        run = RunRecord(**r_data) if isinstance(r_data, dict) else r_data
                        self.session.record_run(run)
                        await self._broadcast_event({"event": "run_recorded", "run": run.model_dump()})

        except Exception as e:
            logger.debug(f"Reconciliation with {peer_url} failed: {e}")

    async def _periodic_heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(10.0)
            peers = self.session.get_peers()
            for peer in peers:
                if peer.agent_id == self.agent_id:
                    continue
                try:
                    await self.measure_clock_offset(peer.endpoint_url)
                    self._peer_miss_counts[peer.agent_id] = 0
                except Exception:
                    misses = self._peer_miss_counts.get(peer.agent_id, 0) + 1
                    self._peer_miss_counts[peer.agent_id] = misses
                    if misses >= 3:
                        self.session.remove_peer(peer.agent_id)
                        self._peer_miss_counts.pop(peer.agent_id, None)
                        await self._broadcast_event({
                            "event": "peer_left",
                            "peer_id": peer.agent_id,
                        })

    # --- Outbound P2P Communication & Relay ---

    async def connect_to_peer(self, peer_url: str) -> HandshakeResponse:
        async with httpx.AsyncClient(timeout=10.0) as client:
            req = HandshakeRequest(
                agent_id=self.agent_id,
                role=self.role,
                endpoint_url=self.endpoint_url,
                machine_name=self.machine_name,
                capabilities=self.self_peer.capabilities,
                session_id=self.session_id,
                agent_card=self.agent_card,
            )
            response_raw = await client.post(f"{peer_url.rstrip('/')}/v1/a2a/handshake", json=req.model_dump())
            response_raw.raise_for_status()
            response = HandshakeResponse(**response_raw.json())

            remote_metadata: Dict[str, Any] = {}
            if response.agent_card and response.agent_card.metadata:
                remote_metadata = dict(response.agent_card.metadata)

            remote_peer = AgentPeer(
                agent_id=response.agent_id,
                role=response.role,
                endpoint_url=peer_url,
                metadata=remote_metadata,
            )
            for p in response.peers:
                if p.agent_id != self.agent_id:
                    self.session.register_peer(p)

            self.session.register_peer(remote_peer)

            # Measure initial clock offset
            try:
                await self.measure_clock_offset(peer_url)
            except Exception:
                pass

            return response

    async def measure_clock_offset(self, peer_url: str) -> Dict[str, float]:
        """Calculates NTP-style round-trip time and UTC clock offset relative to peer."""
        t0_mono = get_monotonic_ns()
        t0_wall = get_wall_time_ns()
        async with httpx.AsyncClient(timeout=5.0) as client:
            ping_req = PingRequest(agent_id=self.agent_id, t0_send_mono_ns=t0_mono, t0_send_wall_ns=t0_wall)
            res = await client.post(f"{peer_url.rstrip('/')}/v1/a2a/ping", json=ping_req.model_dump())
            res.raise_for_status()
            pong = PongResponse(**res.json())
            t3_mono = get_monotonic_ns()
            t3_wall = get_wall_time_ns()

            # Monotonic RTT in ms
            rtt_ns = (t3_mono - pong.t0_send_mono_ns) - (pong.t2_send_mono_ns - pong.t1_recv_mono_ns)
            rtt_ms = max(0.05, rtt_ns / 1_000_000.0)

            # True Wall-Clock Offset in ms using Unix Epoch: ((t1_wall - t0_wall) + (t2_wall - t3_wall)) / 2
            offset_ns = ((pong.t1_recv_wall_ns - pong.t0_send_wall_ns) + (pong.t2_send_wall_ns - t3_wall)) / 2.0
            offset_ms = offset_ns / 1_000_000.0
            uncertainty_ms = rtt_ms / 2.0

            metrics = {"rtt_ms": rtt_ms, "offset_ms": offset_ms, "uncertainty_ms": uncertainty_ms}

            # Update peer in storage
            peers = self.session.get_peers()
            for p in peers:
                if p.endpoint_url.rstrip("/") == peer_url.rstrip("/"):
                    p.clock_offset_ms = offset_ms
                    p.clock_uncertainty_ms = uncertainty_ms
                    self.session.register_peer(p)
                    self._peer_metrics[p.agent_id] = metrics
                    break

            return metrics

    async def _relay_to_peers(self, envelope: MessageEnvelope) -> None:
        """Relays a message envelope to all other known registered peers across the network."""
        peers = self.session.get_peers()
        for peer in peers:
            # Skip self, original sender, and immediate previous sender
            if (
                peer.agent_id == self.agent_id
                or peer.agent_id == envelope.origin_sender_id
                or peer.agent_id == envelope.sender_id
            ):
                continue

            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(
                        f"{peer.endpoint_url.rstrip('/')}/v1/a2a/messages",
                        json=envelope.model_dump(),
                    )
            except Exception as e:
                logger.debug(f"Failed to relay message to {peer.agent_id} ({peer.endpoint_url}): {e}")

    async def broadcast_message(self, envelope: MessageEnvelope) -> List[Dict[str, Any]]:
        """Originates or broadcasts a message to all registered peers."""
        self._seen_message_ids.add(envelope.message_id)
        self.session.record_message(envelope)
        peers = self.session.get_peers()
        results = []
        for peer in peers:
            if peer.agent_id == self.agent_id:
                continue
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.post(
                        f"{peer.endpoint_url.rstrip('/')}/v1/a2a/messages",
                        json=envelope.model_dump(),
                    )
                    results.append({"peer_id": peer.agent_id, "status": "sent", "response": res.json()})
            except Exception as e:
                results.append({"peer_id": peer.agent_id, "status": "error", "error": str(e)})
        return results

    async def send_sync_signal(self, peer_url: str, signal: SyncRunSignal) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{peer_url.rstrip('/')}/v1/a2a/runs/sync",
                json=signal.model_dump(),
            )
            resp.raise_for_status()
            return resp.json()
