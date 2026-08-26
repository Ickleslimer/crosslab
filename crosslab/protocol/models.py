"""
Data models and schemas for CrossLab A2A collaboration.
"""

from datetime import datetime, timezone
import hashlib
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

from crosslab.protocol.actions import (
    ActionType,
    AgentRole,
    ExperimentStatus,
    HypothesisStatus,
    RunOutcome,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str = "") -> str:
    uid = uuid.uuid4().hex[:8]
    return f"{prefix}_{uid}" if prefix else uid


class AgentPeer(BaseModel):
    agent_id: str
    role: AgentRole = AgentRole.OBSERVER
    endpoint_url: str
    machine_name: Optional[str] = None
    capabilities: List[str] = Field(default_factory=lambda: ["reasoning", "instrumentation", "telemetry", "patching"])
    joined_at: str = Field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class HandshakeRequest(BaseModel):
    agent_id: str
    role: AgentRole
    endpoint_url: str
    machine_name: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    session_id: Optional[str] = None


class HandshakeResponse(BaseModel):
    agent_id: str
    role: AgentRole
    session_id: str
    accepted: bool = True
    message: str = "Handshake accepted"
    peers: List[AgentPeer] = Field(default_factory=list)


class MessageEnvelope(BaseModel):
    message_id: str = Field(default_factory=lambda: new_id("msg"))
    conversation_id: str = "default"
    session_id: str = "default"
    sender_id: str
    recipient_id: Optional[str] = None  # None = broadcast to all peers
    timestamp: str = Field(default_factory=utc_now_iso)
    action: ActionType = ActionType.CHAT
    natural_language: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class Hypothesis(BaseModel):
    id: str = Field(default_factory=lambda: new_id("hyp"))
    session_id: str = "default"
    title: str
    description: str
    creator: str
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    confidence: float = 0.5  # 0.0 to 1.0
    evidence_for: List[str] = Field(default_factory=list)
    evidence_against: List[str] = Field(default_factory=list)
    supporting_run_ids: List[int] = Field(default_factory=list)
    contradicting_run_ids: List[int] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class Experiment(BaseModel):
    id: str = Field(default_factory=lambda: new_id("exp"))
    session_id: str = "default"
    run_id: int
    hypothesis_id: Optional[str] = None
    title: str
    rationale: str
    host_role: str
    client_role: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    status: ExperimentStatus = ExperimentStatus.PROPOSED
    creator: str
    created_at: str = Field(default_factory=utc_now_iso)


class Observation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("obs"))
    session_id: str = "default"
    run_id: int
    agent_id: str
    timestamp: str = Field(default_factory=utc_now_iso)
    metric_name: str
    value: Any
    unit: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


class RunRecord(BaseModel):
    run_id: int
    session_id: str = "default"
    experiment_id: Optional[str] = None
    hypothesis_id: Optional[str] = None
    hypothesis_title: Optional[str] = None
    build: str = "default-build"
    participants: List[str] = Field(default_factory=list)
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    outcome: RunOutcome = RunOutcome.PENDING
    result_summary: Optional[str] = None
    host: Dict[str, Any] = Field(default_factory=dict)
    client: Dict[str, Any] = Field(default_factory=dict)
    logs: List[Dict[str, Any]] = Field(default_factory=list)
    observations: List[Observation] = Field(default_factory=list)
    correlated_findings: Optional[Dict[str, Any]] = None
    created_at: str = Field(default_factory=utc_now_iso)


class InstrumentationRequest(BaseModel):
    id: str = Field(default_factory=lambda: new_id("inst"))
    session_id: str = "default"
    requester_id: str
    target_agent_id: str
    target_module: str
    target_function: Optional[str] = None
    trace_type: str  # e.g., "packet_trace", "timing_probe", "state_watch"
    parameters: Dict[str, Any] = Field(default_factory=dict)
    sampling_rate_ms: Optional[int] = 100
    rationale: str
    status: str = "pending"  # "pending", "ready", "rejected"
    created_at: str = Field(default_factory=utc_now_iso)


class ArtifactPayload(BaseModel):
    id: str = Field(default_factory=lambda: new_id("art"))
    session_id: str = "default"
    filename: str
    content_type: str  # "text/plain", "text/x-patch", "application/json", etc.
    content: str
    sha256: str = ""
    author_id: str
    description: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)

    def model_post_init(self, __context: Any) -> None:
        if not self.sha256 and self.content:
            self.sha256 = hashlib.sha256(self.content.encode("utf-8")).hexdigest()


class SyncRunSignal(BaseModel):
    run_id: int
    session_id: str = "default"
    sender_id: str
    phase: str  # "propose", "prepare", "ready", "start", "stop", "abort"
    timestamp: str = Field(default_factory=utc_now_iso)
    payload: Dict[str, Any] = Field(default_factory=dict)


class Discrepancy(BaseModel):
    code: str
    description: str
    host_evidence: Optional[Dict[str, Any]] = None
    client_evidence: Optional[Dict[str, Any]] = None
    impact: str


class CorrelationResult(BaseModel):
    run_id: int
    session_id: str = "default"
    analyzed_at: str = Field(default_factory=utc_now_iso)
    summary: str
    reproduced: bool
    discrepancies: List[Discrepancy] = Field(default_factory=list)
    timeline: List[Dict[str, Any]] = Field(default_factory=list)
    hypothesis_verdict: Optional[str] = None
    suggested_next_steps: List[str] = Field(default_factory=list)
