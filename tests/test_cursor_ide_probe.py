"""Tests for experimental Cursor IDE state.vscdb probe."""

import json
import sqlite3
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from crosslab.engine.harness_probes.cursor_ide import (
    APPLICATION_USER_KEY,
    extract_model_from_application_user,
    probe_cursor_ide,
)
from crosslab.engine.harness_probes.registry import probe_cursor
from crosslab.engine.manifest import data_dir_from_db_path
from crosslab.protocol.actions import AgentRole
from crosslab.transport.node import A2ANode


def _write_state_db(path: Path, blob: dict | None, *, raw_value: bytes | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE ItemTable (key TEXT UNIQUE, value BLOB)")
        if blob is not None:
            conn.execute(
                "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
                (APPLICATION_USER_KEY, json.dumps(blob)),
            )
        elif raw_value is not None:
            conn.execute(
                "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
                (APPLICATION_USER_KEY, raw_value),
            )
        conn.commit()
    finally:
        conn.close()
    return path


def _application_user(*modes: tuple[str, str]) -> dict:
    model_config = {
        mode: {"modelName": model_id, "selectedModels": [{"modelId": model_id}]}
        for mode, model_id in modes
    }
    return {"aiSettings": {"modelConfig": model_config}}


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.delenv("CROSSLAB_HARNESS", raising=False)
    monkeypatch.delenv("CROSSLAB_AGENT_MODEL", raising=False)
    monkeypatch.delenv("CROSSLAB_AGENT_MODEL_DISPLAY", raising=False)
    monkeypatch.delenv("CROSSLAB_PROBE_CURSOR_IDE", raising=False)
    return home


def test_extract_prefers_composer_over_other_modes():
    blob = _application_user(
        ("agent", "claude-sonnet-4"),
        ("composer", "composer-2.5"),
        ("cmd-k", "gpt-4"),
    )
    assert extract_model_from_application_user(blob) == "composer-2.5"


def test_extract_falls_back_to_agent():
    blob = _application_user(("agent", "claude-sonnet-4"), ("cmd-k", "gpt-4"))
    assert extract_model_from_application_user(blob) == "claude-sonnet-4"


def test_extract_falls_back_to_first_remaining_mode():
    blob = _application_user(("cmd-k", "gpt-4"))
    assert extract_model_from_application_user(blob) == "gpt-4"


def test_probe_cursor_ide_parses_composer_model(tmp_path):
    db = _write_state_db(tmp_path / "state.vscdb", _application_user(("composer", "composer-2.5")))
    result = probe_cursor_ide(db)
    assert result is not None
    assert result.harness == "cursor"
    assert result.model_id == "composer-2.5"
    assert result.model_display == "Composer 2.5"
    assert result.source == "cursor_ide"
    assert result.confidence == 0.7
    assert result.config_path == db


def test_probe_cursor_ide_missing_file(tmp_path):
    assert probe_cursor_ide(tmp_path / "missing.vscdb") is None


def test_probe_cursor_ide_empty_table(tmp_path):
    db = _write_state_db(tmp_path / "state.vscdb", None)
    assert probe_cursor_ide(db) is None


def test_probe_cursor_ide_garbage_json(tmp_path):
    db = _write_state_db(tmp_path / "state.vscdb", None, raw_value=b"not-json")
    assert probe_cursor_ide(db) is None


def test_probe_cursor_ignores_ide_without_flag(isolated_home, tmp_path, monkeypatch):
    db = _write_state_db(tmp_path / "state.vscdb", _application_user(("composer", "composer-2.5")))
    monkeypatch.setattr(
        "crosslab.engine.harness_probes.cursor_ide.cursor_state_db_path",
        lambda: db,
    )
    assert probe_cursor() is None
    assert probe_cursor_ide(db) is not None


def test_probe_cursor_uses_ide_when_flag_set_and_no_cli(isolated_home, tmp_path, monkeypatch):
    db = _write_state_db(tmp_path / "state.vscdb", _application_user(("composer", "composer-2.5")))
    monkeypatch.setenv("CROSSLAB_PROBE_CURSOR_IDE", "1")
    monkeypatch.setattr(
        "crosslab.engine.harness_probes.cursor_ide.cursor_state_db_path",
        lambda: db,
    )
    result = probe_cursor()
    assert result is not None
    assert result.source == "cursor_ide"
    assert result.confidence == 0.7
    assert result.model_id == "composer-2.5"


def test_probe_cursor_cli_wins_over_ide(isolated_home, tmp_path, monkeypatch):
    db = _write_state_db(tmp_path / "state.vscdb", _application_user(("composer", "composer-2.5")))
    monkeypatch.setenv("CROSSLAB_PROBE_CURSOR_IDE", "1")
    monkeypatch.setattr(
        "crosslab.engine.harness_probes.cursor_ide.cursor_state_db_path",
        lambda: db,
    )
    cursor_dir = isolated_home / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "cli-config.json").write_text(json.dumps({"model": "gpt-5.6-sol"}), encoding="utf-8")

    result = probe_cursor()
    assert result is not None
    assert result.source == "config_file"
    assert result.model_id == "gpt-5.6-sol"
    assert result.confidence == 0.9


