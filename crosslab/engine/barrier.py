"""
Barrier coordination state machine for synchronized multi-machine runs.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from pydantic import BaseModel, Field

from crosslab.engine.probe_validation import validate_instrumentation_payload
from crosslab.protocol.actions import ActionType
from crosslab.protocol.models import MessageEnvelope, SyncRunSignal, utc_now_iso

if TYPE_CHECKING:
    from crosslab.engine.session import InvestigationSession


class BarrierPhase(str, Enum):
    IDLE = "idle"
    PAUSED = "paused"
    PREPARING = "preparing"
    READY_WAIT = "ready_wait"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    ABORTED = "aborted"


class BarrierState(BaseModel):
    run_id: int
    phase: BarrierPhase
    ready: Dict[str, bool] = Field(default_factory=lambda: {"host": False, "client": False})
    start_authorized: bool = False
    pause_reason: Optional[str] = None
    instrumentation: Dict[str, Any] = Field(default_factory=dict)
    last_signals: List[Dict[str, Any]] = Field(default_factory=list)
    updated_at: str = Field(default_factory=utc_now_iso)


def detect_role(sender_id: str) -> Optional[str]:
    sid = sender_id.lower()
    if "host" in sid:
        return "host"
    if "client" in sid:
        return "client"
    return None


class RunBarrierTracker:
    def __init__(self, run_id: int) -> None:
        self.run_id = run_id
        self.ready: Dict[str, bool] = {"host": False, "client": False}
        self.instrumentation: Dict[str, Any] = {}
        self.phase: BarrierPhase = BarrierPhase.IDLE
        self.last_signals: List[Dict[str, Any]] = []
        self.updated_at = utc_now_iso()

    def touch(self) -> None:
        self.updated_at = utc_now_iso()

    def mark_ready(self, role: str) -> bool:
        """Mark role ready. Returns True if this was a duplicate (already ready)."""
        duplicate = self.ready.get(role, False)
        if role in self.ready:
            self.ready[role] = True
        self.touch()
        return duplicate

    def to_state(self, session_paused: bool, pause_reason: Optional[str]) -> BarrierState:
        ready_both = self.ready.get("host", False) and self.ready.get("client", False)
        phase = self.phase
        if session_paused and phase not in (BarrierPhase.COMPLETED, BarrierPhase.ABORTED):
            phase = BarrierPhase.PAUSED
        elif ready_both and phase in (BarrierPhase.IDLE, BarrierPhase.PREPARING, BarrierPhase.READY_WAIT, BarrierPhase.READY):
            phase = BarrierPhase.READY
        elif self.ready.get("host") or self.ready.get("client"):
            if phase in (BarrierPhase.IDLE, BarrierPhase.PREPARING):
                phase = BarrierPhase.READY_WAIT

        start_authorized = ready_both and not session_paused and phase in (
            BarrierPhase.READY,
            BarrierPhase.RUNNING,
        )

        return BarrierState(
            run_id=self.run_id,
            phase=phase,
            ready=dict(self.ready),
            start_authorized=start_authorized,
            pause_reason=pause_reason if session_paused else None,
            instrumentation=dict(self.instrumentation),
            last_signals=list(self.last_signals[-10:]),
            updated_at=self.updated_at,
        )


class BarrierCoordinator:
    def __init__(
        self,
        session: "InvestigationSession",
        *,
        strict_instrumentation: bool = False,
        local_agent_id: Optional[str] = None,
    ) -> None:
        self.session = session
        self.strict_instrumentation = strict_instrumentation
        self.local_agent_id = local_agent_id
        self._runs: Dict[int, RunBarrierTracker] = {}
        self._session_paused = False
        self._pause_reason: Optional[str] = None
        self._replay_ledger()

    def _get_tracker(self, run_id: int) -> RunBarrierTracker:
        if run_id not in self._runs:
            self._runs[run_id] = RunBarrierTracker(run_id)
        return self._runs[run_id]

    def _replay_ledger(self) -> None:
        for msg in self.session.get_messages(limit=None):
            self.on_message(msg, replay=True)
        # sync signals are not persisted historically — state rebuilt from messages only

    @staticmethod
    def is_ready_envelope(envelope: MessageEnvelope) -> bool:
        text = envelope.natural_language or ""
        action = envelope.action
        if action in (ActionType.SYNC_READY, ActionType.REPORT_INSTRUMENTATION_READY):
            return True
        if action == ActionType.CHAT and re.search(r"\bREADY\b", text, re.IGNORECASE):
            return True
        return False

    def ready_response_for_envelope(self, envelope: MessageEnvelope) -> Optional[Dict[str, Any]]:
        """Barrier snapshot for an already-processed READY message (no state mutation)."""
        if not self.is_ready_envelope(envelope):
            return None
        text = envelope.natural_language or ""
        payload = envelope.payload or {}
        run_id = self._extract_run_id(text, payload)
        if run_id is None:
            return None
        try:
            state = self.get_barrier_state(run_id)
        except KeyError:
            return None
        return {
            "duplicate_ready": True,
            "barrier": state.model_dump(),
        }

    def _ready_response(self, tracker: RunBarrierTracker, duplicate: bool) -> Dict[str, Any]:
        state = tracker.to_state(self._session_paused, self._pause_reason)
        return {
            "duplicate_ready": duplicate,
            "barrier": state.model_dump(),
        }

    def on_message(self, envelope: MessageEnvelope, replay: bool = False) -> Optional[Dict[str, Any]]:
        text = envelope.natural_language or ""
        payload = envelope.payload or {}
        action = envelope.action
        role = detect_role(envelope.origin_sender_id or envelope.sender_id)

        if action == ActionType.CHAT:
            if re.search(r"\bPAUSED\b", text, re.IGNORECASE) and "UNPAUSE" not in text.upper():
                self._session_paused = True
                self._pause_reason = text[:200]
            if re.search(r"\bUNPAUSE\b", text, re.IGNORECASE):
                self._session_paused = False
                self._pause_reason = None

        run_id = self._extract_run_id(text, payload)
        if run_id is None:
            return None

        tracker = self._get_tracker(run_id)
        ready_result: Optional[Dict[str, Any]] = None

        if action == ActionType.PROPOSE_EXPERIMENT:
            if tracker.phase == BarrierPhase.IDLE:
                tracker.phase = BarrierPhase.PREPARING

        elif action in (ActionType.SYNC_READY, ActionType.REPORT_INSTRUMENTATION_READY):
            if action == ActionType.REPORT_INSTRUMENTATION_READY and role:
                inst = dict(payload)
                if "pid" not in inst:
                    pid_match = re.search(r"PID\s+(\d+)", text, re.IGNORECASE)
                    if pid_match:
                        inst["pid"] = int(pid_match.group(1))
                sender_id = envelope.origin_sender_id or envelope.sender_id
                is_local = (
                    self.local_agent_id is not None
                    and sender_id == self.local_agent_id
                )
                validation = validate_instrumentation_payload(
                    inst,
                    strict=self.strict_instrumentation and is_local,
                    validate_local_process=is_local,
                )
                inst["validation"] = {
                    "ok": validation["ok"],
                    "reason": validation["reason"],
                }
                tracker.instrumentation[role] = inst
                if validation["ok"] or not self.strict_instrumentation:
                    duplicate = tracker.mark_ready(role)
                    ready_result = self._ready_response(tracker, duplicate)
            elif role:
                duplicate = tracker.mark_ready(role)
                ready_result = self._ready_response(tracker, duplicate)

        elif action == ActionType.START_RUN or re.search(r"START\s+RUN", text, re.IGNORECASE):
            tracker.phase = BarrierPhase.RUNNING

        elif action in (ActionType.END_RUN, ActionType.REPORT_RESULT):
            tracker.phase = BarrierPhase.COMPLETED

        elif action in (ActionType.ABORT_RUN, ActionType.REPORT_FAILURE):
            tracker.phase = BarrierPhase.ABORTED

        elif action == ActionType.CHAT:
            if re.search(r"\bREADY\b", text, re.IGNORECASE) and role:
                duplicate = tracker.mark_ready(role)
                ready_result = self._ready_response(tracker, duplicate)

        tracker.touch()
        return ready_result

    def on_sync_signal(self, signal: SyncRunSignal) -> Optional[Dict[str, Any]]:
        tracker = self._get_tracker(signal.run_id)
        signal_data = signal.model_dump()
        tracker.last_signals.append(signal_data)
        tracker.last_signals = tracker.last_signals[-10:]

        phase = signal.phase.lower()
        role = detect_role(signal.sender_id)

        if phase in ("prepare", "preparing", "propose"):
            tracker.phase = BarrierPhase.PREPARING
        elif phase == "ready" and role:
            duplicate = tracker.mark_ready(role)
            tracker.touch()
            return self._ready_response(tracker, duplicate)
        elif phase == "start":
            tracker.phase = BarrierPhase.RUNNING
        elif phase in ("stop", "end", "complete", "completed"):
            tracker.phase = BarrierPhase.COMPLETED
        elif phase == "abort":
            tracker.phase = BarrierPhase.ABORTED

        tracker.touch()
        return None

    def get_barrier_state(self, run_id: int) -> BarrierState:
        run = self.session.get_run(run_id)
        if run_id not in self._runs and not run:
            raise KeyError(f"Run {run_id} not found")
        tracker = self._get_tracker(run_id)
        return tracker.to_state(self._session_paused, self._pause_reason)

    def get_session_pause(self) -> Optional[str]:
        return self._pause_reason if self._session_paused else None

    @staticmethod
    def _extract_run_id(text: str, payload: Dict[str, Any]) -> Optional[int]:
        if "run_id" in payload:
            try:
                return int(payload["run_id"])
            except (ValueError, TypeError):
                pass
        m = re.search(
            r"(?:START\s+RUN|RUN\s+IN\s+PROGRESS|ABORT\s+RUN|START\s+Run|Run\s*#?|run\s*#?)\s*(\d+)",
            text,
            re.IGNORECASE,
        )
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
        if "experiment" in payload and isinstance(payload["experiment"], dict):
            exp_run = payload["experiment"].get("run_id")
            if exp_run is not None:
                try:
                    return int(exp_run)
                except (ValueError, TypeError):
                    pass
        return None
