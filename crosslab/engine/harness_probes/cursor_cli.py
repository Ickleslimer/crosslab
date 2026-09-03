"""
Probe Cursor CLI default model from ~/.cursor/cli-config.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from crosslab.engine.harness_probes.base import ProbeResult, display_name_for_model


def _default_cursor_cli_path() -> Path:
    return Path.home() / ".cursor" / "cli-config.json"


def _extract_model_field(model_value: Any) -> Optional[str]:
    if isinstance(model_value, str) and model_value.strip():
        return model_value.strip()
    if isinstance(model_value, dict):
        for key in ("modelId", "model_id", "id", "name", "model"):
            value = model_value.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def probe_cursor_cli(config_path: Optional[Path] = None) -> Optional[ProbeResult]:
    path = config_path or _default_cursor_cli_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    model_id = _extract_model_field(data.get("model"))
    if not model_id:
        return None

    return ProbeResult(
        harness="cursor",
        model_id=model_id,
        model_display=display_name_for_model(model_id),
        config_path=path,
    )
