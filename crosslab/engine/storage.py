"""
Persistent SQLite storage backend for CrossLab shared investigation state.
"""

import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from crosslab.protocol.actions import ExperimentStatus, HypothesisStatus, RunOutcome
from crosslab.protocol.models import (
    AgentPeer,
    ArtifactPayload,
    Experiment,
    Hypothesis,
    InstrumentationRequest,
    MessageEnvelope,
    Observation,
    RunRecord,
)


import threading


class Storage:
    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._lock = threading.Lock()
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
            self._mem_conn = None
        else:
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
            self._mem_conn.execute("PRAGMA foreign_keys=ON;")
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._mem_conn is not None:
            return self._mem_conn
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    name TEXT,
                    created_at TEXT,
                    active_hypothesis_id TEXT
                );

                CREATE TABLE IF NOT EXISTS peers (
                    agent_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    role TEXT,
                    endpoint_url TEXT,
                    machine_name TEXT,
                    capabilities TEXT,
                    joined_at TEXT,
                    metadata TEXT
                );

                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    conversation_id TEXT,
                    sender_id TEXT,
                    recipient_id TEXT,
                    timestamp TEXT,
                    action TEXT,
                    natural_language TEXT,
                    payload TEXT
                );

                CREATE TABLE IF NOT EXISTS hypotheses (
                    id TEXT PRIMARY KEY,
                    session_id TEXT,
                    title TEXT,
                    description TEXT,
                    creator TEXT,
                    status TEXT,
                    confidence REAL,
                    evidence_for TEXT,
                    evidence_against TEXT,
                    supporting_run_ids TEXT,
                    contradicting_run_ids TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY,
                    session_id TEXT,
                    run_id INTEGER,
                    hypothesis_id TEXT,
                    title TEXT,
                    rationale TEXT,
                    host_role TEXT,
                    client_role TEXT,
                    parameters TEXT,
                    status TEXT,
                    creator TEXT,
                    created_at TEXT
                );

                CREATE TABLE IF NOT EXISTS runs (
                    run_id INTEGER,
                    session_id TEXT,
                    experiment_id TEXT,
                    hypothesis_id TEXT,
                    hypothesis_title TEXT,
                    build TEXT,
                    participants TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    outcome TEXT,
                    result_summary TEXT,
                    host TEXT,
                    client TEXT,
                    logs TEXT,
                    correlated_findings TEXT,
                    created_at TEXT,
                    PRIMARY KEY (session_id, run_id)
                );

                CREATE TABLE IF NOT EXISTS observations (
                    id TEXT PRIMARY KEY,
                    session_id TEXT,
                    run_id INTEGER,
                    agent_id TEXT,
                    timestamp TEXT,
                    metric_name TEXT,
                    value TEXT,
                    unit TEXT,
                    tags TEXT,
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS instrumentation_requests (
                    id TEXT PRIMARY KEY,
                    session_id TEXT,
                    requester_id TEXT,
                    target_agent_id TEXT,
                    target_module TEXT,
                    target_function TEXT,
                    trace_type TEXT,
                    parameters TEXT,
                    sampling_rate_ms INTEGER,
                    rationale TEXT,
                    status TEXT,
                    created_at TEXT
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    session_id TEXT,
                    filename TEXT,
                    content_type TEXT,
                    content TEXT,
                    sha256 TEXT,
                    author_id TEXT,
                    description TEXT,
                    created_at TEXT
                );
                """
            )

    # --- Session & Peer Operations ---

    def ensure_session(self, session_id: str, name: str = "FEAR 3 Co-Op Investigation") -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO sessions (session_id, name, created_at, active_hypothesis_id)
                VALUES (?, ?, datetime('now'), NULL)
                """,
                (session_id, name),
            )

    def upsert_peer(self, peer: AgentPeer, session_id: str = "default") -> None:
        self.ensure_session(session_id)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO peers 
                (agent_id, session_id, role, endpoint_url, machine_name, capabilities, joined_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    peer.agent_id,
                    session_id,
                    peer.role.value if hasattr(peer.role, "value") else str(peer.role),
                    peer.endpoint_url,
                    peer.machine_name,
                    json.dumps(peer.capabilities),
                    peer.joined_at,
                    json.dumps(peer.metadata),
                ),
            )

    def get_peers(self, session_id: str = "default") -> List[AgentPeer]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM peers WHERE session_id = ?", (session_id,)).fetchall()
            return [
                AgentPeer(
                    agent_id=row["agent_id"],
                    role=row["role"],
                    endpoint_url=row["endpoint_url"],
                    machine_name=row["machine_name"],
                    capabilities=json.loads(row["capabilities"] or "[]"),
                    joined_at=row["joined_at"],
                    metadata=json.loads(row["metadata"] or "{}"),
                )
                for row in rows
            ]

    # --- Messages ---

    def save_message(self, msg: MessageEnvelope) -> None:
        self.ensure_session(msg.session_id)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO messages
                (message_id, session_id, conversation_id, sender_id, recipient_id, timestamp, action, natural_language, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg.message_id,
                    msg.session_id,
                    msg.conversation_id,
                    msg.sender_id,
                    msg.recipient_id,
                    msg.timestamp,
                    msg.action.value if hasattr(msg.action, "value") else str(msg.action),
                    msg.natural_language,
                    json.dumps(msg.payload),
                ),
            )

    def get_messages(self, session_id: str = "default", limit: int = 100) -> List[MessageEnvelope]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp ASC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            return [
                MessageEnvelope(
                    message_id=row["message_id"],
                    session_id=row["session_id"],
                    conversation_id=row["conversation_id"],
                    sender_id=row["sender_id"],
                    recipient_id=row["recipient_id"],
                    timestamp=row["timestamp"],
                    action=row["action"],
                    natural_language=row["natural_language"],
                    payload=json.loads(row["payload"] or "{}"),
                )
                for row in rows
            ]

    # --- Hypotheses ---

    def save_hypothesis(self, hyp: Hypothesis) -> None:
        self.ensure_session(hyp.session_id)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO hypotheses
                (id, session_id, title, description, creator, status, confidence, evidence_for, evidence_against, supporting_run_ids, contradicting_run_ids, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hyp.id,
                    hyp.session_id,
                    hyp.title,
                    hyp.description,
                    hyp.creator,
                    hyp.status.value if hasattr(hyp.status, "value") else str(hyp.status),
                    hyp.confidence,
                    json.dumps(hyp.evidence_for),
                    json.dumps(hyp.evidence_against),
                    json.dumps(hyp.supporting_run_ids),
                    json.dumps(hyp.contradicting_run_ids),
                    hyp.created_at,
                    hyp.updated_at,
                ),
            )

    def get_hypotheses(self, session_id: str = "default") -> List[Hypothesis]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM hypotheses WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
            return [
                Hypothesis(
                    id=row["id"],
                    session_id=row["session_id"],
                    title=row["title"],
                    description=row["description"],
                    creator=row["creator"],
                    status=HypothesisStatus(row["status"]),
                    confidence=row["confidence"],
                    evidence_for=json.loads(row["evidence_for"] or "[]"),
                    evidence_against=json.loads(row["evidence_against"] or "[]"),
                    supporting_run_ids=json.loads(row["supporting_run_ids"] or "[]"),
                    contradicting_run_ids=json.loads(row["contradicting_run_ids"] or "[]"),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            ]

    def get_hypothesis(self, hyp_id: str) -> Optional[Hypothesis]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM hypotheses WHERE id = ?", (hyp_id,)).fetchone()
            if not row:
                return None
            return Hypothesis(
                id=row["id"],
                session_id=row["session_id"],
                title=row["title"],
                description=row["description"],
                creator=row["creator"],
                status=HypothesisStatus(row["status"]),
                confidence=row["confidence"],
                evidence_for=json.loads(row["evidence_for"] or "[]"),
                evidence_against=json.loads(row["evidence_against"] or "[]"),
                supporting_run_ids=json.loads(row["supporting_run_ids"] or "[]"),
                contradicting_run_ids=json.loads(row["contradicting_run_ids"] or "[]"),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    # --- Experiments ---

    def save_experiment(self, exp: Experiment) -> None:
        self.ensure_session(exp.session_id)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO experiments
                (id, session_id, run_id, hypothesis_id, title, rationale, host_role, client_role, parameters, status, creator, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    exp.id,
                    exp.session_id,
                    exp.run_id,
                    exp.hypothesis_id,
                    exp.title,
                    exp.rationale,
                    exp.host_role,
                    exp.client_role,
                    json.dumps(exp.parameters),
                    exp.status.value if hasattr(exp.status, "value") else str(exp.status),
                    exp.creator,
                    exp.created_at,
                ),
            )

    def get_experiments(self, session_id: str = "default") -> List[Experiment]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM experiments WHERE session_id = ? ORDER BY run_id ASC",
                (session_id,),
            ).fetchall()
            return [
                Experiment(
                    id=row["id"],
                    session_id=row["session_id"],
                    run_id=row["run_id"],
                    hypothesis_id=row["hypothesis_id"],
                    title=row["title"],
                    rationale=row["rationale"],
                    host_role=row["host_role"],
                    client_role=row["client_role"],
                    parameters=json.loads(row["parameters"] or "{}"),
                    status=ExperimentStatus(row["status"]),
                    creator=row["creator"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    # --- Runs & Observations ---

    def save_run(self, run: RunRecord) -> None:
        self.ensure_session(run.session_id)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runs
                (run_id, session_id, experiment_id, hypothesis_id, hypothesis_title, build, participants, start_time, end_time, outcome, result_summary, host, client, logs, correlated_findings, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.session_id,
                    run.experiment_id,
                    run.hypothesis_id,
                    run.hypothesis_title,
                    run.build,
                    json.dumps(run.participants),
                    run.start_time,
                    run.end_time,
                    run.outcome.value if hasattr(run.outcome, "value") else str(run.outcome),
                    run.result_summary,
                    json.dumps(run.host),
                    json.dumps(run.client),
                    json.dumps(run.logs),
                    json.dumps(run.correlated_findings) if run.correlated_findings else None,
                    run.created_at,
                ),
            )

    def get_runs(self, session_id: str = "default") -> List[RunRecord]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE session_id = ? ORDER BY run_id ASC",
                (session_id,),
            ).fetchall()
            runs = []
            for row in rows:
                run_id = row["run_id"]
                obs = self.get_observations(session_id=session_id, run_id=run_id)
                runs.append(
                    RunRecord(
                        run_id=row["run_id"],
                        session_id=row["session_id"],
                        experiment_id=row["experiment_id"],
                        hypothesis_id=row["hypothesis_id"],
                        hypothesis_title=row["hypothesis_title"],
                        build=row["build"] or "default",
                        participants=json.loads(row["participants"] or "[]"),
                        start_time=row["start_time"],
                        end_time=row["end_time"],
                        outcome=RunOutcome(row["outcome"]),
                        result_summary=row["result_summary"],
                        host=json.loads(row["host"] or "{}"),
                        client=json.loads(row["client"] or "{}"),
                        logs=json.loads(row["logs"] or "[]"),
                        observations=obs,
                        correlated_findings=json.loads(row["correlated_findings"])
                        if row["correlated_findings"]
                        else None,
                        created_at=row["created_at"],
                    )
                )
            return runs

    def get_run(self, run_id: int, session_id: str = "default") -> Optional[RunRecord]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE run_id = ? AND session_id = ?",
                (run_id, session_id),
            ).fetchone()
            if not row:
                return None
            obs = self.get_observations(session_id=session_id, run_id=run_id)
            return RunRecord(
                run_id=row["run_id"],
                session_id=row["session_id"],
                experiment_id=row["experiment_id"],
                hypothesis_id=row["hypothesis_id"],
                hypothesis_title=row["hypothesis_title"],
                build=row["build"] or "default",
                participants=json.loads(row["participants"] or "[]"),
                start_time=row["start_time"],
                end_time=row["end_time"],
                outcome=RunOutcome(row["outcome"]),
                result_summary=row["result_summary"],
                host=json.loads(row["host"] or "{}"),
                client=json.loads(row["client"] or "{}"),
                logs=json.loads(row["logs"] or "[]"),
                observations=obs,
                correlated_findings=json.loads(row["correlated_findings"])
                if row["correlated_findings"]
                else None,
                created_at=row["created_at"],
            )

    def save_observation(self, obs: Observation) -> None:
        self.ensure_session(obs.session_id)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO observations
                (id, session_id, run_id, agent_id, timestamp, metric_name, value, unit, tags, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    obs.id,
                    obs.session_id,
                    obs.run_id,
                    obs.agent_id,
                    obs.timestamp,
                    obs.metric_name,
                    json.dumps(obs.value),
                    obs.unit,
                    json.dumps(obs.tags),
                    obs.notes,
                ),
            )

    def get_observations(self, session_id: str = "default", run_id: Optional[int] = None) -> List[Observation]:
        with self._get_connection() as conn:
            if run_id is not None:
                rows = conn.execute(
                    "SELECT * FROM observations WHERE session_id = ? AND run_id = ? ORDER BY timestamp ASC",
                    (session_id, run_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM observations WHERE session_id = ? ORDER BY timestamp ASC",
                    (session_id,),
                ).fetchall()
            return [
                Observation(
                    id=row["id"],
                    session_id=row["session_id"],
                    run_id=row["run_id"],
                    agent_id=row["agent_id"],
                    timestamp=row["timestamp"],
                    metric_name=row["metric_name"],
                    value=json.loads(row["value"]) if row["value"] is not None else None,
                    unit=row["unit"],
                    tags=json.loads(row["tags"] or "[]"),
                    notes=row["notes"],
                )
                for row in rows
            ]

    # --- Instrumentation Requests ---

    def save_instrumentation_request(self, req: InstrumentationRequest) -> None:
        self.ensure_session(req.session_id)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO instrumentation_requests
                (id, session_id, requester_id, target_agent_id, target_module, target_function, trace_type, parameters, sampling_rate_ms, rationale, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    req.id,
                    req.session_id,
                    req.requester_id,
                    req.target_agent_id,
                    req.target_module,
                    req.target_function,
                    req.trace_type,
                    json.dumps(req.parameters),
                    req.sampling_rate_ms,
                    req.rationale,
                    req.status,
                    req.created_at,
                ),
            )

    def get_instrumentation_requests(self, session_id: str = "default") -> List[InstrumentationRequest]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM instrumentation_requests WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
            return [
                InstrumentationRequest(
                    id=row["id"],
                    session_id=row["session_id"],
                    requester_id=row["requester_id"],
                    target_agent_id=row["target_agent_id"],
                    target_module=row["target_module"],
                    target_function=row["target_function"],
                    trace_type=row["trace_type"],
                    parameters=json.loads(row["parameters"] or "{}"),
                    sampling_rate_ms=row["sampling_rate_ms"],
                    rationale=row["rationale"],
                    status=row["status"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    # --- Artifacts ---

    def save_artifact(self, art: ArtifactPayload) -> None:
        self.ensure_session(art.session_id)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO artifacts
                (id, session_id, filename, content_type, content, sha256, author_id, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    art.id,
                    art.session_id,
                    art.filename,
                    art.content_type,
                    art.content,
                    art.sha256,
                    art.author_id,
                    art.description,
                    art.created_at,
                ),
            )

    def get_artifacts(self, session_id: str = "default") -> List[ArtifactPayload]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM artifacts WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
            return [
                ArtifactPayload(
                    id=row["id"],
                    session_id=row["session_id"],
                    filename=row["filename"],
                    content_type=row["content_type"],
                    content=row["content"],
                    sha256=row["sha256"],
                    author_id=row["author_id"],
                    description=row["description"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]
