"""
CrossLab Agent Client SDK.
Provides a clean, high-level asynchronous and synchronous interface for coding agents.
"""

from typing import Any, Dict, List, Optional
import httpx

from crosslab.protocol.actions import ActionType, AgentRole, HypothesisStatus
from crosslab.protocol.models import (
    ArtifactPayload,
    CorrelationResult,
    Experiment,
    Hypothesis,
    InstrumentationRequest,
    MessageEnvelope,
    Observation,
    RunRecord,
    SyncRunSignal,
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

    async def send_chat(self, text: str, recipient_id: Optional[str] = None) -> Dict[str, Any]:
        envelope = MessageEnvelope(
            sender_id=self.agent_id,
            recipient_id=recipient_id,
            action=ActionType.CHAT,
            natural_language=text,
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(f"{self.base_url}/v1/a2a/messages", json=envelope.model_dump())
            return res.json()

    async def propose_hypothesis(
        self,
        title: str,
        description: str,
        natural_language: Optional[str] = None,
        confidence: float = 0.5,
    ) -> Hypothesis:
        hyp = Hypothesis(
            title=title,
            description=description,
            creator=self.agent_id,
            confidence=confidence,
        )
        # 1. Store hypothesis locally
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(f"{self.base_url}/v1/a2a/hypotheses", json=hyp.model_dump())

            # 2. Broadcast envelope to peers
            nl_text = natural_language or f"I propose the hypothesis: '{title}' - {description}"
            envelope = MessageEnvelope(
                sender_id=self.agent_id,
                action=ActionType.PROPOSE_HYPOTHESIS,
                natural_language=nl_text,
                payload={"hypothesis": hyp.model_dump()},
            )
            await client.post(f"{self.base_url}/v1/a2a/messages", json=envelope.model_dump())

        return hyp

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
            action=ActionType.CHALLENGE_HYPOTHESIS,
            natural_language=nl_text,
            payload={
                "hypothesis_id": hypothesis_id,
                "reason": reason,
                "counter_evidence": counter_evidence,
            },
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
                action=ActionType.PROPOSE_EXPERIMENT,
                natural_language=nl_text,
                payload={"experiment": exp.model_dump()},
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
            action=ActionType.ACCEPT_EXPERIMENT,
            natural_language=nl_text,
            payload={"experiment_id": experiment_id},
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
            payload=payload or {},
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(f"{self.base_url}/v1/a2a/runs/sync", json=signal.model_dump())
            return res.json()

    async def submit_run_record(self, run: RunRecord) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(f"{self.base_url}/v1/a2a/runs", json=run.model_dump())
            return res.json()

    async def request_instrumentation(
        self,
        target_agent_id: str,
        target_module: str,
        trace_type: str,
        rationale: str,
        target_function: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        req = InstrumentationRequest(
            requester_id=self.agent_id,
            target_agent_id=target_agent_id,
            target_module=target_module,
            target_function=target_function,
            trace_type=trace_type,
            parameters=parameters or {},
            rationale=rationale,
        )
        envelope = MessageEnvelope(
            sender_id=self.agent_id,
            recipient_id=target_agent_id,
            action=ActionType.REQUEST_INSTRUMENTATION,
            natural_language=f"Please instrument {target_module} ({trace_type}): {rationale}",
            payload={"request": req.model_dump()},
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(f"{self.base_url}/v1/a2a/messages", json=envelope.model_dump())
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
                action=ActionType.SHARE_PATCH,
                natural_language=f"I've shared a patch '{filename}': {description}",
                payload={"artifact": art.model_dump()},
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
