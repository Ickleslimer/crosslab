# CrossLab: Multi-Machine Agent-to-Agent (A2A) Empirical Collaboration Layer

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![A2A 1.0 Ready](https://img.shields.io/badge/A2A-1.0%20Ready-blueviolet.svg)](https://a2a-protocol.org)

**CrossLab** is an open collaboration layer that allows **independent AI coding agents running on different physical or virtual machines to work together on empirical debugging problems**.

Rather than giving one agent remote control or unrestricted shell access over every machine, each agent remains sovereign over its own local environment. The agents communicate over the **Agent-to-Agent (A2A)** protocol, exchanging natural-language reasoning, structured hypotheses, synchronized experiment plans, high-resolution telemetry, multi-machine correlated logs, and patches.

---

## 🎯 Architecture & A2A Protocol Layering

CrossLab is structured as an empirical investigation application protocol cleanly layered on top of A2A transport and discovery primitives:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        AI Coding Agents                                │
│       (Antigravity / Claude Code / Codex / Gemini / Cursor)            │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ MCP / Python SDK
┌──────────────────────────────────▼─────────────────────────────────────┐
│                      CrossLab Application Layer                         │
│  ├── Hypotheses & Evidence Graphs (Derivations, Supports, Contradicts) │
│  ├── Synchronized Experiment Coordinator & Barrier Sync                │
│  ├── Pluggable Correlation Engine (Temporal, Sequence, Request/Resp)   │
│  └── First-Class Time Uncertainty Engine (Monotonic ns, +/-Delta_t)    │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ Application Messages & Runs
┌──────────────────────────────────▼─────────────────────────────────────┐
│                       A2A 1.0 Transport Layer                          │
│  ├── Canonical Agent Cards (/.well-known/agent-card.json)              │
│  ├── Peer Discovery & Handshake Protocol                               │
│  ├── Multi-Hop Network Message Relay & Loop Prevention                 │
│  └── Real-Time SSE Streams & Ping/Pong Clock Offset Measurement        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 🔬 Multi-Machine Investigation Model

```text
Machine A / Host (Port 8765)           Machine B / Client (Port 8766)
       │                                              │
   Host Agent              ←──── A2A ────→        Client Agent
       │                                              │
   FEAR 3 host                                    FEAR 3 client
   receive watchdog (5000ms)                      Steam send queue
   packet receipt telemetry                       UI disconnect listener
   local patches                                  local patches
```

### Collaborative Investigation Flow:
1. **Discovery & Handshake**: Nodes discover peer capabilities via A2A Agent Cards (`/.well-known/agent-card.json`) and measure RTT clock offset.
2. **Conversational Reasoning**: Agents communicate in natural language over the real network via local MCP/Client bridges.
3. **Evidence Graphs**: Formulate hypotheses with explicit evidence links (`SUPPORTS`, `CONTRADICTS`, `QUALIFIES`) and agent-assessed confidence scores.
4. **Experiment Proposal & Agreement**: Propose and agree upon dual-role experimental conditions.
5. **Zero-Trust Local Execution**: No remote shell execution. Local agents independently apply non-intrusive instrumentation probes.
6. **Barrier-Synchronized Runs**: Coordinate `ready` -> `start` -> `stop` execution windows.
7. **Pluggable Correlation**: The Correlation Engine runs pluggable analyzers (`TemporalAnalyzer`, `PacketSequenceAnalyzer`, `RequestResponseAnalyzer`, and domain-specific rules like `Fear3CoopAnalyzer`) computing scientific intervals:
   > *"Client sent packet #8835 18.2 ms [±2.0 ms uncertainty] before host 5000ms silence watchdog triggered disconnect ('connection_lost')."*
8. **Patch Exchange**: Agents formulate, share, and review unified patches (`fear3_keepalive_probe.patch`).

---

## 🚀 Quick Start

### 1. Installation

```powershell
git clone https://github.com/Ickleslimer/crosslab.git
cd crosslab
uv sync --all-extras
```

### 2. Run the Full Test Suite

```powershell
uv run pytest -v
```

Includes the genuine two-node distributed integration test:
```powershell
uv run pytest tests/test_distributed_network.py -v
```

### 3. Run the FEAR 3 Multi-Agent Demonstration

```powershell
uv run crosslab demo fear3
```

### 4. Start Distributed Nodes on Separate Machines / Ports

**Machine A (Host):**
```powershell
uv run crosslab node --role host --port 8765 --session fear3-debug
```

**Machine B (Client — connects to Host):**
```powershell
uv run crosslab node --role client --port 8766 --peer http://machine-a:8765 --session fear3-debug
```

### 5. Desktop App (Tauri + Svelte)

CrossLab ships a bundled desktop app for Windows with the same Host/Client flow, a native investigation HUD, and optional Classic HUD (legacy web dashboard).

**Development:**
```powershell
cd desktop
npm install
npm run tauri:dev
```

**Release build (bundles Python node sidecar):**
```powershell
uv sync --all-extras
.\scripts\build_sidecar.ps1
cd desktop
npm install
npm run tauri:build
```

The installer is written to `desktop/src-tauri/target/release/bundle/`.

**Desktop workflow:**
1. Launch CrossLab on Machine A → choose **Host**, set session ID (e.g. `fear3-debug`), start session.
2. Copy the LAN URL shown in the setup wizard.
3. Launch CrossLab on Machine B → choose **Client**, enter the host peer URL, same session ID, start session.
4. Use the HUD for chat, hypotheses, runs, and transcripts. Click **Classic HUD** to open the original web dashboard in a second window.
5. Connect your agent's MCP bridge to `http://127.0.0.1:{port}` (see README MCP section).

---

## 🤖 MCP (Model Context Protocol) Server

CrossLab provides an MCP server connecting AI coding agents directly to the live A2A node network:

```powershell
uv run crosslab mcp --node-url http://127.0.0.1:8765
```

### MCP install and doctor

Generate harness-specific MCP config (paste-ready JSON or write to the harness config file):

```powershell
# Print config for Cursor
uv run crosslab mcp install --harness cursor --node-url http://127.0.0.1:8765

# Write merged config for Claude Desktop
uv run crosslab mcp install --harness claude-desktop --write

# Validate node + MCP tool registration
uv run crosslab doctor --node-url http://127.0.0.1:8765

# First-run observability checklist (transcript, DB, peers, message age)
uv run crosslab doctor --observability --node-url http://127.0.0.1:8765

# Compare local vs peer message ledgers before a coordinated run
uv run crosslab probe-ledger --node-url http://127.0.0.1:8766 --peer http://192.168.1.10:8765
```

Supported harnesses: `cursor`, `claude-desktop`, `antigravity`, `codex`, `opencode`.

### Agent profile (harness + model visibility)

Peers can see each other's harness and model after handshake. Set identity via environment variables, REST, or MCP:

```powershell
# Environment (applied on node startup)
$env:CROSSLAB_HARNESS = "codex"
$env:CROSSLAB_AGENT_MODEL = "gpt-5.6-sol"
$env:CROSSLAB_AGENT_MODEL_DISPLAY = "GPT Sol 5.6"

# REST
# GET  /v1/a2a/session/profile
# PUT  /v1/a2a/session/profile  {"harness":"codex","model_display":"GPT Sol 5.6"}

# MCP (at session start)
# crosslab_set_agent_profile(harness="codex", model_display="GPT Sol 5.6")
# crosslab_get_peer_profiles()
```

`mcp install --harness codex` pre-fills `CROSSLAB_HARNESS` in the generated MCP env block.

**Auto-detect (Tier A):** On node startup, CrossLab probes local config files when no manual/env profile is set:

| Harness | Config file |
|---------|-------------|
| Codex | `~/.codex/config.toml` |
| OpenCode CLI | `~/.config/opencode/opencode.json(c)` |
| Cursor CLI | `~/.cursor/cli-config.json` |

- Exactly one config found → profile auto-filled (`source: config_file`, `confidence: 0.9`)
- Multiple configs found → ambiguous; set `CROSSLAB_HARNESS` or use `crosslab_set_agent_profile`
- Inspect probes: `crosslab detect-profile` or `crosslab doctor --detect-profile`
- MCP: `crosslab_detect_agent_profile(apply=true)` applies only when current profile is unset

Detected values reflect **configured defaults**, not necessarily the live session model.

### Harness thread linking (CodeTalker / OpenCode)

Link external harness session IDs to a CrossLab investigation via the desktop Setup Wizard or MCP `crosslab_set_harness_link`. This is especially useful when CodeTalker cannot discover an OpenCode thread by project name — see [docs/codetalker-opencode.md](docs/codetalker-opencode.md).

### Available MCP Tools:
- `crosslab_send_chat`: Send conversational messages to peer agents across the network.
- `crosslab_propose_hypothesis`: Propose and broadcast an empirical hypothesis.
- `crosslab_add_evidence`: Attach an explicit supporting or contradicting evidence item.
- `crosslab_assess_hypothesis`: Record an agent's confidence rating with rationale.
- `crosslab_challenge_hypothesis`: Challenge a hypothesis with counter-evidence.
- `crosslab_propose_experiment`: Propose a multi-machine synchronized experiment.
- `crosslab_record_run`: Submit local telemetry, packet logs, and outcome for a test run.
- `crosslab_correlate_run`: Run multi-machine cross-log correlation to find sequence gaps and timing deltas.
- `crosslab_query_investigation`: Query shared investigation state (unresolved hypotheses, latest reproduced run, diffs).
- `crosslab_share_patch`: Share unified patches or diagnostic scripts across the network.
- `crosslab_get_transcript`: Fetch the full human-readable Markdown investigation transcript.
- `crosslab_wait_for_message`: Block until an inbound peer message arrives (replaces manual poll timers).
- `crosslab_get_run_state`: Query barrier coordination state for a run (phase, ready flags, start_authorized).
- `crosslab_send_sync_signal`: Send structured ready/start/abort sync signals.
- `crosslab_get_agent_profile`: Get this node's harness and model identity.
- `crosslab_set_agent_profile`: Set harness/model identity visible to peers.
- `crosslab_get_peer_profiles`: List remote peers with their harness and model.
- `crosslab_detect_agent_profile`: Probe local harness configs; optional `apply` when profile unset.

### Agent coordination (no poll timers)

Instead of scheduling 60s REST poll loops, agents should:

1. Call `crosslab_wait_for_message` at the end of a turn to block until the peer replies.
2. Run the event watcher alongside the agent to trigger harness wakeup on inbound events:

```powershell
# Generic stdout wakeup (prints [CROSSLAB_WAKEUP] JSON lines)
uv run crosslab watch --node-url http://127.0.0.1:8765 --wake stdout --verbose

# Antigravity: writes %TEMP%\crosslab_wakeup.json + schedule-compatible stdout prompt
uv run crosslab watch --wake antigravity --agent-id agent-host --role host

# OpenCode: file hook at %TEMP%\crosslab_wakeup.json (inject follow-up from sidecar)
uv run crosslab watch --wake opencode

# Codex: POST to automation webhook
uv run crosslab watch --wake codex --webhook http://127.0.0.1:9999/crosslab-wakeup
```

Set `CROSSLAB_HARNESS=antigravity|opencode|codex` and use `--wake auto` to pick the backend automatically.

| Harness | Wakeup mode | Mechanism |
| :--- | :--- | :--- |
| Antigravity | `--wake antigravity` | File + stdout prompt for schedule hooks |
| OpenCode | `--wake opencode` | Atomic write to `crosslab_wakeup.json` |
| Codex | `--wake codex` | HTTP webhook POST |
| Generic | `--wake stdout` | `[CROSSLAB_WAKEUP]` JSON on stdout |

Query run barrier state before START:

```powershell
# MCP: crosslab_get_run_state(run_id=14)
# REST: GET /v1/a2a/runs/14/barrier
```

`REPORT_INSTRUMENTATION_READY` payloads should include `pid` and `process_start_time` (Unix epoch seconds). Only the **attaching agent** should emit this action. Set `CROSSLAB_STRICT_INSTRUMENTATION=1` to reject stale local READY messages when the PID is no longer running.

### NAT and topology

- **Host:** share a LAN URL from `crosslab doctor` or the desktop setup wizard — not `127.0.0.1` unless both agents are on the same machine.
- **Client:** paste the host's LAN URL; the desktop wizard warns if you enter a loopback address.
- **Remote networks:** use Tailscale, a VPN, or a tunnel (e.g. cloudflared) and set the public URL as the peer endpoint.
- `GET /health` returns `advertised_reachable_externally` and per-peer `topology_warning` when loopback endpoints may break callbacks.

---

## 📦 Protocol Primitives

| Action | Description |
| :--- | :--- |
| `handshake` / `agent-card` | A2A Agent Card discovery and RTT clock offset estimation |
| `chat` | First-class natural language conversation relayed across peer nodes |
| `propose_hypothesis` | Formulate a hypothesis within the investigation evidence graph |
| `add_evidence` | Link runs, observations, or counter-hypotheses as supporting/contradicting evidence |
| `assess_hypothesis` | Record subjective confidence scores from collaborating agents |
| `propose_experiment` | Define test conditions and roles for both host & client |
| `sync_ready` / `start_run` / `end_run` | Synchronize barrier test execution across machines |
| `report_observation` | Emit structured measurements with monotonic timestamps and uncertainty intervals |
| `share_patch` / `share_log` | Safely transfer unified diffs and logs between machines |
| `correlation_analysis` | Execute pluggable correlation analyzers over distributed event streams |

---

## 🛡️ Zero-Implicit-Trust Boundary

CrossLab is specifically designed to eliminate arbitrary remote code execution risks between cooperating agents. Peer agents exchange structured requests and evidence schemas; each agent's local runtime executes only what it independently decides to run.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
