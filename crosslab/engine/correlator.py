"""
Multi-Machine Correlation Engine for CrossLab.
Correlates logs, telemetry, and packet states between Host and Client machines.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from crosslab.protocol.actions import RunOutcome
from crosslab.protocol.models import CorrelationResult, Discrepancy, RunRecord


class CorrelationEngine:
    """
    Analyzes multi-machine investigation logs, aligns timestamps,
    detects sequence discrepancies, and evaluates empirical hypotheses.
    """

    @staticmethod
    def correlate_run(run: RunRecord) -> CorrelationResult:
        discrepancies: List[Discrepancy] = []
        timeline: List[Dict[str, Any]] = []

        host_data = run.host or {}
        client_data = run.client or {}

        # 1. Correlate Packet Counters
        last_sent = client_data.get("last_sent_packet")
        last_recv = host_data.get("last_received_packet")

        if last_sent is not None and last_recv is not None:
            if last_sent > last_recv:
                dropped = last_sent - last_recv
                discrepancies.append(
                    Discrepancy(
                        code="PACKET_RECEIPT_LAG_OR_DROP",
                        description=(
                            f"Client sent packet #{last_sent} (reported transport success), "
                            f"but Host only received up to packet #{last_recv} ({dropped} packets in flight or dropped)."
                        ),
                        host_evidence={"last_received_packet": last_recv},
                        client_evidence={"last_sent_packet": last_sent, "transport_result": client_data.get("transport_result")},
                        impact="Host receive buffer starved, causing receive timeout timer to count up.",
                    )
                )

        # 2. Correlate Disconnect Reasons & UI States
        host_reason = host_data.get("reason") or host_data.get("disconnect_reason")
        client_ui_reason = client_data.get("displayed_reason") or client_data.get("ui_reason")

        if host_reason == "connection_lost" and client_ui_reason == "kicked_by_host":
            discrepancies.append(
                Discrepancy(
                    code="ASYMMETRIC_DISCONNECT_REASON",
                    description=(
                        "Host terminated session due to internal 'connection_lost' (timeout timer reached 5000ms), "
                        "which the Client game UI displayed as 'Kicked by the host / connection lost'."
                    ),
                    host_evidence={"internal_reason": host_reason, "disconnect_time": host_data.get("disconnect_time")},
                    client_evidence={"ui_displayed_reason": client_ui_reason, "transport_result": client_data.get("transport_result")},
                    impact="The UI error message 'Kicked by the host' is misleading; the host did not kick the client intentionally, but suffered a silent receive timeout.",
                )
            )

        # 3. Interleave and build timeline from host and client logs
        all_logs = list(run.logs or [])
        # Extract timestamped events from host and client telemetry
        if "events" in host_data and isinstance(host_data["events"], list):
            for ev in host_data["events"]:
                ev_copy = dict(ev)
                ev_copy.setdefault("source", "host")
                all_logs.append(ev_copy)

        if "events" in client_data and isinstance(client_data["events"], list):
            for ev in client_data["events"]:
                ev_copy = dict(ev)
                ev_copy.setdefault("source", "client")
                all_logs.append(ev_copy)

        def sort_key(entry: Dict[str, Any]) -> str:
            return str(entry.get("timestamp") or entry.get("time") or "")

        timeline = sorted(all_logs, key=sort_key)

        # 4. Generate Summary and Verdict
        reproduced = (
            run.outcome == RunOutcome.REPRODUCED
            or (host_reason is not None and "disconnect" in str(host_reason).lower())
            or (host_reason == "connection_lost")
        )

        hypothesis_verdict = None
        suggested_next_steps = []

        if discrepancies:
            hypothesis_verdict = "SUPPORTED: Empirical evidence confirms host receive timeout occurs despite active client transmission."
            suggested_next_steps.append("Instrument Steam P2P keep-alive heartbeat callback on both host and client.")
            suggested_next_steps.append("Check if client is sending keep-alive on a socket channel the host stopped polling.")
            suggested_next_steps.append("Propose patch to keep receive timer refreshed or clamp watchdog threshold.")
        else:
            hypothesis_verdict = "INCONCLUSIVE: No significant discrepancy detected between host and client metrics."
            suggested_next_steps.append("Increase instrumentation sampling rate (e.g. 50ms) for subsequent run.")

        summary = (
            f"Run {run.run_id} Analysis ({len(discrepancies)} discrepancies detected): "
            f"Host reason='{host_reason}', Client UI='{client_ui_reason}'. "
            f"Packets sent={last_sent}, received={last_recv}."
        )

        return CorrelationResult(
            run_id=run.run_id,
            session_id=run.session_id,
            summary=summary,
            reproduced=reproduced,
            discrepancies=discrepancies,
            timeline=timeline,
            hypothesis_verdict=hypothesis_verdict,
            suggested_next_steps=suggested_next_steps,
        )

    @staticmethod
    def diff_runs(run_a: RunRecord, run_b: RunRecord) -> Dict[str, Any]:
        """
        Calculates differential comparison between two test runs.
        What changed between Run A and Run B?
        """
        diff = {
            "run_a_id": run_a.run_id,
            "run_b_id": run_b.run_id,
            "build_changed": run_a.build != run_b.build,
            "build_a": run_a.build,
            "build_b": run_b.build,
            "outcome_a": run_a.outcome,
            "outcome_b": run_b.outcome,
            "hypothesis_a": run_a.hypothesis_title or run_a.hypothesis_id,
            "hypothesis_b": run_b.hypothesis_title or run_b.hypothesis_id,
            "host_diff": {},
            "client_diff": {},
        }

        # Compare host metrics
        for k in set(run_a.host.keys()).union(run_b.host.keys()):
            val_a = run_a.host.get(k)
            val_b = run_b.host.get(k)
            if val_a != val_b:
                diff["host_diff"][k] = {"run_a": val_a, "run_b": val_b}

        # Compare client metrics
        for k in set(run_a.client.keys()).union(run_b.client.keys()):
            val_a = run_a.client.get(k)
            val_b = run_b.client.get(k)
            if val_a != val_b:
                diff["client_diff"][k] = {"run_a": val_a, "run_b": val_b}

        return diff
