"""
CrossLab Agent Client SDK.
Provides a clean, high-level asynchronous interface for AI coding agents to communicate over A2A.
"""

from typing import Any, Dict, List, Optional
import httpx

from crosslab.protocol.actions import (
    ActionType,
    AgentRole,
    EvidenceRelation,
    EvidenceType,
    HypothesisStatus,
)
from crosslab.protocol.models import (
    AgentCard,
    ArtifactPayload,
    CorrelationResult,
    EvidenceItem,
    Experiment,
    Hypothesis,
    InstrumentationRequest,
    MessageEnvelope,
    Observation,
    RunRecord,
    SyncRunSignal,
    get_monotonic_ns,
)


class CrossLabClient:
    """
    Client for coding agents (Antigravity, Claude Code, Codex, Cursor, etc.)
    to interact with their local CrossLab node and peer network.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8000", agent_id: str = "agent-local"):
        self.base_url = base_url.rstrip("/")
        self.agent_id = agent_id

    async def ping(self) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(f"{self.base_url}/health")
            return res.json()

    async def get_agent_card(self) -> AgentCard:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(f"{self.base_url}/.well-known/agent-card.json")
            return AgentCard(**res.json())

    async def send_chat(self, text: str, recipient_id: Optional[str] = None) -> Dict[str, Any]:
        envelope = MessageEnvelope(
            sender_id=self.agent_id,
            origin_sender_id=self.agent_id,
            recipient_id=recipient_id,
            action=ActionType.CHAT,
            natural_language=text,
            relay=True,
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(f"{self.base_url}/v1/a2a/messages", json=envelope.model_dump())
            return res.json()

    async def propose_hypothesis(
        self,
        title: str,
        description: str,
        parent_hypothesis_id: Optional[str] = None,
        natural_language: Optional[str] = None,
        confidence: Optional[float] = 0.5,
    ) -> Hypothesis:
        hyp = Hypothesis(
            title=title,
            description=description,
            creator=self.agent_id,
            parent_hypothesis_id=parent_hypothesis_id,
            confidence=confidence,
        )
        # Store locally & broadcast envelope
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(f"{self.base_url}/v1/a2a/hypotheses", json=hyp.model_dump())

            nl_text = natural_language or f"I propose the hypothesis: '{title}' - {description}"
            envelope = MessageEnvelope(
                sender_id=self.agent_id,
                origin_sender_id=self.agent_id,
                action=ActionType.PROPOSE_HYPOTHESIS,
                natural_language=nl_text,
                payload={"hypothesis": hyp.model_dump()},
                relay=True,
            )
            await client.post(f"{self.base_url}/v1/a2a/messages", json=envelope.model_dump())

        return hyp

    async def add_evidence(
        self,
        hypothesis_id: str,
        evidence_type: EvidenceType,
        relation: EvidenceRelation,
        rationale: str,
        source_id: str = "agent-observation",
        details: Optional[Dict[str, Any]] = None,
        natural_language: Optional[str] = None,
    ) -> EvidenceItem:
        ev = EvidenceItem(
            evidence_type=evidence_type,
            relation=relation,
            source_agent_id=self.agent_id,
            source_id=source_id,
            rationale=rationale,
            details=details or {},
        )
        nl_text = natural_language or f"Added {relation.value} evidence to hypothesis {hypothesis_id}: {rationale}"
        envelope = MessageEnvelope(
            sender_id=self.agent_id,
            origin_sender_id=self.agent_id,
            action=ActionType.ADD_EVIDENCE,
            natural_language=nl_text,
            payload={"hypothesis_id": hypothesis_id, "evidence": ev.model_dump()},
            relay=True,
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(f"{self.base_url}/v1/a2a/messages", json=envelope.model_dump())
        return ev

    async def assess_hypothesis(
        self,
        hypothesis_id: str,
        confidence_score: float,
        rationale: str,
    ) -> Dict[str, Any]:
        envelope = MessageEnvelope(
            sender_id=self.agent_id,
            origin_sender_id=self.agent_id,
            action=ActionType.ASSESS_HYPOTHESIS,
            natural_language=f"Assessed hypothesis {hypothesis_id} at {confidence_score:.2f} confidence: {rationale}",
            payload={
                "hypothesis_id": hypothesis_id,
                "confidence_score": confidence_score,
                "rationale": rationale,
            },
            relay=True,
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(f"{self.base_url}/v1/a2a/messages", json=envelope.model_dump())
            return res.json()

    async def challenge_hypothesis(
        self,
        hypothesis_id: str,
        reason: str,
        counter_evidence: Optional[str] = None,
        natural_language: Optional[str] = None,
    ) -> Dict[str, Any]:
        nl_text = natural_language or f"I challenge hypothesis {hypothesis_id}: {reason}"
        envelope = MessageEnvelope(
            sender_id=self.agent_id,
            origin_sender_id=self.agent_id,
            action=ActionType.CHALLENGE_HYPOTHESIS,
            natural_language=nl_text,
            payload={
                "hypothesis_id": hypothesis_id,
                "reason": reason,
                "counter_evidence": counter_evidence,
            },
            relay=True,
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(f"{self.base_url}/v1/a2a/messages", json=envelope.model_dump())
            return res.json()

    async def propose_experiment(
        self,
        run_id: int,
        title: str,
        rationale: str,
        host_role: str,
        client_role: str,
        hypothesis_id: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        natural_language: Optional[str] = None,
    ) -> Experiment:
        exp = Experiment(
            run_id=run_id,
            hypothesis_id=hypothesis_id,
            title=title,
            rationale=rationale,
            host_role=host_role,
            client_role=client_role,
            creator=self.agent_id,
            parameters=parameters or {},
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(f"{self.base_url}/v1/a2a/experiments", json=exp.model_dump())

            nl_text = natural_language or (
                f"I propose Experiment for Run {run_id}: {title}. "
                f"Host plan: {host_role}. Client plan: {client_role}."
            )
            envelope = MessageEnvelope(
                sender_id=self.agent_id,
                origin_sender_id=self.agent_id,
                action=ActionType.PROPOSE_EXPERIMENT,
                natural_language=nl_text,
                payload={"experiment": exp.model_dump()},
                relay=True,
            )
            await client.post(f"{self.base_url}/v1/a2a/messages", json=envelope.model_dump())

        return exp

    async def accept_experiment(
        self,
        experiment_id: str,
        natural_language: Optional[str] = None,
    ) -> Dict[str, Any]:
        nl_text = natural_language or f"I accept experiment {experiment_id}. Ready to instrument."
        envelope = MessageEnvelope(
            sender_id=self.agent_id,
            origin_sender_id=self.agent_id,
            action=ActionType.ACCEPT_EXPERIMENT,
            natural_language=nl_text,
            payload={"experiment_id": experiment_id},
            relay=True,
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(f"{self.base_url}/v1/a2a/messages", json=envelope.model_dump())
            return res.json()

    async def send_sync_signal(
        self,
        run_id: int,
        phase: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        signal = SyncRunSignal(
            run_id=run_id,
            sender_id=self.agent_id,
            phase=phase,
            monotonic_ns=get_monotonic_ns(),
            payload=payload or {},
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(f"{self.base_url}/v1/a2a/runs/sync", json=signal.model_dump())
            return res.json()

    async def add_observation(
        self,
        run_id: int,
        metric_name: str,
        value: Any,
        unit: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notes: Optional[str] = None,
    ) -> Observation:
        obs = Observation(
            run_id=run_id,
            agent_id=self.agent_id,
            monotonic_ns=get_monotonic_ns(),
            metric_name=metric_name,
            value=value,
            unit=unit,
            tags=tags or [],
            notes=notes,
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(f"{self.base_url}/v1/a2a/observations", json=obs.model_dump())
        return obs

    async def submit_run_record(self, run: RunRecord) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(f"{self.base_url}/v1/a2a/runs", json=run.model_dump())
            return res.json()

    async def share_patch(
        self,
        filename: str,
        patch_content: str,
        description: str,
    ) -> ArtifactPayload:
        art = ArtifactPayload(
            filename=filename,
            content_type="text/x-patch",
            content=patch_content,
            author_id=self.agent_id,
            description=description,
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(f"{self.base_url}/v1/a2a/artifacts", json=art.model_dump())
            envelope = MessageEnvelope(
                sender_id=self.agent_id,
                origin_sender_id=self.agent_id,
                action=ActionType.SHARE_PATCH,
                natural_language=f"I've shared a patch '{filename}': {description}",
                payload={"artifact": art.model_dump()},
                relay=True,
            )
            await client.post(f"{self.base_url}/v1/a2a/messages", json=envelope.model_dump())
        return art

    async def get_summary(self) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{self.base_url}/v1/a2a/summary")
            return res.json()

    async def get_correlate(self, run_id: int) -> CorrelationResult:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{self.base_url}/v1/a2a/correlate/{run_id}")
            return CorrelationResult(**res.json())

    async def reconcile_ledger(
        self,
        known_message_ids: Optional[List[str]] = None,
        known_hypothesis_ids: Optional[List[str]] = None,
        known_experiment_ids: Optional[List[str]] = None,
        known_run_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "agent_id": self.agent_id,
            "session_id": "default",
            "known_message_ids": known_message_ids or [],
            "known_hypothesis_ids": known_hypothesis_ids or [],
            "known_experiment_ids": known_experiment_ids or [],
            "known_run_ids": known_run_ids or [],
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(f"{self.base_url}/v1/a2a/sync/reconcile", json=payload)
            return res.json()

    async def get_barrier_state(self, run_id: int) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{self.base_url}/v1/a2a/runs/{run_id}/barrier")
            res.raise_for_status()
            return res.json()

    async def wait_for_message(
        self,
        since_id: Optional[str] = None,
        timeout_s: float = 60.0,
        actions: Optional[List[str]] = None,
        exclude_self: bool = True,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"timeout_s": timeout_s, "exclude_self": str(exclude_self).lower()}
        if since_id:
            params["since_id"] = since_id
        if actions:
            params["actions"] = ",".join(actions)
        async with httpx.AsyncClient(timeout=timeout_s + 10.0) as client:
            res = await client.get(f"{self.base_url}/v1/a2a/messages/wait", params=params)
            return res.json()

    async def get_transcript(self) -> str:
        """Fetch the live human-readable Markdown transcript from the node."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{self.base_url}/v1/a2a/transcript")
            return res.text

    async def get_harness_links(self) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{self.base_url}/v1/a2a/session/manifest")
            res.raise_for_status()
            return res.json()

    async def get_agent_profile(self) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{self.base_url}/v1/a2a/session/profile")
            res.raise_for_status()
            return res.json()

    async def set_agent_profile(
        self,
        *,
        harness: Optional[str] = None,
        model_id: Optional[str] = None,
        model_display: Optional[str] = None,
    ) -> Dict[str, Any]:
        from crosslab.engine.agent_profile import AgentProfile

        current = await self.get_agent_profile()
        body = AgentProfile(**current)
        body.apply_manual(harness=harness, model_id=model_id, model_display=model_display)
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.put(f"{self.base_url}/v1/a2a/session/profile", json=body.model_dump())
            res.raise_for_status()
            return res.json()

    async def get_peer_profiles(self) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{self.base_url}/v1/a2a/peers/detailed")
            res.raise_for_status()
            peers = res.json()
        result = []
        for peer in peers:
            profile = (peer.get("metadata") or {}).get("agent_profile") or {}
            if not profile and peer.get("harness"):
                profile = {
                    "harness": peer.get("harness"),
                    "model_id": peer.get("model_id"),
                    "model_display": peer.get("model_display"),
                    "confidence": peer.get("profile_confidence", 1.0),
                }
            result.append({
                "agent_id": peer.get("agent_id"),
                "role": peer.get("role"),
                "endpoint_url": peer.get("endpoint_url"),
                "agent_profile": profile,
            })
        return result

    async def detect_agent_profile(
        self,
        harness: Optional[str] = None,
        apply: bool = False,
    ) -> Dict[str, Any]:
        import os

        from crosslab.engine.harness_probes import detect_summary
        from crosslab.engine.harness_probes.cursor_ide import probe_cursor_ide

        harness_hint = harness or os.environ.get("CROSSLAB_HARNESS")
        candidates, selected = detect_summary(harness_hint=harness_hint or None)
        cursor_ide = probe_cursor_ide()
        payload: Dict[str, Any] = {
            "status": "ok",
            "candidates": [c.to_dict() for c in candidates],
            "selected": selected.model_dump() if selected else None,
            "cursor_ide": cursor_ide.to_dict() if cursor_ide else None,
            "applied": False,
        }

        if apply and selected and selected.is_set():
            current = await self.get_agent_profile()
            has_current = bool(current.get("model_id") or current.get("model_display"))
            if not has_current:
                updated = await self.set_agent_profile(
                    harness=selected.harness,
                    model_id=selected.model_id,
                    model_display=selected.model_display,
                )
                payload["applied"] = True
                payload["profile"] = updated
            else:
                payload["note"] = "Current profile already set; not overwriting"

        return payload

    async def set_harness_link(self, harness: str, thread_id: str) -> Dict[str, Any]:
        links = await self.get_harness_links()
        from crosslab.engine.manifest import HarnessLinks
        model = HarnessLinks(**links)
        model.set_link(harness, thread_id)
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.put(f"{self.base_url}/v1/a2a/session/manifest", json=model.model_dump())
            res.raise_for_status()
            return res.json()

    async def get_runbook(self, run_id: Optional[int] = None) -> Dict[str, Any]:
        params = {"run_id": run_id} if run_id is not None else {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{self.base_url}/v1/a2a/runbook", params=params)
            res.raise_for_status()
            return res.json()

    async def request_human_repro(
        self,
        run_id: int,
        steps: List[Dict[str, str]],
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        envelope = MessageEnvelope(
            sender_id=self.agent_id,
            origin_sender_id=self.agent_id,
            action=ActionType.HUMAN_REPRO_REQUEST,
            natural_language=title or f"Human reproduction steps for Run {run_id}",
            payload={"run_id": run_id, "steps": steps, "title": title or f"Run {run_id} repro"},
            relay=True,
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(f"{self.base_url}/v1/a2a/messages", json=envelope.model_dump())
            return res.json()

    async def human_signal(
        self,
        run_id: int,
        signal: str,
        detail: str,
        human_role: str = "host",
        ack_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        envelope = MessageEnvelope(
            sender_id=f"human-{human_role}",
            origin_sender_id=f"human-{human_role}",
            action=ActionType.HUMAN_SIGNAL,
            natural_language=detail,
            payload={
                "run_id": run_id,
                "signal": signal,
                "detail": detail,
                "human_role": human_role,
                "ack_message_id": ack_message_id,
            },
            relay=True,
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(f"{self.base_url}/v1/a2a/messages", json=envelope.model_dump())
            return res.json()
