"""
Unit and integration tests for CrossLab human-readable transcript recording.
"""

from pathlib import Path
import tempfile
import pytest
from httpx import ASGITransport, AsyncClient

from crosslab.engine.session import InvestigationSession
from crosslab.engine.storage import Storage
from crosslab.engine.transcript import TranscriptRecorder, format_sender_badge, format_action_tag
from crosslab.mcp.server import CrossLabMCPServer
from crosslab.protocol.actions import ActionType, AgentRole, RunOutcome
from crosslab.protocol.models import MessageEnvelope, RunRecord, utc_now_iso
from crosslab.transport.node import A2ANode


def test_transcript_formatting():
    assert "Agent A (Host)" in format_sender_badge("agent-host")
    assert "Agent B (Client)" in format_sender_badge("agent-client")
    assert "Human Host" in format_sender_badge("human-host")
    assert "CHAT" in format_action_tag(ActionType.CHAT)
    assert "PROPOSE_HYPOTHESIS" in format_action_tag(ActionType.PROPOSE_HYPOTHESIS)


def test_transcript_streaming_messages():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        transcripts_dir = str(Path(tmpdir) / "transcripts")

        session = InvestigationSession(
            session_id="test-session",
            db_path=db_path,
            transcript_dir=transcripts_dir,
        )

        try:
            msg1 = MessageEnvelope(
                sender_id="agent-host",
                action=ActionType.CHAT,
                natural_language="Hello Agent B, let us start testing.",
            )
            session.record_message(msg1)

            msg2 = MessageEnvelope(
                sender_id="agent-client",
                action=ActionType.CHAT,
                natural_language="Acknowledged Agent A. Ready for Run 1.",
            )
            session.record_message(msg2)

            transcript_path = Path(session.get_transcript_path())
            assert transcript_path.exists()

            content = transcript_path.read_text(encoding="utf-8")
            assert "CrossLab Investigation Transcript: test-session" in content
            assert "Agent A (Host)" in content
            assert "Hello Agent B, let us start testing." in content
            assert "Agent B (Client)" in content
            assert "Acknowledged Agent A. Ready for Run 1." in content
        finally:
            session.close()


def test_transcript_hypotheses_and_runs():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        transcripts_dir = str(Path(tmpdir) / "transcripts")

        session = InvestigationSession(
            session_id="test-session-2",
            db_path=db_path,
            transcript_dir=transcripts_dir,
        )

        try:
            hyp = session.propose_hypothesis(
                title="Keepalive Watchdog Timeout",
                description="The 90-second disconnect is caused by missing periodic pulse packets.",
                creator="agent-host",
                confidence=0.85,
            )

            run = RunRecord(
                run_id=1,
                session_id="test-session-2",
                hypothesis_id=hyp.id,
                hypothesis_title=hyp.title,
                build="netprobe-0.1",
                outcome=RunOutcome.REPRODUCED,
                result_summary="P2P disconnect occurred at 90.2s elapsed.",
                host={"disconnect_reason": "timeout"},
                client={"disconnect_reason": "timeout"},
            )
            session.record_run(run)

            transcript_path = Path(session.get_transcript_path())
            assert transcript_path.exists()

            content = transcript_path.read_text(encoding="utf-8")
            assert "Keepalive Watchdog Timeout" in content
            assert "The 90-second disconnect is caused by missing periodic pulse packets." in content
            assert "Run 1 Result:" in content
            assert "REPRODUCED" in content
        finally:
            session.close()


def test_full_markdown_export():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        storage = Storage(db_path=db_path, enable_transcript=False)

        try:
            msg = MessageEnvelope(
                session_id="export-test",
                sender_id="agent-host",
                action=ActionType.CHAT,
                natural_language="Export test message",
            )
            storage.save_message(msg)

            recorder = TranscriptRecorder(transcript_dir=tmpdir, session_id="export-test")
            full_md = recorder.generate_full_markdown(storage)

            assert "CrossLab Investigation Transcript: export-test" in full_md
            assert "**Total Messages:** 1" in full_md
            assert "Export test message" in full_md
        finally:
            storage.close()


def test_mcp_get_transcript():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        session = InvestigationSession(session_id="mcp-test", db_path=db_path, transcript_dir=tmpdir)
        try:
            session.record_message(
                MessageEnvelope(
                    sender_id="agent-host",
                    action=ActionType.CHAT,
                    natural_language="Testing MCP transcript retrieval",
                )
            )

            mcp_server = CrossLabMCPServer()
            mcp_server.session = session

            result = mcp_server.execute_tool("crosslab_get_transcript", {})
            assert result["status"] == "ok"
            assert "Testing MCP transcript retrieval" in result["transcript"]
        finally:
            session.close()


@pytest.mark.asyncio
async def test_node_transcript_endpoint():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        node = A2ANode(
            agent_id="test-agent",
            role=AgentRole.HOST,
            session_id="api-test",
            db_path=db_path,
            transcript_dir=tmpdir,
        )
        try:
            node.session.record_message(
                MessageEnvelope(
                    sender_id="agent-host",
                    action=ActionType.CHAT,
                    natural_language="Testing HTTP GET transcript endpoint",
                )
            )

            transport = ASGITransport(app=node.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.get("/v1/a2a/transcript")
                assert res.status_code == 200
                assert "Testing HTTP GET transcript endpoint" in res.text
        finally:
            node.session.close()
