"""
Minimal CrossLab node entry point for desktop sidecar / PyInstaller bundles.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys

import uvicorn

from crosslab.protocol.actions import AgentRole
from crosslab.transport.node import A2ANode


def _db_counts(db_path: str, session_id: str) -> tuple[int, int, int]:
    if not os.path.exists(db_path):
        return (0, 0, 0)
    try:
        with sqlite3.connect(db_path) as conn:
            counts: list[int] = []
            for table in ("messages", "hypotheses", "runs"):
                try:
                    row = conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE session_id = ?",
                        (session_id,),
                    ).fetchone()
                    counts.append(int(row[0]) if row else 0)
                except sqlite3.Error:
                    counts.append(0)
            return counts[0], counts[1], counts[2]
    except sqlite3.Error:
        return (0, 0, 0)


def _legacy_db_candidates(session_id: str, search_dirs: list[str]) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for directory in search_dirs:
        if not directory:
            continue
        candidate = os.path.abspath(os.path.join(directory, f"crosslab_{session_id}.db"))
        if candidate in seen:
            continue
        seen.add(candidate)
        candidates.append(candidate)
    return candidates


def _legacy_transcript_candidates(session_id: str, search_dirs: list[str]) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for directory in search_dirs:
        if not directory:
            continue
        for base in (os.path.join(directory, "transcripts"), directory):
            candidate = os.path.abspath(os.path.join(base, f"{session_id}.md"))
            if candidate in seen:
                continue
            seen.add(candidate)
            candidates.append(candidate)
    return candidates


def _copy_sqlite_database(source: str, dest: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    for path in (dest, f"{dest}-wal", f"{dest}-shm"):
        if os.path.exists(path):
            os.remove(path)
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(dest) as dst:
        src.backup(dst)
        dst.execute("PRAGMA journal_mode=DELETE")


def maybe_import_legacy_database(
    db_path: str,
    session_id: str,
    transcript_dir: str | None,
    search_dirs: list[str] | None = None,
) -> bool:
    """
    If the target DB has no investigation data, import a richer legacy DB
    from known locations (repo cwd, explicit legacy search dirs).
    """
    if sum(_db_counts(db_path, session_id)) > 0:
        return False

    dirs = search_dirs if search_dirs else [os.getcwd()]

    best_db: str | None = None
    best_score = 0
    for candidate in _legacy_db_candidates(session_id, dirs):
        if os.path.abspath(candidate) == os.path.abspath(db_path):
            continue
        score = sum(_db_counts(candidate, session_id))
        if score > best_score:
            best_score = score
            best_db = candidate

    if not best_db:
        return False

    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    _copy_sqlite_database(best_db, db_path)

    if transcript_dir:
        os.makedirs(transcript_dir, exist_ok=True)
        target_transcript = os.path.join(transcript_dir, f"{session_id}.md")
        if not os.path.exists(target_transcript):
            for candidate in _legacy_transcript_candidates(session_id, dirs):
                if os.path.exists(candidate):
                    shutil.copy2(candidate, target_transcript)
                    break

    return True


def resolve_data_paths(
    data_dir: str | None,
    session_id: str,
    db_path: str | None,
    transcript_dir: str | None,
) -> tuple[str, str | None]:
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
        resolved_db = db_path or os.path.join(data_dir, f"crosslab_{session_id}.db")
        resolved_transcript = transcript_dir or os.path.join(data_dir, "transcripts")
        os.makedirs(resolved_transcript, exist_ok=True)
        return resolved_db, resolved_transcript
    return db_path or f"./crosslab_{session_id}.db", transcript_dir


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="CrossLab A2A node sidecar")
    parser.add_argument("--role", choices=["host", "client", "observer"], default="host")
    parser.add_argument("--agent-id", type=str, default=None)
    parser.add_argument("--host", type=str, default=None, help="Binding host (host role defaults to 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--session", type=str, default="default")
    parser.add_argument("--peer", type=str, default=None)
    parser.add_argument("--data-dir", type=str, default=None, help="Root directory for DB and transcripts")
    parser.add_argument("--db", type=str, default=None)
    parser.add_argument("--transcript-dir", type=str, default=None)
    parser.add_argument(
        "--legacy-search-dir",
        action="append",
        default=[],
        help="Additional directories to search for legacy crosslab_<session>.db files",
    )
    args = parser.parse_args(argv)

    role = AgentRole(args.role)
    bind_host = args.host if args.host is not None else ("0.0.0.0" if role == AgentRole.HOST else "127.0.0.1")
    db_path, transcript_dir = resolve_data_paths(args.data_dir, args.session, args.db, args.transcript_dir)
    maybe_import_legacy_database(db_path, args.session, transcript_dir, args.legacy_search_dir)

    node = A2ANode(
        agent_id=args.agent_id or f"agent-{role.value}",
        role=role,
        host=bind_host,
        port=args.port,
        session_id=args.session,
        db_path=db_path,
        initial_peer_url=args.peer,
        transcript_dir=transcript_dir,
    )

    print(f"CrossLab sidecar starting: role={role.value} port={args.port} session={args.session}", flush=True)
    uvicorn.run(node.app, host=bind_host, port=args.port, log_level="info")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
