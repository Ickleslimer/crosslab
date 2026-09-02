"""
Real-time human-readable transcript recorder and formatter for CrossLab.
Maintains continuous, crash-safe Markdown transcripts of all A2A messages,
hypotheses, experiments, and test run outcomes.
"""

from datetime import datetime
import json
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional

from crosslab.protocol.actions import ActionType, AgentRole, RunOutcome
from crosslab.protocol.models import (
    AgentPeer,
    ArtifactPayload,
    EvidenceItem,
    Experiment,
    Hypothesis,
    MessageEnvelope,
    Observation,
    RunRecord,
)


def format_sender_badge(sender_id: Optional[str]) -> str:
    """Return a human-friendly formatted badge for a message sender."""
    if not sender_id:
        return "**[Unknown]**"
    s = sender_id.lower()
    if "agent-host" in s or s == "host":
        return "**[Agent A (Host)]**"
    elif "agent-client" in s or s == "client":
        return "**[Agent B (Client)]**"
    elif "human-host" in s:
        return "**[Human Host]**"
    elif "human-client" in s:
        return "**[Human Client]**"
    elif "agent-mcp" in s:
        return f"**[MCP Agent ({sender_id})]**"
    else:
        return f"**[{sender_id}]**"


def format_action_tag(action: Any) -> str:
    """Return a styled action tag."""
    val = action.value if hasattr(action, "value") else str(action)
    return f"`{val.upper()}`"


