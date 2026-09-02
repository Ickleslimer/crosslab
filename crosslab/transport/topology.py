"""
Network topology helpers for CrossLab peer endpoint validation.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from crosslab.protocol.models import AgentPeer


def is_loopback_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host in ("127.0.0.1", "localhost", "::1")


def topology_warning(local_machine: str, peer: AgentPeer) -> Optional[str]:
    if not is_loopback_url(peer.endpoint_url):
        return None
    peer_machine = (peer.machine_name or "").strip()
    local = (local_machine or "").strip()
    if peer_machine and local and peer_machine != local:
        return (
            f"Peer {peer.agent_id} advertises loopback URL {peer.endpoint_url} "
            f"from machine '{peer_machine}'; direct callbacks may fail across machines"
        )
    if peer_machine and local and peer_machine == local:
        return None
    return (
        f"Peer {peer.agent_id} advertises loopback URL {peer.endpoint_url}; "
        "callbacks may fail across machines"
    )
