"""
CrossLab environment diagnostics.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from crosslab.transport.topology import is_loopback_url
from crosslab.mcp.server import CrossLabMCPServer


async def run_doctor(
    node_url: str = "http://127.0.0.1:8765",
    session_id: str = "default",
    *,
    observability: bool = False,
) -> Dict[str, Any]:
    results: Dict[str, Any] = {
        "node_url": node_url,
        "checks": [],
        "ok": True,
    }

    def add_check(name: str, ok: bool, detail: str) -> None:
        results["checks"].append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            results["ok"] = False

    # 1. Node health
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(f"{node_url.rstrip('/')}/health")
            if res.status_code == 200:
                health = res.json()
                add_check("node_health", True, f"Agent {health.get('agent_id')} role={health.get('role')}")
                advertised = health.get("advertised_url", node_url)
                if not health.get("advertised_reachable_externally", True):
                    add_check(
                        "advertised_url",
                        False,
                        f"Node advertises loopback URL {advertised}; remote peers cannot callback",
                    )
                else:
                    add_check("advertised_url", True, f"Advertised URL: {advertised}")

                peers = health.get("peers", [])
                add_check("peer_count", True, f"{len(peers)} peer(s) registered")
                for peer in peers:
                    warning = peer.get("topology_warning")
                    if warning:
                        add_check(
                            f"peer_topology:{peer.get('agent_id')}",
                            False,
                            warning,
                        )
            else:
                add_check("node_health", False, f"HTTP {res.status_code}")
    except Exception as e:
        add_check("node_health", False, str(e))

    # 2. MCP tools
    try:
        server = CrossLabMCPServer(node_url=node_url)
        tools = server.get_tool_definitions()
        names = [t["name"] for t in tools]
        required = {"crosslab_send_chat", "crosslab_wait_for_message", "crosslab_get_run_state"}
        missing = required - set(names)
        if missing:
            add_check("mcp_tools", False, f"Missing tools: {', '.join(sorted(missing))}")
        else:
            add_check("mcp_tools", True, f"{len(tools)} MCP tools registered")
    except Exception as e:
        add_check("mcp_tools", False, str(e))

    # 3. Session summary (optional)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(f"{node_url.rstrip('/')}/v1/a2a/summary")
            if res.status_code == 200:
                summary = res.json()
                add_check(
                    "session",
                    True,
                    f"session={summary.get('session_id', session_id)} runs={summary.get('total_runs', 0)}",
                )
    except Exception:
        pass

    if observability:
        base = node_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                transcript_res = await client.get(f"{base}/v1/a2a/transcript")
                add_check(
                    "transcript_endpoint",
                    transcript_res.status_code == 200,
                    f"GET /v1/a2a/transcript HTTP {transcript_res.status_code}",
                )

                obs_res = await client.get(f"{base}/v1/a2a/observability")
                if obs_res.status_code == 200:
                    obs = obs_res.json()
                    add_check(
                        "transcript_file",
                        obs.get("transcript_reachable", False),
                        obs.get("transcript_path") or "transcript not reachable",
                    )
                    add_check(
                        "db_writable",
                        obs.get("db_writable", True),
                        obs.get("db_path", "in-memory"),
                    )
                    msg_count = obs.get("message_count", 0)
                    last_age = obs.get("last_message_age_s")
                    age_detail = f"{msg_count} message(s)"
                    if last_age is not None:
                        age_detail += f", last {last_age:.0f}s ago"
                    stale = last_age is not None and last_age > 3600 and msg_count > 0
                    add_check(
                        "message_activity",
                        not stale,
                        age_detail + (" (stale >1h)" if stale else ""),
                    )
                    peer_count = obs.get("peer_count", 0)
                    add_check(
                        "observability_peer_count",
                        peer_count > 0,
                        f"{peer_count} remote peer(s)",
                    )
                else:
                    add_check("observability", False, f"HTTP {obs_res.status_code}")
        except Exception as e:
            add_check("observability", False, str(e))

    return results