class TranscriptRecorder:
    """
    Manages live streaming and full export of human-readable Markdown transcripts.
    """

    def __init__(self, transcript_dir: Optional[str] = None, session_id: str = "default"):
        self.session_id = session_id
        if transcript_dir:
            self.transcript_dir = Path(transcript_dir)
        else:
            self.transcript_dir = Path("transcripts")
        
        self.transcript_dir.mkdir(parents=True, exist_ok=True)
        self.transcript_file = self.transcript_dir / f"{self.session_id}.md"
        self._lock = threading.Lock()
        self._initialized = False

    def get_file_path(self) -> Path:
        return self.transcript_file.resolve()

    def _ensure_header(self, session_name: Optional[str] = None, created_at: Optional[str] = None) -> None:
        """Ensure initial header is written if file is new or empty."""
        if self.transcript_file.exists() and self.transcript_file.stat().st_size > 0:
            self._initialized = True
            return

        name = session_name or f"CrossLab Investigation: {self.session_id}"
        ts = created_at or datetime.now().isoformat()

        header = [
            f"# CrossLab Investigation Transcript: {self.session_id}",
            "",
            f"> **Session Name:** {name}  ",
            f"> **Started At:** `{ts}`  ",
            f"> **Transcript Format:** Live Streaming Markdown Backup  ",
            "",
            "---",
            "",
            "## Chronological Dialogue & Investigation Events",
            "",
        ]
        with open(self.transcript_file, "w", encoding="utf-8") as f:
            f.write("\n".join(header))
            f.flush()
            os.fsync(f.fileno())
        self._initialized = True

    def record_message(self, msg: MessageEnvelope) -> None:
        """Stream a single incoming/outgoing message envelope into the transcript."""
        with self._lock:
            self._ensure_header()
            sender_badge = format_sender_badge(msg.sender_id)
            action_tag = format_action_tag(msg.action)
            ts = msg.timestamp or datetime.now().isoformat()
            
            lines = [
                f"### {sender_badge} &nbsp; {action_tag} &nbsp; <small>`{ts}`</small>",
                f"<!-- message_id: {msg.message_id} -->",
                "",
            ]

            # Natural language text
            text = (msg.natural_language or "").strip()
            if text:
                if msg.action in (ActionType.HUMAN_REPRO_REQUEST, ActionType.HUMAN_SIGNAL):
                    lines.append("> **Human Operator**")
                    for line in text.splitlines():
                        lines.append(f"> {line}")
                else:
                    lines.append(text)
                lines.append("")

            # Formatted structured payload (if present and meaningful)
            if msg.payload and isinstance(msg.payload, dict) and msg.payload != {}:
                if any(k in msg.payload for k in ("run_id", "build", "hypothesis_id", "parameters", "experiment_id", "patch")):
                    lines.append("<details>")
                    lines.append("<summary>Structured Payload</summary>")
                    lines.append("")
                    lines.append("```json")
                    lines.append(json.dumps(msg.payload, indent=2, ensure_ascii=False))
                    lines.append("```")
                    lines.append("</details>")
                    lines.append("")

            lines.append("---")
            lines.append("")

            with open(self.transcript_file, "a", encoding="utf-8") as f:
                f.write("\n".join(lines))
                f.flush()
                os.fsync(f.fileno())

    def record_hypothesis(self, hyp: Hypothesis) -> None:
        """Stream a newly proposed or updated hypothesis."""
        with self._lock:
            self._ensure_header()
            creator_badge = format_sender_badge(hyp.creator)
            ts = hyp.created_at or datetime.now().isoformat()
            status_val = hyp.status.value if hasattr(hyp.status, "value") else str(hyp.status)
            conf_str = f"{hyp.confidence:.2f}" if hyp.confidence is not None else "N/A"

            lines = [
                f"### 💡 Hypothesis Proposed: **{hyp.title}** (`{hyp.id}`)",
                f"> **Author:** {creator_badge} &nbsp;|&nbsp; **Status:** `{status_val}` &nbsp;|&nbsp; **Confidence:** `{conf_str}` &nbsp;|&nbsp; **Time:** `{ts}`",
                "",
                hyp.description.strip(),
                "",
                "---",
                "",
            ]
            with open(self.transcript_file, "a", encoding="utf-8") as f:
                f.write("\n".join(lines))
                f.flush()
                os.fsync(f.fileno())

    def record_run(self, run: RunRecord) -> None:
        """Stream a test run record."""
        with self._lock:
            self._ensure_header()
            outcome_val = run.outcome.value if hasattr(run.outcome, "value") else str(run.outcome)
            ts = run.end_time or run.start_time or datetime.now().isoformat()

            lines = [
                f"### 🧪 Run {run.run_id} Result: **`{outcome_val.upper()}`** &nbsp; <small>`{ts}`</small>",
                f"> **Build:** `{run.build}` &nbsp;|&nbsp; **Hypothesis:** `{run.hypothesis_id or 'N/A'}`: *{run.hypothesis_title or 'Untitled'}*",
                "",
            ]
            if run.result_summary:
                lines.append(f"**Summary:** {run.result_summary.strip()}")
                lines.append("")

            if run.host or run.client:
                lines.append("<details>")
                lines.append("<summary>Run Telemetry</summary>")
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps({"host": run.host, "client": run.client}, indent=2, ensure_ascii=False))
                lines.append("```")
                lines.append("</details>")
                lines.append("")

            lines.append("---")
            lines.append("")

            with open(self.transcript_file, "a", encoding="utf-8") as f:
                f.write("\n".join(lines))
                f.flush()
                os.fsync(f.fileno())

    def generate_full_markdown(self, storage: Any) -> str:
        """
        Generate a complete, structured, human-readable Markdown transcript
        from a Storage instance.
        """
        session_id = self.session_id
        peers = storage.get_peers(session_id=session_id)
        messages = storage.get_messages(session_id=session_id, limit=None)
        hypotheses = storage.get_hypotheses(session_id=session_id)
        experiments = storage.get_experiments(session_id=session_id)
        runs = storage.get_runs(session_id=session_id)

        md = []
        md.append(f"# CrossLab Investigation Transcript: {session_id}")
        md.append("")
        md.append(f"> **Generated:** `{datetime.now().isoformat()}`  ")
        md.append(f"> **Total Messages:** {len(messages)}  ")
        md.append(f"> **Total Hypotheses:** {len(hypotheses)}  ")
        md.append(f"> **Total Runs:** {len(runs)}  ")
        md.append("")

        # Peers table
        if peers:
            md.append("## Participating Agents & Roles")
            md.append("")
            md.append("| Agent ID | Role | Machine | Endpoint |")
            md.append("| :--- | :--- | :--- | :--- |")
            for p in peers:
                role_str = p.role.value if hasattr(p.role, "value") else str(p.role)
                md.append(f"| `{p.agent_id}` | **{role_str}** | {p.machine_name or 'N/A'} | `{p.endpoint_url}` |")
            md.append("")
            md.append("---")
            md.append("")

        # Hypotheses summary
        if hypotheses:
            md.append("## Hypotheses Ledger")
            md.append("")
            for h in hypotheses:
                status_val = h.status.value if hasattr(h.status, "value") else str(h.status)
                conf_str = f"{h.confidence:.2f}" if h.confidence is not None else "N/A"
                md.append(f"### `{h.id}`: {h.title}")
                md.append(f"- **Author:** {format_sender_badge(h.creator)}")
                md.append(f"- **Status:** `{status_val}` | **Confidence:** `{conf_str}`")
                md.append(f"- **Description:** {h.description}")
                if h.evidence_graph:
                    md.append(f"- **Evidence Items ({len(h.evidence_graph)}):**")
                    for ev in h.evidence_graph:
                        rel_str = ev.relation.value if hasattr(ev.relation, "value") else str(ev.relation)
                        md.append(f"  - `{rel_str.upper()}` ({ev.source_id}): {ev.rationale}")
                md.append("")
            md.append("---")
            md.append("")

        # Runs summary
        if runs:
            md.append("## Empirical Run History")
            md.append("")
            md.append("| Run | Outcome | Build | Hypothesis | Result Summary |")
            md.append("| :--- | :--- | :--- | :--- | :--- |")
            for r in runs:
                outcome_str = r.outcome.value if hasattr(r.outcome, "value") else str(r.outcome)
                summary_snippet = (r.result_summary or "").replace("\n", " ").replace("|", "\\|")
                if len(summary_snippet) > 80:
                    summary_snippet = summary_snippet[:80] + "..."
                md.append(f"| **Run {r.run_id}** | `{outcome_str.upper()}` | `{r.build}` | `{r.hypothesis_id or '-'}` | {summary_snippet} |")
            md.append("")
            md.append("---")
            md.append("")

        # Human operator runbook
        human_msgs = [m for m in messages if m.action in (ActionType.HUMAN_REPRO_REQUEST, ActionType.HUMAN_SIGNAL)]
        if human_msgs:
            md.append("## Human Operator Runbook")
            md.append("")
            for m in human_msgs:
                sender_badge = format_sender_badge(m.sender_id)
                action_tag = format_action_tag(m.action)
                md.append(f"### {sender_badge} &nbsp; {action_tag}")
                payload = m.payload or {}
                if payload.get("run_id") is not None:
                    md.append(f"- **Run:** {payload.get('run_id')}")
                if payload.get("signal"):
                    md.append(f"- **Signal:** `{payload.get('signal')}`")
                text = (m.natural_language or "").strip()
                if text:
                    md.append("")
                    for line in text.splitlines():
                        md.append(f"> {line}")
                steps = payload.get("steps", [])
                if steps:
                    md.append("")
                    for i, step in enumerate(steps, 1):
                        role = step.get("role", "both") if isinstance(step, dict) else "both"
                        instr = step.get("instruction", step) if isinstance(step, dict) else str(step)
                        md.append(f"{i}. **[{role}]** {instr}")
                md.append("")
            md.append("---")
            md.append("")

        # Chronological Message Log
        md.append("## Full Chronological Message Log")
        md.append("")

        for m in messages:
            sender_badge = format_sender_badge(m.sender_id)
            action_tag = format_action_tag(m.action)
            ts = m.timestamp or "Unknown"

            md.append(f"### {sender_badge} &nbsp; {action_tag} &nbsp; <small>`{ts}`</small>")
            md.append(f"<!-- message_id: {m.message_id} -->")
            md.append("")
            text = (m.natural_language or "").strip()
            if text:
                md.append(text)
                md.append("")

            if m.payload and isinstance(m.payload, dict) and m.payload != {}:
                if any(k in m.payload for k in ("run_id", "build", "hypothesis_id", "parameters", "experiment_id", "patch")):
                    md.append("<details>")
                    md.append("<summary>Structured Payload</summary>")
                    md.append("")
                    md.append("```json")
                    md.append(json.dumps(m.payload, indent=2, ensure_ascii=False))
                    md.append("```")
                    md.append("</details>")
                    md.append("")

            md.append("---")
            md.append("")

        return "\n".join(md)

    def write_full_transcript(self, storage: Any) -> Path:
        """Regenerate and write the full transcript to file atomically."""
        content = self.generate_full_markdown(storage)
        with self._lock:
            with open(self.transcript_file, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
        return self.transcript_file.resolve()
