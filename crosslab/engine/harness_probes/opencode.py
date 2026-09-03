"""
Probe OpenCode CLI default model from ~/.config/opencode/opencode.json(c).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from crosslab.engine.harness_probes.base import ProbeResult, display_name_for_model


def _default_opencode_dir() -> Path:
    return Path.home() / ".config" / "opencode"


_CANDIDATE_FILES = ("opencode.json", "opencode.jsonc")


def _strip_jsonc_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    return text


def _extract_model_id(data: Any) -> Optional[str]:
    if isinstance(data, str) and data.strip():
        return data.strip()
    if isinstance(data, dict):
        for key in ("model", "default", "id", "name"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        provider = data.get("provider")
        model = data.get("model")
        if isinstance(provider, str) and isinstance(model, str):
            combined = f"{provider.strip()}/{model.strip()}"
            return combined
    return None


def _find_model_in_config(data: dict) -> Optional[str]:
    for key in ("model", "defaultModel", "default_model"):
        model_id = _extract_model_id(data.get(key))
        if model_id:
            return model_id

    provider = data.get("provider")
    if isinstance(provider, dict):
        model_id = _extract_model_id(provider.get("model") or provider.get("default"))
        if model_id:
            return model_id

    providers = data.get("providers")
    if isinstance(providers, dict):
        for entry in providers.values():
            if isinstance(entry, dict):
                model_id = _extract_model_id(entry.get("model") or entry.get("default"))
                if model_id:
                    return model_id
    return None


def probe_opencode(config_dir: Optional[Path] = None) -> Optional[ProbeResult]:
    base = config_dir or _default_opencode_dir()
    for name in _CANDIDATE_FILES:
        path = base / name
        if not path.exists():
            continue
        try:
            raw = path.read_text(encoding="utf-8")
            if name.endswith(".jsonc"):
                raw = _strip_jsonc_comments(raw)
            data = json.loads(raw)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        model_id = _find_model_in_config(data)
        if not model_id:
            continue
        return ProbeResult(
            harness="opencode",
            model_id=model_id,
            model_display=display_name_for_model(model_id.split("/")[-1]),
            config_path=path,
        )
    return None
