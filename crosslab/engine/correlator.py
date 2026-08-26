"""
Multi-Machine Correlation Engine for CrossLab.
Discovers empirical facts across distributed timelines and delegates to pluggable analyzers.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from crosslab.engine.analyzers import (
    BaseAnalyzer,
    Fear3CoopAnalyzer,
    PacketSequenceAnalyzer,
    RequestResponseAnalyzer,
    TemporalAnalyzer,
)
from crosslab.protocol.actions import RunOutcome
from crosslab.protocol.models import CorrelationResult, Discrepancy, RunRecord


class CorrelationEngine:
    """
    Coordinates distributed investigation correlation by executing registered analyzers
    and building temporal fact timelines.
    """

    def __init__(self, analyzers: Optional[List[BaseAnalyzer]] = None):
        self.analyzers: List[BaseAnalyzer] = analyzers or [
            TemporalAnalyzer(),
            PacketSequenceAnalyzer(),
            RequestResponseAnalyzer(),
            Fear3CoopAnalyzer(),
        ]

    def register_analyzer(self, analyzer: BaseAnalyzer) -> None:
        self.analyzers.append(analyzer)

    def correlate_run(self, run: RunRecord) -> CorrelationResult:
        discrepancies: List[Discrepancy] = []
        temporal_insights: List[str] = []

        # 1. Execute all pluggable analyzers
        for analyzer in self.analyzers:
            try:
                disc = analyzer.analyze(run)
                discrepancies.extend(disc)
                insights = analyzer.get_temporal_insights(run)
                temporal_insights.extend(insights)
            except Exception as e:
                discrepancies.append(
                    Discrepancy(
                        code="ANALYZER_EXECUTION_ERROR",
                        analyzer=analyzer.name,
                        description=f"Analyzer {analyzer.name} encountered error: {str(e)}",
                        impact="Partial analysis only",
                    )
                )

        # 2. Interleave and build timeline from host and client logs
        all_logs: List[Dict[str, Any]] = list(run.logs or [])
        host_data = run.host or {}
        client_data = run.client or {}

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
            # Monotonic first if available, otherwise wall time / string
            mono = entry.get("monotonic_ns")
            if mono is not None:
                return f"mono_{mono:020d}"
            return str(entry.get("timestamp") or entry.get("time") or entry.get("wall_time") or "")

        timeline = sorted(all_logs, key=sort_key)

        # 3. Determine if failure reproduced
        host_reason = host_data.get("reason") or host_data.get("disconnect_reason")
        reproduced = (
            run.outcome == RunOutcome.REPRODUCED
            or (host_reason is not None and "disconnect" in str(host_reason).lower())
            or (host_reason == "connection_lost")
            or any(d.code == "PACKET_SEQUENCE_GAP" for d in discrepancies)
        )

        # 4. Generate Verdict and Next Steps based on empirical facts
        hypothesis_verdict = None
        suggested_next_steps: List[str] = []

        if discrepancies:
            disc_codes = [d.code for d in discrepancies]
            hypothesis_verdict = f"SUPPORTED: {len(discrepancies)} empirical discrepancies identified ({', '.join(disc_codes)})."
            suggested_next_steps.append("Examine transport vs application layer socket queue synchronization.")
            suggested_next_steps.append("Validate keep-alive heartbeat probe frequency during high send/recv load.")
            suggested_next_steps.append("Formulate and test defensive watchdog heartbeat patch.")
        else:
            hypothesis_verdict = "INCONCLUSIVE: No significant discrepancy detected between distributed node observations."
            suggested_next_steps.append("Increase instrumentation trace frequency on both nodes for the next run.")

        summary = (
            f"Run {run.run_id} Analysis ({len(discrepancies)} discrepancies detected via {len(self.analyzers)} analyzers). "
            f"Reproduced: {reproduced}."
        )

        return CorrelationResult(
            run_id=run.run_id,
            session_id=run.session_id,
            summary=summary,
            reproduced=reproduced,
            discrepancies=discrepancies,
            timeline=timeline,
            temporal_insights=temporal_insights,
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
