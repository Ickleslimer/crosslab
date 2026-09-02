"""
Data models and schemas for CrossLab A2A collaboration.
"""

from datetime import datetime, timezone
import hashlib
import time
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

from crosslab.protocol.actions import (
    ActionType,
    AgentRole,
    EvidenceRelation,
    EvidenceType,
    ExperimentStatus,
    HypothesisStatus,
    RunOutcome,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str = "") -> str:
    uid = uuid.uuid4().hex[:8]
    return f"{prefix}_{uid}" if prefix else uid


def get_monotonic_ns() -> int:
    return time.monotonic_ns()


class AgentCard(BaseModel):
    """A2A 1.0 compliant Agent Card specification."""
    name: str
    description: str
    version: str = "0.2.0"
    url: str
    role: AgentRole = AgentRole.OBSERVER
    machine_name: Optional[str] = None
    capabilities: List[str] = Field(default_factory=lambda: [
        "empirical_investigation",
        "hypotheses_evidence_graph",
        "synchronized_runs",
        "cross_machine_correlation",
        "instrumentation",
        "patching"
    ])
    endpoints: Dict[str, str] = Field(default_factory=dict)
    provider: Dict[str, Any] = Field(default_factory=lambda: {"name": "CrossLab"})
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentPeer(BaseModel):
    agent_id: str
    role: AgentRole = AgentRole.OBSERVER
    endpoint_url: str
    machine_name: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    clock_offset_ms: float = 0.0
    clock_uncertainty_ms: float = 0.0
    joined_at: str = Field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = Field(default_factory=dict)


def get_wall_time_ns() -> int:
    return time.time_ns()


class PingRequest(BaseModel):
    agent_id: str
    t0_send_mono_ns: int = Field(default_factory=get_monotonic_ns)
    t0_send_wall_ns: int = Field(default_factory=get_wall_time_ns)
    t0_send_ns: Optional[int] = None

    def model_post_init(self, __context: Any) -> None:
        if self.t0_send_ns is not None:
            self.t0_send_mono_ns = self.t0_send_ns


class PongResponse(BaseModel):
    agent_id: str
    t0_send_mono_ns: int
    t0_send_wall_ns: int
    t1_recv_mono_ns: int = Field(default_factory=get_monotonic_ns)
    t1_recv_wall_ns: int = Field(default_factory=get_wall_time_ns)
    t2_send_mono_ns: int = Field(default_factory=get_monotonic_ns)
    t2_send_wall_ns: int = Field(default_factory=get_wall_time_ns)
    t0_send_ns: Optional[int] = None
    t1_recv_ns: Optional[int] = None
    t2_send_ns: Optional[int] = None

    def model_post_init(self, __context: Any) -> None:
        if self.t0_send_ns is None:
            self.t0_send_ns = self.t0_send_mono_ns
        if self.t1_recv_ns is None:
            self.t1_recv_ns = self.t1_recv_mono_ns
        if self.t2_send_ns is None:
            self.t2_send_ns = self.t2_send_mono_ns


class HandshakeRequest(BaseModel):
    agent_id: str
    role: AgentRole
    endpoint_url: str
    machine_name: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    session_id: Optional[str] = None
    agent_card: Optional[AgentCard] = None


class HandshakeResponse(BaseModel):
    agent_id: str
    role: AgentRole
    session_id: str
    accepted: bool = True
    message: str = "Handshake accepted"
    warnings: List[str] = Field(default_factory=list)
    peers: List[AgentPeer] = Field(default_factory=list)
    agent_card: Optional[AgentCard] = None


class ReconcileRequest(BaseModel):
    agent_id: str
    session_id: str
    known_message_ids: List[str] = Field(default_factory=list)
    known_hypothesis_ids: List[str] = Field(default_factory=list)
    known_experiment_ids: List[str] = Field(default_factory=list)
    known_run_ids: List[int] = Field(default_factory=list)


class ReconcileResponse(BaseModel):
    agent_id: str
    session_id: str
    missing_messages: List[Any] = Field(default_factory=list)
    missing_hypotheses: List[Any] = Field(default_factory=list)
    missing_experiments: List[Any] = Field(default_factory=list)
    missing_runs: List[Any] = Field(default_factory=list)


