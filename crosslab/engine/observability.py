"""
Session observability snapshot for first-run health checks.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from crosslab.engine.session import InvestigationSession


def _parse_timestamp(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _last_message_age_s(messages) -> Optional[float]:
    if not messages:
        return None
    newest = messages[-1]
    ts = _parse_timestamp(newest.timestamp or "")
    if ts is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())


def build_observability_report(session: "InvestigationSession", agent_id: str) -> Dict[str, Any]:
    db_path = session.storage.db_path
    transcript_enabled = session.storage.enable_transcript
    transcript_path = session.get_transcript_path()

    db_writable: Optional[bool] = None
    if db_path != ":memory:":
        parent = Path(db_path).resolve().parent
        db_writable = os.access(parent, os.W_OK)

    transcript_reachable = False
    if transcript_enabled:
        if transcript_path and Path(transcript_path).exists() and Path(transcript_path).stat().st_size > 0:
            transcript_reachable = True
        else:
            try:
                md = session.export_transcript_markdown()
                transcript_reachable = bool(md)
            except Exception:
                transcript_reachable = False

    messages = session.get_messages(limit=None)
    message_count = len(messages)
    last_message_age_s = _last_message_age_s(messages)

    peers = session.get_peers()
    peer_count = max(0, len(peers) - 1)

    critical_ok = True
    if db_path != ":memory:" and db_writable is False:
        critical_ok = False
    if transcript_enabled and not transcript_reachable:
        critical_ok = False

    report: Dict[str, Any] = {
        "session_id": session.session_id,
        "transcript_enabled": transcript_enabled,
        "transcript_reachable": transcript_reachable,
        "message_count": message_count,
        "last_message_age_s": last_message_age_s,
        "peer_count": peer_count,
        "ok": critical_ok,
    }
    if db_path != ":memory:":
        report["db_path"] = str(Path(db_path).resolve())
        report["db_writable"] = db_writable
    if transcript_path:
        report["transcript_path"] = transcript_path
    return report
