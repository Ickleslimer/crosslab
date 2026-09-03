"""
Experimental Cursor IDE probe: read selected agent model from state.vscdb.

Read-only. Fail-open. Auto-apply is gated by CROSSLAB_PROBE_CURSOR_IDE.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from crosslab.engine.harness_probes.base import ProbeResult, display_name_for_model

APPLICATION_USER_KEY = (
    "src.vs.platform.reactivestorage.browser.reactiveStorageServiceImpl"
    ".persistentStorage.applicationUser"
)

MODE_PREFERENCE = ("composer", "agent", "background-composer")
IDE_CONFIDENCE = 0.7


def cursor_ide_enabled() -> bool:
    value = os.environ.get("CROSSLAB_PROBE_CURSOR_IDE", "").strip().lower()
    return value in ("1", "true", "yes")


def cursor_state_db_path() -> Path:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Cursor" / "User" / "globalStorage" / "state.vscdb"
        return Path.home() / "AppData" / "Roaming" / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Cursor"
            / "User"
            / "globalStorage"
            / "state.vscdb"
        )
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    return Path.home() / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb"


def _sqlite_uri(path: Path) -> str:
    resolved = path.resolve()
    as_posix = resolved.as_posix()
    if sys.platform == "win32" and len(as_posix) >= 2 and as_posix[1] == ":":
        as_posix = f"/{as_posix}"
    return f"file:{quote(as_posix, safe='/')}?mode=ro"


def _decode_value(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _extract_model_from_mode(mode_value: Any) -> Optional[str]:
    if isinstance(mode_value, str) and mode_value.strip():
        return mode_value.strip()
    if not isinstance(mode_value, dict):
        return None
    model_name = mode_value.get("modelName") or mode_value.get("model_id") or mode_value.get("modelId")
    if isinstance(model_name, str) and model_name.strip():
        return model_name.strip()
    selected = mode_value.get("selectedModels")
    if isinstance(selected, list) and selected:
        first = selected[0]
        if isinstance(first, str) and first.strip():
            return first.strip()
        if isinstance(first, dict):
            for key in ("modelId", "model_id", "id", "name", "modelName"):
                value = first.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


def extract_model_from_application_user(blob: Any) -> Optional[str]:
    if not isinstance(blob, dict):
        return None
    ai_settings = blob.get("aiSettings")
    if not isinstance(ai_settings, dict):
        return None
    model_config = ai_settings.get("modelConfig")
    if not isinstance(model_config, dict) or not model_config:
        return None

    for mode in MODE_PREFERENCE:
        model_id = _extract_model_from_mode(model_config.get(mode))
        if model_id:
            return model_id

    for mode, mode_value in model_config.items():
        model_id = _extract_model_from_mode(mode_value)
        if model_id:
            return model_id
    return None


def _read_application_user(db_path: Path) -> Optional[Any]:
    uri = _sqlite_uri(db_path)
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.execute("PRAGMA busy_timeout = 1000")
        row = conn.execute(
            "SELECT value FROM ItemTable WHERE key = ?",
            (APPLICATION_USER_KEY,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    text = _decode_value(row[0])
    if not text:
        return None
    return json.loads(text)


def _copy_db_sidecars(src: Path, dest_dir: Path) -> Path:
    dest = dest_dir / src.name
    shutil.copy2(src, dest)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(src) + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, dest_dir / sidecar.name)
    return dest


def _load_application_user(db_path: Path) -> Optional[Any]:
    try:
        return _read_application_user(db_path)
    except sqlite3.OperationalError:
        tmp_dir = tempfile.mkdtemp(prefix="crosslab-cursor-ide-")
        try:
            copied = _copy_db_sidecars(db_path, Path(tmp_dir))
            return _read_application_user(copied)
        except Exception:
            return None
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        return None


def probe_cursor_ide(db_path: Optional[Path] = None) -> Optional[ProbeResult]:
    path = db_path or cursor_state_db_path()
    if not path.exists():
        return None
    try:
        blob = _load_application_user(path)
        model_id = extract_model_from_application_user(blob)
    except Exception:
        return None
    if not model_id:
        return None
    return ProbeResult(
        harness="cursor",
        model_id=model_id,
        model_display=display_name_for_model(model_id),
        config_path=path,
        confidence=IDE_CONFIDENCE,
        source="cursor_ide",
    )
