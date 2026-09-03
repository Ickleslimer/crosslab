"""
Probe Codex default model from ~/.codex/config.toml.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from crosslab.engine.harness_probes.base import ProbeResult, display_name_for_model


def _default_codex_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


def _parse_toml_minimal(text: str) -> Dict[str, Any]:
    """Minimal TOML parser for top-level string keys (Python 3.10 fallback)."""
    result: Dict[str, Any] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r'^([A-Za-z0-9_-]+)\s*=\s*"(.*)"\s*$', stripped)
        if match:
            result[match.group(1)] = match.group(2)
            continue
        match = re.match(r"^([A-Za-z0-9_-]+)\s*=\s*'(.*)'\s*$", stripped)
        if match:
            result[match.group(1)] = match.group(2)
    return result


def _load_toml(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if sys.version_info >= (3, 11):
        import tomllib

        return tomllib.loads(text)
    return _parse_toml_minimal(text)


def probe_codex(config_path: Optional[Path] = None) -> Optional[ProbeResult]:
    path = config_path or _default_codex_path()
    if not path.exists():
        return None
    try:
        data = _load_toml(path)
    except Exception:
        return None

    model = data.get("model")
    if not model or not isinstance(model, str):
        return None

    model_id = model.strip()
    if not model_id:
        return None

    return ProbeResult(
        harness="codex",
        model_id=model_id,
        model_display=display_name_for_model(model_id),
        config_path=path,
    )
