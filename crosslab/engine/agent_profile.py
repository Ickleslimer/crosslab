"""
Per-session agent identity (harness + model) for peer visibility.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from crosslab.protocol.models import utc_now_iso


class AgentProfile(BaseModel):
    harness: Optional[str] = None
    model_id: Optional[str] = None
    model_display: Optional[str] = None
    source: str = "unset"
    confidence: float = 0.0
    updated_at: str = Field(default_factory=utc_now_iso)

    def is_set(self) -> bool:
        return bool(self.harness or self.model_id or self.model_display)

    def apply_manual(
        self,
        *,
        harness: Optional[str] = None,
        model_id: Optional[str] = None,
        model_display: Optional[str] = None,
    ) -> None:
        if harness is not None:
            self.harness = harness or None
        if model_id is not None:
            self.model_id = model_id or None
        if model_display is not None:
            self.model_display = model_display or None
        self.source = "manual"
        self.confidence = 1.0
        self.updated_at = utc_now_iso()


def profile_path_for_data_dir(data_dir: str) -> Path:
    return Path(data_dir) / "agent_profile.json"


def load_agent_profile(data_dir: str) -> AgentProfile:
    path = profile_path_for_data_dir(data_dir)
    if not path.exists():
        return AgentProfile()
    with open(path, encoding="utf-8") as f:
        return AgentProfile(**json.load(f))


def save_agent_profile(data_dir: str, profile: AgentProfile) -> Path:
    path = profile_path_for_data_dir(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    profile.updated_at = utc_now_iso()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile.model_dump(), f, indent=2)
        f.write("\n")
    return path


def profile_from_env() -> AgentProfile:
    harness = os.environ.get("CROSSLAB_HARNESS", "").strip() or None
    model_id = os.environ.get("CROSSLAB_AGENT_MODEL", "").strip() or None
    model_display = os.environ.get("CROSSLAB_AGENT_MODEL_DISPLAY", "").strip() or None
    if not (harness or model_id or model_display):
        return AgentProfile()
    return AgentProfile(
        harness=harness,
        model_id=model_id,
        model_display=model_display or model_id,
        source="env",
        confidence=1.0,
    )


def merge_profile(base: AgentProfile, override: AgentProfile) -> AgentProfile:
    """Merge override into base; override wins for non-empty fields."""
    data = base.model_dump()
    for key, value in override.model_dump().items():
        if key == "updated_at":
            continue
        if value is not None and value != "" and value != 0.0:
            data[key] = value
        elif key in ("harness", "model_id", "model_display") and override.is_set():
            if getattr(override, key) is not None:
                data[key] = getattr(override, key)
    merged = AgentProfile(**data)
    if override.source not in ("unset", ""):
        merged.source = override.source
    if override.confidence > 0:
        merged.confidence = override.confidence
    merged.updated_at = utc_now_iso()
    return merged


def resolve_local_profile(stored: AgentProfile) -> AgentProfile:
    """Apply precedence: manual stored > env > stored file > empty."""
    if stored.source == "manual" and stored.is_set():
        return stored
    env_profile = profile_from_env()
    if env_profile.is_set():
        return merge_profile(stored, env_profile)
    return stored if stored.is_set() else AgentProfile()


def format_profile_label(profile: AgentProfile) -> str:
    if not profile.is_set():
        return "Unknown"
    model = profile.model_display or profile.model_id or "Unknown model"
    if profile.harness:
        return f"{profile.harness} / {model}"
    return model


def peer_profile_from_metadata(metadata: Optional[dict]) -> Optional[AgentProfile]:
    if not metadata:
        return None
    raw = metadata.get("agent_profile")
    if not raw:
        return None
    try:
        profile = AgentProfile(**raw)
    except Exception:
        return None
    return profile if profile.is_set() else None
