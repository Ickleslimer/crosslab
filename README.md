# CrossLab: Multi-Machine Agent-to-Agent (A2A) Empirical Collaboration Layer

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**CrossLab** is a lightweight collaboration layer and protocol that allows **independent AI coding agents running on different physical or virtual machines to work together on empirical debugging problems**.

Rather than giving one agent remote control or unrestricted shell access over every machine, each agent remains sovereign over its own local environment. The agents communicate using an **Agent-to-Agent (A2A)** protocol, exchanging natural-language reasoning, structured hypotheses, synchronized experiment plans, telemetry observations, multi-machine correlated logs, and patches.

---

## 🎯 Primary Test Case: FEAR 3 Co-Op Disconnect

Distributed bugs violate the assumption that all evidence exists on one machine:

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
1. **Discovery & Handshake**: Agents establish a persistent investigation session over A2A.
2. **Conversational Reasoning**: Host Agent notes a timeout 5 seconds after receive counter halts; Client Agent confirms 4 sends returned `k_EResultOK`.
3. **Hypothesis Formulation**: Host Agent proposes hypothesis `Host receive timeout occurs despite successful client sends`.
4. **Experiment Proposal & Agreement**: Host Agent proposes Run 14 with dual-machine instrumentation. Client Agent accepts.
5. **Zero-Trust Local Execution**: Neither agent gains remote shell access. Each agent applies non-intrusive probes locally.
6. **Synchronized Run & Telemetry Exchange**: Telemetry is recorded and exchanged over A2A.
7. **Cross-Machine Correlation**: The Correlation Engine detects that packet #8835 was sent successfully by the client while the host stopped receiving at packet #8831, causing an internal watchdog timeout (`connection_lost`) which the client UI misreported as `kicked_by_host`.
8. **Patch Formulation**: Agents formulate and share `fear3_keepalive_probe.patch` to maintain active heartbeat probes during packet starvation.

---

## 🏗️ Architecture

```text
A2A Agent Endpoint (FastAPI + SSE Stream)
       │
Investigation Engine (SQLite Ledger)
       ├── Conversations & Messages
       ├── Hypotheses (Active / Supported / Contradicted)
       ├── Experiments & Synchronized Run Coordinator
       ├── Multi-Machine Correlation & Anomaly Engine
       └── Artifact & Patch Store
       │
Local Coding Agent Adapter & MCP Server
       │
Antigravity / Claude Code / Codex / Gemini / Cursor
```

---

## 🚀 Quick Start

### 1. Installation

```powershell
cd C:\Users\mrdyl\.gemini\antigravity\scratch\crosslab
uv sync
```

### 2. Run the Automated FEAR 3 Multi-Agent Demo

```powershell
uv run crosslab demo fear3
```

### 3. Run the Test Suite

```powershell
uv run pytest -v
```

### 4. Start an A2A Node on Host / Client Machines

**Machine A (Host):**
```powershell
uv run crosslab node --role host --port 8765 --session fear3-debug
```

**Machine B (Client):**
```powershell
uv run crosslab node --role client --port 8766 --peer http://machine-a:8765 --session fear3-debug
```

---

## 🤖 MCP (Model Context Protocol) Server

CrossLab provides a built-in MCP server that enables any MCP-compatible coding agent to invoke investigation tools directly:

```powershell
uv run crosslab mcp
```

### Available MCP Tools:
- `crosslab_propose_hypothesis`: Formulate and broadcast an empirical hypothesis.
- `crosslab_challenge_hypothesis`: Challenge a hypothesis with counter-evidence.
- `crosslab_propose_experiment`: Propose a multi-machine synchronized experiment (host and client roles).
- `crosslab_record_run`: Submit local telemetry and logs for a test run.
- `crosslab_correlate_run`: Run multi-machine cross-log correlation to find packet drops and race conditions.
- `crosslab_query_investigation`: Query unresolved hypotheses, latest reproduced runs, or diffs between runs.
- `crosslab_share_patch`: Share unified patches or diagnostic scripts with peer agents.

---

## 📦 Protocol Primitives

| Action | Description |
| :--- | :--- |
| `propose_hypothesis` | Propose an empirical explanation for the failure |
| `challenge_hypothesis` | Challenge an existing theory with counter-evidence |
| `propose_experiment` | Define test conditions and roles for both host & client |
| `accept_experiment` | Agree to participate in a proposed experiment |
| `sync_ready` / `start_run` / `end_run` | Synchronize test run execution across machines |
| `report_observation` | Emit structured measurements and metric values |
| `request_instrumentation` | Request the peer agent to attach a specific trace probe |
| `share_log` / `share_patch` / `share_file` | Transfer files, logs, and unified diffs safely |
| `correlate_run` | Align cross-machine timestamps and isolate root causes |

---

## 💡 Investigation Queries

The shared ledger allows either agent to ask questions like:
- **Which hypotheses remain unresolved?** `session.get_unresolved_hypotheses()`
- **Which experiment last reproduced the bug?** `session.get_latest_reproducing_run()`
- **What changed between Run 12 and Run 14?** `session.diff_runs(12, 14)`
- **Which observations contradict our current theory?** `session.get_contradicting_observations(hyp_id)`

---

## 🛡️ Zero-Implicit-Trust Boundary

CrossLab is specifically designed to prevent arbitrary remote command execution. Peer agents propose experiments, request instrumentation, and exchange data through strictly validated schemas. Each agent's local runtime executes only what it independently decides to run.
