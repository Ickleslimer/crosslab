"""
MCP harness config generation and installation helpers.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

SUPPORTED_HARNESSES = ("cursor", "claude-desktop", "antigravity", "codex", "opencode")

POST_INSTALL_HINTS: Dict[str, str] = {
    "cursor": "Paste into Cursor Settings → MCP, or merge into ~/.cursor/mcp.json. Restart Cursor.",
    "claude-desktop": "Merge into %APPDATA%\\Claude\\claude_desktop_config.json. Restart Claude Desktop.",
    "antigravity": "Add to Antigravity MCP server settings. Restart the agent session.",
    "codex": "Add to Codex MCP configuration (Settings → MCP). Restart Codex.",
    "opencode": "Add to OpenCode MCP config. Restart OpenCode desktop.",
}


def _crosslab_server_entry(node_url: str, project_root: Optional[str] = None) -> Dict[str, Any]:
    args = ["run", "crosslab", "mcp", "--node-url", node_url]
    if project_root:
        args = ["run", "--directory", project_root, "crosslab", "mcp", "--node-url", node_url]
    return {
        "command": "uv",
        "args": args,
        "env": {
            "CROSSLAB_NODE_URL": node_url,
        },
    }


def render_config(
    harness: str,
    node_url: str = "http://127.0.0.1:8765",
    project_root: Optional[str] = None,
) -> Dict[str, Any]:
    harness = harness.lower()
    if harness not in SUPPORTED_HARNESSES:
        raise ValueError(f"Unsupported harness '{harness}'. Choose from: {', '.join(SUPPORTED_HARNESSES)}")

    entry = _crosslab_server_entry(node_url, project_root)

    if harness == "antigravity":
        return {"crosslab": entry}

    return {"mcpServers": {"crosslab": entry}}


def get_install_path(harness: str) -> Path:
    harness = harness.lower()
    home = Path.home()
    if harness == "cursor":
        return home / ".cursor" / "mcp.json"
    if harness == "claude-desktop":
        appdata = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    if harness == "antigravity":
        return home / ".antigravity" / "mcp.json"
    if harness == "codex":
        return home / ".codex" / "mcp.json"
    if harness == "opencode":
        appdata = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
        return Path(appdata) / "ai.opencode.desktop" / "mcp.json"
    raise ValueError(f"Unsupported harness '{harness}'")


def merge_config(existing: Dict[str, Any], rendered: Dict[str, Any], harness: str) -> Dict[str, Any]:
    harness = harness.lower()
    merged = dict(existing) if existing else {}
    if harness == "antigravity":
        merged.update(rendered)
        return merged
    servers = dict(merged.get("mcpServers", {}))
    servers.update(rendered.get("mcpServers", {}))
    merged["mcpServers"] = servers
    return merged


def write_config(path: Path, config: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


def post_install_hint(harness: str, path: Path) -> str:
    return f"{POST_INSTALL_HINTS.get(harness, 'Restart your harness after updating MCP config.')} Path: {path}"
