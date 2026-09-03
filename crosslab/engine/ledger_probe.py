"""
Ledger consistency probe — compare message IDs between local and peer nodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from crosslab.protocol.models import MessageEnvelope, ReconcileRequest


DISPLAY_ID_LIMIT = 20


@dataclass
class LedgerDiff:
    local_url: str
    peer_url: str
    local_count: int
    peer_count: int
    common_count: int
    only_local: List[str] = field(default_factory=list)
    only_peer: List[str] = field(default_factory=list)
    ok: bool = True
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "local_url": self.local_url,
            "peer_url": self.peer_url,
            "local_count": self.local_count,
            "peer_count": self.peer_count,
            "common_count": self.common_count,
            "only_local_count": len(self.only_local),
            "only_peer_count": len(self.only_peer),
            "only_local": self.only_local[:DISPLAY_ID_LIMIT],
            "only_peer": self.only_peer[:DISPLAY_ID_LIMIT],
            "ok": self.ok,
            "error": self.error,
        }


async def fetch_message_ids(base_url: str, timeout: float = 10.0) -> List[str]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        res = await client.get(f"{base_url.rstrip('/')}/v1/a2a/messages", params={"limit": 100000})
        res.raise_for_status()
        return [m["message_id"] for m in res.json() if m.get("message_id")]


async def reconcile_missing_ids(
    local_url: str,
    peer_url: str,
    known_ids: List[str],
    agent_id: str = "probe-ledger",
    session_id: str = "default",
) -> List[str]:
    req = ReconcileRequest(
        agent_id=agent_id,
        session_id=session_id,
        known_message_ids=known_ids,
    )
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.post(
            f"{peer_url.rstrip('/')}/v1/a2a/sync/reconcile",
            json=req.model_dump(),
        )
        res.raise_for_status()
        data = res.json()
        return [m["message_id"] for m in data.get("missing_messages", []) if m.get("message_id")]


async def compare_ledgers(
    local_url: str,
    peer_url: str,
    *,
    agent_id: str = "probe-ledger",
    session_id: str = "default",
) -> LedgerDiff:
    local_url = local_url.rstrip("/")
    peer_url = peer_url.rstrip("/")
    try:
        local_ids = await fetch_message_ids(local_url)
        peer_ids = await fetch_message_ids(peer_url)
    except Exception as exc:
        try:
            local_ids = await fetch_message_ids(local_url)
            peer_only = await reconcile_missing_ids(local_url, peer_url, local_ids, agent_id, session_id)
            local_only: List[str] = []
            # reverse reconcile not available without peer calling us — partial diff
            return LedgerDiff(
                local_url=local_url,
                peer_url=peer_url,
                local_count=len(local_ids),
                peer_count=len(local_ids) + len(peer_only),
                common_count=len(local_ids),
                only_local=local_only,
                only_peer=peer_only,
                ok=len(peer_only) == 0,
                error=f"peer GET failed, used reconcile fallback: {exc}",
            )
        except Exception as inner:
            return LedgerDiff(
                local_url=local_url,
                peer_url=peer_url,
                local_count=0,
                peer_count=0,
                common_count=0,
                ok=False,
                error=str(inner),
            )

    local_set = set(local_ids)
    peer_set = set(peer_ids)
    only_local = sorted(local_set - peer_set)
    only_peer = sorted(peer_set - local_set)
    return LedgerDiff(
        local_url=local_url,
        peer_url=peer_url,
        local_count=len(local_set),
        peer_count=len(peer_set),
        common_count=len(local_set & peer_set),
        only_local=only_local,
        only_peer=only_peer,
        ok=not only_local and not only_peer,
    )


async def fix_ledger_from_peer(
    local_url: str,
    peer_url: str,
    *,
    agent_id: str = "probe-ledger",
    session_id: str = "default",
) -> int:
    """Pull missing messages from peer into local node via reconcile + POST."""
    local_ids = await fetch_message_ids(local_url)
    missing_raw = await reconcile_missing_ids(local_url, peer_url, local_ids, agent_id, session_id)
    if not missing_raw:
        return 0

    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.post(
            f"{peer_url.rstrip('/')}/v1/a2a/sync/reconcile",
            json=ReconcileRequest(
                agent_id=agent_id,
                session_id=session_id,
                known_message_ids=local_ids,
            ).model_dump(),
        )
        res.raise_for_status()
        missing_messages = res.json().get("missing_messages", [])

    ingested = 0
    async with httpx.AsyncClient(timeout=10.0) as client:
        for m_data in missing_messages:
            env = MessageEnvelope(**m_data)
            post = await client.post(
                f"{local_url.rstrip('/')}/v1/a2a/messages",
                json=env.model_dump(),
            )
            if post.status_code == 200:
                ingested += 1
    return ingested
