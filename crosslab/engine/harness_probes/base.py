"""
Shared types and helpers for harness config probes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from crosslab.engine.agent_profile import AgentProfile

MODEL_DISPLAY_NAMES = {
    "gpt-5.6-sol": "GPT Sol 5.6",
    "composer-2.5": "Composer 2.5",
    "claude-sonnet-4": "Claude Sonnet 4",
}


def display_name_for_model(model_id: str) -> str:
    return MODEL_DISPLAY_NAMES.get(model_id, model_id)


@dataclass
class ProbeResult:
    harness: str
    model_id: str
    model_display: str
    config_path: Path
    confidence: float = 0.9

    def to_agent_profile(self) -> AgentProfile:
        return AgentProfile(
            harness=self.harness,
            model_id=self.model_id,
            model_display=self.model_display,
            source="config_file",
            confidence=self.confidence,
        )

    def to_dict(self) -> dict:
        return {
            "harness": self.harness,
            "model_id": self.model_id,
            "model_display": self.model_display,
            "config_path": str(self.config_path),
            "confidence": self.confidence,
        }


def normalize_harness_hint(harness_hint: Optional[str]) -> Optional[str]:
    if not harness_hint:
        return None
    hint = harness_hint.strip().lower().replace("_", "-")
    if hint == "cursor-cli":
        return "cursor"
    return hint
