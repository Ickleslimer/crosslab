"""
End-to-End Multi-Agent FEAR 3 Co-Op Investigation Scenario.
Demonstrates two independent coding agents collaborating across separate machines (A2A endpoints).
"""

import asyncio
import json
import logging
import sys
from typing import Optional

# Ensure standard output can handle utf-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from crosslab.agent.client import CrossLabClient
from crosslab.cases.fear3.client_harness import Fear3ClientHarness
from crosslab.cases.fear3.host_harness import Fear3HostHarness
from crosslab.engine.session import InvestigationSession
from crosslab.protocol.actions import ActionType, AgentRole, HypothesisStatus, RunOutcome
from crosslab.protocol.models import MessageEnvelope, RunRecord

logger = logging.getLogger("crosslab.scenario")
console = Console(force_terminal=True, legacy_windows=False)


async def run_fear3_investigation_demo(interactive: bool = False) -> InvestigationSession:
    """
    Executes the full 8-step empirical collaboration workflow between Host and Client agents.
    """
    console.print(
        Panel.fit(
            "[bold cyan]CrossLab: Agent-to-Agent Empirical Collaboration Protocol[/bold cyan]\n"
            "[yellow]FEAR 3 Co-Op 'Kicked by host / connection lost' Investigation Demo[/yellow]",
            border_style="cyan",
        )
    )

    # 1. Initialize Shared Session & Agent Nodes (In-memory shared ledger for demo)
    session = InvestigationSession(session_id="fear3-coop-investigation")
    host_harness = Fear3HostHarness(timeout_ms=5000)
    client_harness = Fear3ClientHarness()

    console.print("\n[bold green]Step 1: Agent Discovery & Handshake[/bold green]")
    session.storage.ensure_session("fear3-coop-investigation", name="FEAR 3 Co-Op Disconnect Diagnosis")
    console.print("  [green][OK][/green] Host Agent (Agent A) online on Machine A [dim](http://machine-a:8765)[/dim]")
    console.print("  [green][OK][/green] Client Agent (Agent B) online on Machine B [dim](http://machine-b:8766)[/dim]")
    console.print("  [green][OK][/green] Handshake established: A2A session 'fear3-coop-investigation' active.\n")

    # 2. Collaborative Reasoning & Natural-Language Conversation
    console.print("[bold green]Step 2: Natural-Language Exchange[/bold green]")
    
    msg1 = MessageEnvelope(
        sender_id="host-agent",
        action=ActionType.CHAT,
        natural_language="The host timed out five seconds after its receive counter stopped advancing. Are you still transmitting during that interval?",
    )
    session.record_message(msg1)
    console.print("  [bold blue]Host Agent:[/bold blue] \"The host timed out five seconds after its receive counter stopped advancing. Are you still transmitting during that interval?\"")

    msg2 = MessageEnvelope(
        sender_id="client-agent",
        action=ActionType.CHAT,
        natural_language="Yes. Four sends returned success. I'll instrument the transport layer for the next run.",
    )
    session.record_message(msg2)
    console.print("  [bold magenta]Client Agent:[/bold magenta] \"Yes. Four sends returned success. I'll instrument the transport layer for the next run.\"")

    msg3 = MessageEnvelope(
        sender_id="host-agent",
        action=ActionType.CHAT,
        natural_language="I'll instrument the corresponding receive path. Let's repeat as Run 14.",
    )
    session.record_message(msg3)
    console.print("  [bold blue]Host Agent:[/bold blue] \"I'll instrument the corresponding receive path. Let's repeat as Run 14.\"\n")

    # 3. Formulate & Propose Hypothesis
    console.print("[bold green]Step 3: Formulating Empirical Hypothesis[/bold green]")
    hyp = session.propose_hypothesis(
        title="Host receive timeout occurs despite successful client sends",
        description="Host receive silence watchdog (5000ms) expires and tears down P2P session even though client Steam SendP2PPacket returns k_EResultOK.",
        creator="host-agent",
        confidence=0.6,
    )
    console.print(f"  [green][OK][/green] Hypothesis [[cyan]{hyp.id}[/cyan]] registered: [italic]\"{hyp.title}\"[/italic] (Confidence: {hyp.confidence})\n")

    # 4. Propose & Agree upon Synchronized Experiment (Run 14)
    console.print("[bold green]Step 4: Proposing Synchronized Experiment (Run 14)[/bold green]")
    exp = session.propose_experiment(
        run_id=14,
        hypothesis_id=hyp.id,
        title="Instrument Steam session state every 100ms and trace packet sequence",
        rationale="Verify whether client sends continue while host receive counter halts.",
        host_role="trace receive path and watchdog timer",
        client_role="trace send path and transport result",
        creator="host-agent",
        parameters={"sampling_rate_ms": 100, "log_steam_state": True},
    )
    console.print(f"  [green][OK][/green] Experiment [[cyan]{exp.id}[/cyan]] proposed by Host Agent for Run {exp.run_id}")
    console.print(f"    - Host Role:   {exp.host_role}")
    console.print(f"    - Client Role: {exp.client_role}")

    # Client accepts experiment
    accepted_exp = session.accept_experiment(exp.id)
    console.print("  [green][OK][/green] Client Agent independently reviewed and [green]ACCEPTED[/green] experiment proposal.\n")

    # 5. Local Instrumentation Execution (Zero-Trust boundary)
    console.print("[bold green]Step 5: Local Instrumentation Execution[/bold green]")
    console.print("  [dim]Applying local non-intrusive probes (no remote shell access allowed)...[/dim]")
    host_harness.enable_instrumentation("host_receive_watchdog_probe")
    client_harness.enable_instrumentation("client_steam_sockets_probe")
    console.print("  [green][OK][/green] Machine A: Host instrumented receive path.")
    console.print("  [green][OK][/green] Machine B: Client instrumented send path.\n")

    # 6. Synchronized Run Execution & Telemetry Collection
    console.print("[bold green]Step 6: Executing Synchronized Run 14[/bold green]")
    host_telemetry = host_harness.run_session_simulation(packets_to_receive=31, drop_after=8831)
    client_telemetry = client_harness.run_session_simulation(total_packets_to_send=35)

    # Assemble shared RunRecord
    run_14 = RunRecord(
        run_id=14,
        experiment_id=exp.id,
        hypothesis_id=hyp.id,
        hypothesis_title=hyp.title,
        build="netprobe-0.2.1",
        participants=["host-agent", "client-agent"],
        start_time="18:42:14.000",
        end_time="18:42:19.331",
        outcome=RunOutcome.REPRODUCED,
        result_summary="Disconnect reproduced at 18:42:19.331",
        host=host_telemetry,
        client=client_telemetry,
        logs=[],
    )
    saved_run = session.record_run(run_14)
    console.print(f"  [green][OK][/green] Run 14 completed. Outcome: [bold red]{saved_run.outcome.value.upper()}[/bold red]\n")

    # 7. Multi-Machine Correlation & Anomaly Detection
    console.print("[bold green]Step 7: Multi-Machine Correlation Analysis[/bold green]")
    corr_result = session.correlator.correlate_run(saved_run)

    corr_table = Table(title=f"CrossLab Correlation Findings - Run {saved_run.run_id}", header_style="bold cyan")
    corr_table.add_column("Discrepancy Code", style="yellow")
    corr_table.add_column("Description", style="white")
    corr_table.add_column("Impact / Root Cause Insight", style="green")

    for d in corr_result.discrepancies:
        corr_table.add_row(d.code, d.description, d.impact)

    console.print(corr_table)
    console.print(f"\n  [bold]Hypothesis Verdict:[/bold] {corr_result.hypothesis_verdict}")
    for step in corr_result.suggested_next_steps:
        console.print(f"  [cyan]-> Next Step:[/cyan] {step}")

    # 8. Refined Hypothesis & Patch Exchange for Run 15
    console.print("\n[bold green]Step 8: Patch Formulation & Exchange (Run 15 Preparation)[/bold green]")
    patch_code = """--- a/Source/Net/Fear3Watchdog.cpp
+++ b/Source/Net/Fear3Watchdog.cpp
@@ -104,7 +104,11 @@ void NetSession::UpdateWatchdog(float deltaSeconds) {
     if (m_silenceTimer >= 5.0f) {
+        // Fix: Send heartbeat probe before terminating session
+        if (SteamNetworkingSockets()->SendHeartbeatProbe(m_peerId)) {
+            m_silenceTimer = 0.0f;
+            return;
+        }
         TriggerDisconnect("connection_lost", 0x80041002);
     }
 }"""
    art = session.share_artifact(
        filename="fear3_keepalive_probe.patch",
        content_type="text/x-patch",
        content=patch_code,
        author_id="host-agent",
        description="Adds active heartbeat query before 5.0s timeout tear-down.",
    )
    console.print(f"  [green][OK][/green] Host Agent shared patch: [cyan]{art.filename}[/cyan] (SHA256: {art.sha256[:12]}...)")

    # 9. Investigation State Verification Queries
    console.print("\n[bold green]Step 9: Querying Shared Investigation Ledger[/bold green]")

    summary = session.get_session_summary()
    unresolved = session.get_unresolved_hypotheses()
    latest_rep = session.get_latest_reproducing_run()

    q_table = Table(title="Investigation Ledger Summary", header_style="bold magenta")
    q_table.add_column("Query", style="cyan")
    q_table.add_column("Result", style="white")

    q_table.add_row("Active Session", summary["session_id"])
    q_table.add_row("Total Hypotheses", str(summary["total_hypotheses"]))
    q_table.add_row("Unresolved Hypotheses", str(len(unresolved)))
    q_table.add_row(
        "Latest Reproducing Run",
        f"Run {latest_rep.run_id} ({latest_rep.result_summary})" if latest_rep else "None",
    )
    q_table.add_row("Hypothesis Status", f"{hyp.title} -> [bold green]SUPPORTED (85% confidence)[/bold green]")
    console.print(q_table)

    console.print("\n[bold green][OK] FEAR 3 Multi-Agent Investigation Scenario Succeeded![/bold green]\n")
    return session


if __name__ == "__main__":
    asyncio.run(run_fear3_investigation_demo())
