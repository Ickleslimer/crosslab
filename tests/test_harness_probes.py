"""Tests for Tier A harness config probes."""

import json
import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from crosslab.engine.agent_profile import AgentProfile, resolve_local_profile
from crosslab.engine.harness_probes import detect_agent_profile, detect_summary, probe_all
from crosslab.engine.harness_probes.codex import probe_codex
from crosslab.engine.harness_probes.cursor_cli import probe_cursor_cli
from crosslab.engine.harness_probes.opencode import probe_opencode
from crosslab.protocol.actions import AgentRole
from crosslab.transport.node import A2ANode


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


def test_probe_codex(fake_home):
    codex_dir = fake_home / ".codex"
    codex_dir.mkdir()
    config = codex_dir / "config.toml"
    config.write_text('model = "gpt-5.6-sol"\nmodel_provider = "openai"\n', encoding="utf-8")

    result = probe_codex()
    assert result is not None
    assert result.harness == "codex"
    assert result.model_id == "gpt-5.6-sol"
    assert result.model_display == "GPT Sol 5.6"


def test_probe_opencode_json(fake_home):
    opencode_dir = fake_home / ".config" / "opencode"
    opencode_dir.mkdir(parents=True)
    config = opencode_dir / "opencode.json"
    config.write_text(json.dumps({"model": "anthropic/claude-sonnet-4"}), encoding="utf-8")

    result = probe_opencode()
    assert result is not None
    assert result.harness == "opencode"
    assert result.model_id == "anthropic/claude-sonnet-4"


def test_probe_opencode_jsonc(fake_home):
    opencode_dir = fake_home / ".config" / "opencode"
    opencode_dir.mkdir(parents=True)
    config = opencode_dir / "opencode.jsonc"
    config.write_text(
        '{\n  // default model\n  "model": "openai/gpt-4"\n}\n',
        encoding="utf-8",
    )

    result = probe_opencode()
    assert result is not None
    assert result.model_id == "openai/gpt-4"


def test_probe_cursor_cli_string_model(fake_home):
    cursor_dir = fake_home / ".cursor"
    cursor_dir.mkdir()
    config = cursor_dir / "cli-config.json"
    config.write_text(json.dumps({"model": "composer-2.5"}), encoding="utf-8")

    result = probe_cursor_cli()
    assert result is not None
    assert result.harness == "cursor"
    assert result.model_id == "composer-2.5"
    assert result.model_display == "Composer 2.5"


def test_probe_cursor_cli_object_model(fake_home):
    cursor_dir = fake_home / ".cursor"
    cursor_dir.mkdir()
    config = cursor_dir / "cli-config.json"
    config.write_text(json.dumps({"model": {"modelId": "claude-sonnet-4"}}), encoding="utf-8")

    result = probe_cursor_cli()
    assert result is not None
    assert result.model_id == "claude-sonnet-4"


def test_detect_single_candidate(fake_home):
    codex_dir = fake_home / ".codex"
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text('model = "gpt-5.6-sol"\n', encoding="utf-8")

    profile = detect_agent_profile()
    assert profile is not None
    assert profile.harness == "codex"
    assert profile.source == "config_file"
    assert profile.confidence == 0.9


def test_detect_ambiguous_returns_none(fake_home):
    codex_dir = fake_home / ".codex"
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text('model = "gpt-5.6-sol"\n', encoding="utf-8")

    cursor_dir = fake_home / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "cli-config.json").write_text(json.dumps({"model": "composer-2.5"}), encoding="utf-8")

    profile = detect_agent_profile()
    assert profile is None

    candidates, selected = detect_summary()
    assert len(candidates) == 2
    assert selected is None


def test_detect_with_harness_hint(fake_home):
    codex_dir = fake_home / ".codex"
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text('model = "gpt-5.6-sol"\n', encoding="utf-8")

    cursor_dir = fake_home / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "cli-config.json").write_text(json.dumps({"model": "composer-2.5"}), encoding="utf-8")

    profile = detect_agent_profile(harness_hint="cursor")
    assert profile is not None
    assert profile.harness == "cursor"


def test_resolve_local_profile_detected_branch():
    stored = AgentProfile()
    detected = AgentProfile(
        harness="codex",
        model_id="gpt-5",
        model_display="GPT-5",
        source="config_file",
        confidence=0.9,
    )
    resolved = resolve_local_profile(stored, detected)
    assert resolved.harness == "codex"
    assert resolved.source == "config_file"


def test_resolve_local_profile_env_wins_over_detected(monkeypatch):
    monkeypatch.setenv("CROSSLAB_HARNESS", "codex")
    monkeypatch.setenv("CROSSLAB_AGENT_MODEL", "env-model")
    stored = AgentProfile()
    detected = AgentProfile(
        harness="cursor",
        model_id="composer-2.5",
        model_display="Composer 2.5",
        source="config_file",
        confidence=0.9,
    )
    resolved = resolve_local_profile(stored, detected)
    assert resolved.model_id == "env-model"
    assert resolved.source == "env"


def test_resolve_local_profile_manual_wins_over_detected():
    stored = AgentProfile(
        harness="antigravity",
        model_id="gemini-flash",
        model_display="Gemini Flash",
        source="manual",
        confidence=1.0,
    )
    detected = AgentProfile(
        harness="codex",
        model_id="gpt-5",
        model_display="GPT-5",
        source="config_file",
        confidence=0.9,
    )
    resolved = resolve_local_profile(stored, detected)
    assert resolved.harness == "antigravity"


@pytest.mark.asyncio
async def test_node_startup_applies_codex_probe(fake_home, tmp_path, monkeypatch):
    monkeypatch.delenv("CROSSLAB_HARNESS", raising=False)
    monkeypatch.delenv("CROSSLAB_AGENT_MODEL", raising=False)
    monkeypatch.delenv("CROSSLAB_AGENT_MODEL_DISPLAY", raising=False)

    codex_dir = fake_home / ".codex"
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text('model = "gpt-5.6-sol"\n', encoding="utf-8")

    db_path = str(tmp_path / "probe-node.db")
    node = A2ANode(
        agent_id="probe-host",
        role=AgentRole.HOST,
        db_path=db_path,
        session_id="probe-session",
    )

    assert node.agent_profile.harness == "codex"
    assert node.agent_profile.model_id == "gpt-5.6-sol"
    assert node.agent_profile.source == "config_file"
    assert node.agent_profile.confidence == 0.9

    transport = ASGITransport(app=node.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/v1/a2a/session/profile")
        data = res.json()
        assert data["harness"] == "codex"
        assert data["source"] == "config_file"


def test_probe_all_with_hint_filters(fake_home):
    codex_dir = fake_home / ".codex"
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text('model = "gpt-5.6-sol"\n', encoding="utf-8")

    all_results = probe_all()
    assert len(all_results) == 1

    codex_only = probe_all(harness_hint="codex")
    assert len(codex_only) == 1
    assert codex_only[0].harness == "codex"

    missing = probe_all(harness_hint="opencode")
    assert missing == []