@pytest.mark.asyncio
async def test_node_startup_applies_ide_probe_without_persisting(isolated_home, tmp_path, monkeypatch):
    db = _write_state_db(tmp_path / "state.vscdb", _application_user(("composer", "composer-2.5")))
    monkeypatch.setenv("CROSSLAB_PROBE_CURSOR_IDE", "1")
    monkeypatch.setattr(
        "crosslab.engine.harness_probes.cursor_ide.cursor_state_db_path",
        lambda: db,
    )

    node_db = str(tmp_path / "node" / "probe-node.db")
    Path(node_db).parent.mkdir(parents=True, exist_ok=True)
    node = A2ANode(
        agent_id="probe-host",
        role=AgentRole.HOST,
        db_path=node_db,
        session_id="probe-session",
    )

    assert node.agent_profile.harness == "cursor"
    assert node.agent_profile.model_id == "composer-2.5"
    assert node.agent_profile.source == "cursor_ide"
    assert node.agent_profile.confidence == 0.7

    profile_path = Path(data_dir_from_db_path(node_db)) / "agent_profile.json"
    assert not profile_path.exists()

    transport = ASGITransport(app=node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/v1/a2a/session/profile")
        data = res.json()
        assert data["source"] == "cursor_ide"
        assert data["model_id"] == "composer-2.5"


@pytest.mark.asyncio
async def test_node_startup_skips_ide_without_flag(isolated_home, tmp_path, monkeypatch):
    db = _write_state_db(tmp_path / "state.vscdb", _application_user(("composer", "composer-2.5")))
    monkeypatch.setattr(
        "crosslab.engine.harness_probes.cursor_ide.cursor_state_db_path",
        lambda: db,
    )
    node = A2ANode(
        agent_id="probe-host",
        role=AgentRole.HOST,
        db_path=str(tmp_path / "skip.db"),
        session_id="skip-session",
    )
    assert not node.agent_profile.is_set() or node.agent_profile.source != "cursor_ide"


@pytest.mark.asyncio
async def test_doctor_reports_cursor_ide_without_failing(tmp_path):
    from crosslab.mcp.doctor import _add_profile_probe_checks

    db = _write_state_db(tmp_path / "state.vscdb", _application_user(("composer", "composer-2.5")))
    checks = []

    def add_check(name, ok, detail):
        checks.append({"name": name, "ok": ok, "detail": detail})

    import crosslab.engine.harness_probes.cursor_ide as cursor_ide

    original = cursor_ide.cursor_state_db_path
    cursor_ide.cursor_state_db_path = lambda: db
    try:
        _add_profile_probe_checks(add_check)
    finally:
        cursor_ide.cursor_state_db_path = original

    ide_check = next(c for c in checks if c["name"] == "profile_probe:cursor-ide")
    assert ide_check["ok"] is True
    assert "composer-2.5" in ide_check["detail"] or "Composer 2.5" in ide_check["detail"]
