"""
CrossLab Command Line Interface.
"""

import argparse
import asyncio
import os
import sys
from typing import Optional

# Ensure standard output can handle utf-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from rich.console import Console
from rich.table import Table
import uvicorn

from crosslab.cases.fear3.scenario import run_fear3_investigation_demo
from crosslab.engine.session import InvestigationSession
from crosslab.mcp.server import CrossLabMCPServer
from crosslab.protocol.actions import AgentRole
from crosslab.sidecar import resolve_data_paths
from crosslab.transport.node import A2ANode

console = Console(force_terminal=True, legacy_windows=False)


def cmd_demo(args: argparse.Namespace) -> None:
    if args.case == "fear3":
        asyncio.run(run_fear3_investigation_demo(interactive=args.interactive))
    else:
        console.print(f"[red]Unknown case study '{args.case}'. Available: fear3[/red]")


def cmd_mcp(args: argparse.Namespace) -> None:
    server = CrossLabMCPServer(node_url=args.node_url)
    if args.test:
        tools = server.get_tool_definitions()
        console.print(f"[bold green]CrossLab MCP Server[/bold green] ({len(tools)} tools registered):")
        for t in tools:
            console.print(f"  - [cyan]{t['name']}[/cyan]: {t['description']}")
        return

    for line in sys.stdin:
        if not line.strip():
            continue
        response = server.handle_json_rpc(line.strip())
        print(response, flush=True)


def cmd_node(args: argparse.Namespace) -> None:
    role = AgentRole(args.role)
    db_path, transcript_dir = resolve_data_paths(args.data_dir, args.session, args.db, args.transcript_dir)
    node = A2ANode(
        agent_id=args.agent_id or f"agent-{role.value}",
        role=role,
        host=args.host,
        port=args.port,
        session_id=args.session,
        db_path=db_path,
        initial_peer_url=args.peer,
        transcript_dir=transcript_dir,
    )
    console.print(f"[bold green]Starting CrossLab A2A Node[/bold green]")
    console.print(f"  Agent ID:   [cyan]{node.agent_id}[/cyan]")
    console.print(f"  Role:       [yellow]{node.role.value}[/yellow]")
    console.print(f"  Endpoint:   [blue]{node.endpoint_url}[/blue]")
    console.print(f"  Agent Card: [blue]{node.endpoint_url}/.well-known/agent-card.json[/blue]")
    console.print(f"  Session ID: [magenta]{node.session_id}[/magenta]")

    if args.peer:
        console.print(f"  Configured initial peer: [blue]{args.peer}[/blue] (will connect via lifespan startup)")

    uvicorn.run(node.app, host=args.host, port=args.port, log_level="info")


def cmd_status(args: argparse.Namespace) -> None:
    session = InvestigationSession(session_id=args.session, db_path=args.db or f"./crosslab_{args.session}.db")
    summary = session.get_session_summary()

    table = Table(title=f"CrossLab Session Status: {args.session}", header_style="bold cyan")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Session ID", summary["session_id"])
    table.add_row("Peers Count", str(summary["peers_count"]))
    table.add_row("Total Hypotheses", str(summary["total_hypotheses"]))
    table.add_row("Unresolved Hypotheses", str(len(summary["unresolved_hypotheses"])))
    table.add_row("Total Experiments", str(summary["total_experiments"]))
    table.add_row("Total Runs Recorded", str(summary["total_runs"]))
    table.add_row("Latest Reproduced Run ID", str(summary["latest_reproduced_run_id"]))

    console.print(table)


def cmd_watch(args: argparse.Namespace) -> None:
    from crosslab.agent.watcher import watch_events
    from crosslab.agent.wakeup import create_wakeup_backend

    backend = create_wakeup_backend(
        args.wake,
        webhook_url=args.webhook,
        wake_file=args.wake_file,
    )
    asyncio.run(
        watch_events(
            node_url=args.node_url,
            backend=backend,
            agent_id=args.agent_id,
            local_role_hint=args.role,
            verbose=args.verbose,
        )
    )


def cmd_transcript(args: argparse.Namespace) -> None:
    session = InvestigationSession(
        session_id=args.session,
        db_path=args.db or f"./crosslab_{args.session}.db",
        transcript_dir=args.transcript_dir,
    )
    recorder = session.storage.get_transcript_recorder(args.session)
    if not recorder:
        from crosslab.engine.transcript import TranscriptRecorder
        recorder = TranscriptRecorder(transcript_dir=args.transcript_dir, session_id=args.session)

    path = recorder.write_full_transcript(session.storage)
    if args.export and str(path) != str(os.path.abspath(args.export)):
        import shutil
        shutil.copy(str(path), args.export)
        path = os.path.abspath(args.export)

    console.print(f"[bold green]Human-readable transcript generated:[/bold green] [cyan]{path}[/cyan]")
    if getattr(args, "print_stdout", False):
        with open(path, "r", encoding="utf-8") as f:
            print(f.read())


