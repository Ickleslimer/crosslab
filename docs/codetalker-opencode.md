# CodeTalker and OpenCode Session Indexing

CrossLab agents often use [CodeTalker](https://github.com/) to read each other's harness conversation threads. OpenCode desktop sessions are **not** automatically indexed by CodeTalker today, which causes friction when agents try to discover peer threads (friction study E025, E022).

## OpenCode session storage

OpenCode desktop stores session metadata locally:

| Platform | Default path |
|----------|--------------|
| Windows | `%APPDATA%\ai.opencode.desktop` |
| macOS | `~/Library/Application Support/ai.opencode.desktop` |
| Linux | `~/.config/ai.opencode.desktop` |

Session IDs and project associations live under these directories. A CrossLab investigation thread may be filed under an unrelated project folder if the workspace root differed when the session started.

## CrossLab harness manifest workaround

CrossLab records external harness thread IDs in `harness_links.json` (alongside the session database). Use this when CodeTalker cannot find the OpenCode thread by project name alone.

### Desktop Setup Wizard

When starting a session, optional fields let you paste harness thread IDs including **OpenCode**.

### MCP tools

```text
crosslab_set_harness_link(harness="opencode", thread_id="<session-id>")
crosslab_get_harness_links()
crosslab_get_transcript(harness="opencode")  # returns linked thread ID + CodeTalker hint
```

### REST API

```http
GET  /v1/a2a/session/manifest
PUT  /v1/a2a/session/manifest
```

Example manifest:

```json
{
  "opencode": "abc123-session-id",
  "antigravity": "28a6fca6-...",
  "notes": "OpenCode thread for CrossLab coordination"
}
```

## Operator workflow when CodeTalker cannot find a thread

1. Open the OpenCode session that is running CrossLab MCP.
2. Copy the session or thread ID from the OpenCode UI (or inspect `%APPDATA%\ai.opencode.desktop` metadata).
3. Paste the ID into the CrossLab desktop Setup Wizard **OpenCode** field, or call `crosslab_set_harness_link`.
4. Tell the peer agent: `crosslab_get_transcript(harness="opencode")` to retrieve the linked ID.
5. Use CodeTalker with the explicit session ID rather than searching by project name.

## Upstream tooling gap

Indexing OpenCode desktop sessions in CodeTalker is an **external** feature request. Desired capabilities:

- Index `%APPDATA%/ai.opencode.desktop` (and macOS/Linux equivalents) session metadata.
- Accept an optional `--session-export` path for manual session dumps.
- Cross-reference CrossLab `harness_links.json` `opencode` field when resolving threads.

CrossLab does not fetch OpenCode transcripts directly; it only stores the link for agent and operator reference.
