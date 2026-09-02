"""
Per-session harness thread ID manifest for cross-harness continuity.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from crosslab.protocol.models import utc_now_iso

VALID_HARNESSES = ("antigravity", "codex", "opencode", "cursor")


class HarnessLinks(BaseModel):
    antigravity: Optional[str] = None
    codex: Optional[str] = None
    opencode: Optional[str] = None
    cursor: Optional[str] = None
    notes: Optional[str] = None
    updated_at: str = Field(default_factory=utc_now_iso)

    def set_link(self, harness: str, thread_id: str) -> None:
        harness = harness.lower().replace("_", "-")
        if harness not in VALID_HARNESSES:
            raise ValueError(f"Unknown harness '{harness}'. Choose from: {', '.join(VALID_HARNESSES)}")
        setattr(self, harness.replace("-", "_"), thread_id)
        self.updated_at = utc_now_iso()

    def get_link(self, harness: str) -> Optional[str]:
        harness = harness.lower().replace("_", "-")
        if harness not in VALID_HARNESSES:
            return None
        return getattr(self, harness.replace("-", "_"), None)


def manifest_path_for_data_dir(data_dir: str) -> Path:
    return Path(data_dir) / "harness_links.json"


def load_harness_links(data_dir: str) -> HarnessLinks:
    path = manifest_path_for_data_dir(data_dir)
    if not path.exists():
        return HarnessLinks()
    with open(path, encoding="utf-8") as f:
        return HarnessLinks(**json.load(f))


def save_harness_links(data_dir: str, links: HarnessLinks) -> Path:
    path = manifest_path_for_data_dir(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    links.updated_at = utc_now_iso()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(links.model_dump(), f, indent=2)
        f.write("\n")
    return path


def data_dir_from_db_path(db_path: str) -> str:
    return str(Path(db_path).resolve().parent)