def main() -> None:
    parser = argparse.ArgumentParser(description="CrossLab: Multi-Machine A2A Collaboration Protocol")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # demo
    demo_parser = subparsers.add_parser("demo", help="Run an empirical investigation demo")
    demo_parser.add_argument("case", nargs="?", default="fear3", help="Case study to run (default: fear3)")
    demo_parser.add_argument("--interactive", action="store_true", help="Prompt between steps")

    # mcp
    mcp_parser = subparsers.add_parser("mcp", help="Run MCP server for IDEs & AI coding agents")
    mcp_parser.add_argument("--node-url", type=str, default=None, help="Connect MCP to local node URL (e.g. http://127.0.0.1:8000)")
    mcp_parser.add_argument("--test", action="store_true", help="List registered MCP tools and exit")

    # node
    node_parser = subparsers.add_parser("node", help="Start an A2A agent node")
    node_parser.add_argument("--role", choices=["host", "client", "observer"], default="host", help="Agent machine role")
    node_parser.add_argument("--agent-id", type=str, default=None, help="Unique Agent ID")
    node_parser.add_argument("--host", type=str, default="127.0.0.1", help="Binding host")
    node_parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    node_parser.add_argument("--session", type=str, default="default", help="Session ID")
    node_parser.add_argument("--peer", type=str, default=None, help="Remote peer URL to connect to")
    node_parser.add_argument("--data-dir", type=str, default=None, help="Root directory for DB and transcripts")
    node_parser.add_argument("--db", type=str, default=None, help="SQLite database path")
    node_parser.add_argument("--transcript-dir", type=str, default=None, help="Directory to store transcripts")

    # relay
    relay_parser = subparsers.add_parser("relay", help="Start a central P2P relay hub across NATs/firewalls")
    relay_parser.add_argument("--host", type=str, default="0.0.0.0", help="Binding host")
    relay_parser.add_argument("--port", type=int, default=8080, help="Port to listen on")

    # status
    status_parser = subparsers.add_parser("status", help="Show investigation session summary")
    status_parser.add_argument("--session", type=str, default="default", help="Session ID")
    status_parser.add_argument("--db", type=str, default=None, help="SQLite database path")

    # transcript
    transcript_parser = subparsers.add_parser("transcript", help="Export or view human-readable session transcript")
    transcript_parser.add_argument("--session", type=str, default="default", help="Session ID")
    transcript_parser.add_argument("--db", type=str, default=None, help="SQLite database path")
    transcript_parser.add_argument("--export", type=str, default=None, help="Export output file path (.md)")
    transcript_parser.add_argument("--transcript-dir", type=str, default=None, help="Directory to store transcripts")
    transcript_parser.add_argument("--print", dest="print_stdout", action="store_true", help="Print transcript to stdout")

    # watch
    watch_parser = subparsers.add_parser("watch", help="Watch A2A SSE events and wake the agent harness on peer activity")
    watch_parser.add_argument("--node-url", type=str, default="http://127.0.0.1:8765", help="Local CrossLab node URL")
    watch_parser.add_argument(
        "--wake",
        choices=["stdout", "file", "webhook", "antigravity", "opencode", "codex", "auto"],
        default="stdout",
        help="Wakeup backend (auto reads CROSSLAB_HARNESS env)",
    )
    watch_parser.add_argument("--webhook", type=str, default=None, help="Webhook URL for webhook/codex wakeup mode")
    watch_parser.add_argument("--wake-file", type=str, default=None, help="Path for file-based wakeup (default: %%TEMP%%/crosslab_wakeup.json)")
    watch_parser.add_argument("--agent-id", type=str, default="agent-local", help="Local agent ID for self-filtering")
    watch_parser.add_argument("--role", type=str, default="host", choices=["host", "client"], help="Local role hint for peer detection")
    watch_parser.add_argument("--verbose", action="store_true", help="Print full event details to stdout")

    args = parser.parse_args()

    if args.command == "demo":
        cmd_demo(args)
    elif args.command == "mcp":
        cmd_mcp(args)
    elif args.command == "node":
        cmd_node(args)
    elif args.command == "relay":
        from crosslab.transport.relay import run_relay
        run_relay(port=args.port, host=args.host)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "transcript":
        cmd_transcript(args)
    elif args.command == "watch":
        cmd_watch(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