class MessageEnvelope(BaseModel):
    message_id: str = Field(default_factory=lambda: new_id("msg"))
    conversation_id: str = "default"
    session_id: str = "default"
    sender_id: str
    origin_sender_id: Optional[str] = None
    recipient_id: Optional[str] = None  # None = broadcast to all peers
    timestamp: str = Field(default_factory=utc_now_iso)
    monotonic_ns: int = Field(default_factory=get_monotonic_ns)
    hops: int = 0
    relay: bool = True
    correlation_id: Optional[str] = None
    action: ActionType = ActionType.CHAT
    natural_language: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if not self.origin_sender_id:
            self.origin_sender_id = self.sender_id


class EvidenceItem(BaseModel):
    """An explicit link in a hypothesis evidence graph."""
    evidence_id: str = Field(default_factory=lambda: new_id("ev"))
    evidence_type: EvidenceType
    relation: EvidenceRelation  # SUPPORTS, CONTRADICTS, QUALIFIES, INCONCLUSIVE
    source_agent_id: str
    source_id: str  # run_id, observation_id, or artifact_id
    rationale: str
    details: Dict[str, Any] = Field(default_factory=dict)
    recorded_at: str = Field(default_factory=utc_now_iso)


class AgentAssessment(BaseModel):
    """Subjective assessment by an individual agent."""
    agent_id: str
    confidence_score: float = 0.5  # 0.0 to 1.0
    rationale: str
    updated_at: str = Field(default_factory=utc_now_iso)


class Hypothesis(BaseModel):
    id: str = Field(default_factory=lambda: new_id("hyp"))
    session_id: str = "default"
    title: str
    description: str
    creator: str
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    parent_hypothesis_id: Optional[str] = None  # Refinement hierarchy
    evidence_graph: List[EvidenceItem] = Field(default_factory=list)
    agent_assessments: Dict[str, AgentAssessment] = Field(default_factory=dict)
    confidence: Optional[float] = None  # Computed consensus or primary assessment
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)

    @property
    def supporting_run_ids(self) -> List[int]:
        runs = []
        for ev in self.evidence_graph:
            if ev.evidence_type == EvidenceType.RUN and ev.relation == EvidenceRelation.SUPPORTS:
                try:
                    runs.append(int(ev.source_id))
                except ValueError:
                    pass
        return runs

    @property
    def contradicting_run_ids(self) -> List[int]:
        runs = []
        for ev in self.evidence_graph:
            if ev.evidence_type == EvidenceType.RUN and ev.relation == EvidenceRelation.CONTRADICTS:
                try:
                    runs.append(int(ev.source_id))
                except ValueError:
                    pass
        return runs


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
    wall_time: str = Field(default_factory=utc_now_iso)
    monotonic_ns: int = Field(default_factory=get_monotonic_ns)
    clock_offset_ms: float = 0.0
    clock_uncertainty_ms: float = 0.0
    sequence_num: int = 0
    causal_parent_id: Optional[str] = None
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
    trace_type: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    sampling_rate_ms: Optional[int] = 100
    rationale: str
    status: str = "pending"
    created_at: str = Field(default_factory=utc_now_iso)


class ArtifactPayload(BaseModel):
    id: str = Field(default_factory=lambda: new_id("art"))
    session_id: str = "default"
    filename: str
    content_type: str
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
    monotonic_ns: int = Field(default_factory=get_monotonic_ns)
    payload: Dict[str, Any] = Field(default_factory=dict)


class Discrepancy(BaseModel):
    code: str
    description: str
    analyzer: str = "generic"
    host_evidence: Optional[Dict[str, Any]] = None
    client_evidence: Optional[Dict[str, Any]] = None
    impact: str


class TimelineEvent(BaseModel):
    source: str
    event_type: str
    message: str
    wall_time: str
    monotonic_ns: Optional[int] = None
    adjusted_time_ms: Optional[float] = None
    uncertainty_ms: float = 0.0
    details: Dict[str, Any] = Field(default_factory=dict)


class CorrelationResult(BaseModel):
    run_id: int
    session_id: str = "default"
    analyzed_at: str = Field(default_factory=utc_now_iso)
    summary: str
    reproduced: bool
    discrepancies: List[Discrepancy] = Field(default_factory=list)
    timeline: List[Dict[str, Any]] = Field(default_factory=list)
    temporal_insights: List[str] = Field(default_factory=list)
    hypothesis_verdict: Optional[str] = None
    suggested_next_steps: List[str] = Field(default_factory=list)
