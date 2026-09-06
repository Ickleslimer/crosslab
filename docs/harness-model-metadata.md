# Harness model metadata contract

CrossLab peers can see each other's harness and model after handshake via `AgentCard.metadata.agent_profile` / `AgentPeer.metadata.agent_profile`.

## Why this exists

Some harnesses (Codex, OpenCode CLI, Cursor CLI, experimental Cursor IDE) expose a readable default-model config. Others — notably **Antigravity**, **Claude Desktop**, and **OpenCode Desktop** — do not publish a stable, documented “currently selected model” file. For those, CrossLab relies on self-report:

- Environment: `CROSSLAB_HARNESS`, `CROSSLAB_AGENT_MODEL`, `CROSSLAB_AGENT_MODEL_DISPLAY`
- MCP: `crosslab_set_agent_profile`
- Desktop Setup Wizard: **Agent profile (optional)**

## Desired vendor surface

Harnesses that want automatic peer visibility should expose the active identity in this shape:

```json
{
  "agent_profile": {
    "harness": "antigravity",
    "model_id": "gemini-flash",
    "model_display": "Gemini Flash",
    "source": "harness",
    "confidence": 1.0
  }
}
```

Preferred delivery (in order):

1. **MCP `initialize` metadata** — include `agent_profile` under server info or capabilities so CrossLab can copy it into the local node profile without scraping private files.
2. **Documented settings JSON** — a stable path and schema CrossLab can read read-only (same confidence model as Tier A config probes).
3. **Handshake / Agent Card** — if the harness speaks A2A directly, put `agent_profile` on the Agent Card `metadata` object (CrossLab already propagates this key).

## CrossLab behavior today

| Source | `source` field | Confidence |
|--------|----------------|------------|
| Wizard / MCP `set_agent_profile` / REST PUT | `manual` | 1.0 |
| Env vars | `env` | 1.0 |
| Codex / OpenCode / Cursor CLI config | `config_file` | 0.9 |
| Cursor IDE `state.vscdb` (opt-in) | `cursor_ide` | 0.7 |

Manual and env always beat probes. Ambiguous multi-config installs require `CROSSLAB_HARNESS`.

## Antigravity MCP install

CrossLab writes Antigravity MCP config to the official Gemini path:

`~/.gemini/config/mcp_config.json`

under `mcpServers.crosslab`. Older installs may still have `~/.antigravity/mcp.json` — remove that stale file after migrating.
