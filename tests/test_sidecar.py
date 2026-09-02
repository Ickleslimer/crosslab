"""Tests for CrossLab sidecar entry and data-dir resolution."""

import os
import sqlite3
import tempfile
from pathlib import Path

from crosslab.sidecar import _db_counts, maybe_import_legacy_database, resolve_data_paths


def test_resolve_data_paths_with_data_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path, transcript_dir = resolve_data_paths(tmpdir, "fear3-debug", None, None)
        assert db_path == os.path.join(tmpdir, "crosslab_fear3-debug.db")
        assert transcript_dir == os.path.join(tmpdir, "transcripts")
        assert Path(transcript_dir).is_dir()


def test_resolve_data_paths_without_data_dir():
    db_path, transcript_dir = resolve_data_paths(None, "default", None, None)
    assert db_path == "./crosslab_default.db"
    assert transcript_dir is None


def test_maybe_import_legacy_database():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir, tempfile.TemporaryDirectory(
        ignore_cleanup_errors=True
    ) as legacy_dir:
        session_id = "import-test-session"
        legacy_db = os.path.join(legacy_dir, f"crosslab_{session_id}.db")
        target_db = os.path.join(tmpdir, f"crosslab_{session_id}.db")
        transcript_dir = os.path.join(tmpdir, "transcripts")

        with sqlite3.connect(legacy_db) as conn:
            conn.executescript(
                """
                CREATE TABLE messages (message_id TEXT PRIMARY KEY, session_id TEXT);
                INSERT INTO messages VALUES ('m1', 'import-test-session');
                """
            )

        imported = maybe_import_legacy_database(
            target_db,
            session_id,
            transcript_dir,
            search_dirs=[legacy_dir],
        )
        assert imported is True
        assert os.path.exists(target_db)
        assert _db_counts(target_db, session_id)[0] == 1


def test_maybe_import_legacy_database_skips_when_target_has_data():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir, tempfile.TemporaryDirectory(
        ignore_cleanup_errors=True
    ) as legacy_dir:
        session_id = "skip-import-session"
        legacy_db = os.path.join(legacy_dir, f"crosslab_{session_id}.db")
        target_db = os.path.join(tmpdir, f"crosslab_{session_id}.db")

        with sqlite3.connect(legacy_db) as conn:
            conn.executescript(
                """
                CREATE TABLE messages (message_id TEXT PRIMARY KEY, session_id TEXT);
                INSERT INTO messages VALUES ('legacy', 'skip-import-session');
                """
            )
        with sqlite3.connect(target_db) as conn:
            conn.executescript(
                """
                CREATE TABLE messages (message_id TEXT PRIMARY KEY, session_id TEXT);
                INSERT INTO messages VALUES ('local', 'skip-import-session');
                """
            )

        imported = maybe_import_legacy_database(
            target_db,
            session_id,
            None,
            search_dirs=[legacy_dir],
        )
        assert imported is False
        assert _db_counts(target_db, session_id)[0] == 1


def test_resolve_data_paths_explicit_overrides():
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_db = os.path.join(tmpdir, "custom.db")
        custom_transcript = os.path.join(tmpdir, "custom_transcripts")
        db_path, transcript_dir = resolve_data_paths(tmpdir, "s1", custom_db, custom_transcript)
        assert db_path == custom_db
        assert transcript_dir == custom_transcript
