"""
Human operator runbook coordination from structured A2A messages.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from pydantic import BaseModel, Field

from crosslab.protocol.actions import ActionType
from crosslab.protocol.models import MessageEnvelope, utc_now_iso

if TYPE_CHECKING:
    from crosslab.engine.session import InvestigationSession


class RunbookStep(BaseModel):
    role: str = "both"
    instruction: str


class RunbookItem(BaseModel):
    message_id: str
    run_id: Optional[int] = None
    title: str
    steps: List[RunbookStep] = Field(default_factory=list)
    status: str = "pending"  # pending | completed
    source: str = "structured"  # structured | chat_fallback
    created_at: str = ""
    completed_at: Optional[str] = None


class RunbookState(BaseModel):
    pending: List[RunbookItem] = Field(default_factory=list)
    completed: List[RunbookItem] = Field(default_factory=list)


class RunbookCoordinator:
    def __init__(self, session: "InvestigationSession") -> None:
        self.session = session

    def get_runbook(self, run_id: Optional[int] = None) -> RunbookState:
        messages = self.session.get_messages(limit=None)
        items: List[RunbookItem] = []
        acked: set[str] = set()

        for msg in messages:
            if msg.action == ActionType.HUMAN_SIGNAL:
                ack_id = (msg.payload or {}).get("ack_message_id")
                if ack_id:
                    acked.add(ack_id)

        for msg in messages:
            if msg.action == ActionType.HUMAN_REPRO_REQUEST:
                payload = msg.payload or {}
                item_run_id = payload.get("run_id")
                if run_id is not None and item_run_id != run_id:
                    continue
                steps = [RunbookStep(**s) for s in payload.get("steps", [])]
                items.append(RunbookItem(
                    message_id=msg.message_id,
                    run_id=item_run_id,
                    title=payload.get("title", "Reproduction steps"),
                    steps=steps,
                    status="completed" if msg.message_id in acked else "pending",
                    source="structured",
                    created_at=msg.timestamp,
                ))
            elif msg.action == ActionType.CHAT and self._is_unpause_repro(msg):
                parsed = self._parse_chat_repro(msg)
                if parsed:
                    item_run_id = parsed.get("run_id")
                    if run_id is not None and item_run_id != run_id:
                        continue
                    items.append(RunbookItem(
                        message_id=msg.message_id,
                        run_id=item_run_id,
                        title=parsed.get("title", "Reproduction steps (from chat)"),
                        steps=[RunbookStep(role="both", instruction=s) for s in parsed.get("steps", [])],
                        status="completed" if msg.message_id in acked else "pending",
                        source="chat_fallback",
                        created_at=msg.timestamp,
                    ))

        pending = [i for i in items if i.status == "pending"]
        completed = [i for i in items if i.status == "completed"]
        return RunbookState(pending=pending, completed=completed)

    @staticmethod
    def _is_unpause_repro(msg: MessageEnvelope) -> bool:
        text = (msg.natural_language or "").upper()
        return "UNPAUSE" in text and ("STEP" in text or re.search(r"\(\d+\)", msg.natural_language or ""))

    @staticmethod
    def _parse_chat_repro(msg: MessageEnvelope) -> Optional[Dict[str, Any]]:
        text = msg.natural_language or ""
        steps = re.findall(r"\(\d+\)\s*([^\n(]+)", text)
        if not steps:
            return None
        run_match = re.search(r"RUN\s*#?\s*(\d+)", text, re.IGNORECASE)
        return {
            "run_id": int(run_match.group(1)) if run_match else None,
            "title": "UNPAUSE reproduction steps",
            "steps": [s.strip() for s in steps],
        }
