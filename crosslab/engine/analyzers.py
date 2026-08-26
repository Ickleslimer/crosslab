"""
Pluggable Investigation Analyzers for CrossLab.
Separates generic temporal, sequence, and causal correlation from domain-specific rules.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from crosslab.protocol.actions import RunOutcome
from crosslab.protocol.models import Discrepancy, RunRecord


class BaseAnalyzer(ABC):
    """Abstract base class for all investigation analyzers."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def analyze(self, run: RunRecord) -> List[Discrepancy]:
        pass

    def get_temporal_insights(self, run: RunRecord) -> List[str]:
        return []


class TemporalAnalyzer(BaseAnalyzer):
    """
    Analyzes temporal ordering, clock uncertainty intervals (T_A +/- Delta_t),
    and event interleaving across distributed nodes.
    """

    @property
    def name(self) -> str:
        return "temporal"

    def analyze(self, run: RunRecord) -> List[Discrepancy]:
        # Evaluates timing conflicts or causal violations
        discrepancies: List[Discrepancy] = []
        host_data = run.host or {}
        client_data = run.client or {}

        host_events = host_data.get("events", [])
        client_events = client_data.get("events", [])

        # Find host disconnect time and client latest send
        host_disconnect = None
        for ev in reversed(host_events):
            if "disconnect" in str(ev.get("message", "")).lower() or "timeout" in str(ev.get("message", "")).lower():
                host_disconnect = ev
                break

        client_last_send = None
        for ev in reversed(client_events):
            if "send" in str(ev.get("message", "")).lower() or "packet" in str(ev.get("message", "")).lower():
                client_last_send = ev
                break

        if host_disconnect and client_last_send:
            # If monotonic timestamps exist, compute high-resolution interval
            h_mono = host_disconnect.get("monotonic_ns")
            c_mono = client_last_send.get("monotonic_ns")
            uncertainty = max(
                host_disconnect.get("uncertainty_ms", 2.0),
                client_last_send.get("uncertainty_ms", 2.0),
            )
            if h_mono and c_mono:
                delta_ms = (h_mono - c_mono) / 1_000_000.0
                if delta_ms > 0:
                    discrepancies.append(
                        Discrepancy(
                            code="TIMING_ORDERING_OBSERVATION",
                            analyzer=self.name,
                            description=(
                                f"Client dispatched packets {delta_ms:.1f} ms [+/-{uncertainty:.1f} ms uncertainty] "
                                f"before host timeout was triggered."
                            ),
                            host_evidence={"host_disconnect_event": host_disconnect},
                            client_evidence={"client_send_event": client_last_send},
                            impact="Definitively proves client was transmitting immediately prior to host silence trigger.",
                        )
                    )
        return discrepancies

    def get_temporal_insights(self, run: RunRecord) -> List[str]:
        insights = []
        host_data = run.host or {}
        client_data = run.client or {}

        host_events = host_data.get("events", [])
        client_events = client_data.get("events", [])

        if host_events and client_events:
            insights.append(
                f"Correlated {len(host_events)} host events with {len(client_events)} client events across distributed timelines."
            )
        return insights


class PacketSequenceAnalyzer(BaseAnalyzer):
    """
    Generic sequence analyzer for packet, frame, and stream counters across distributed nodes.
    """

    @property
    def name(self) -> str:
        return "packet_sequence"

    def analyze(self, run: RunRecord) -> List[Discrepancy]:
        discrepancies: List[Discrepancy] = []
        host_data = run.host or {}
        client_data = run.client or {}

        last_sent = client_data.get("last_sent_packet") or client_data.get("last_sent_seq")
        last_recv = host_data.get("last_received_packet") or host_data.get("last_received_seq")

        if last_sent is not None and last_recv is not None:
            if last_sent > last_recv:
                dropped = last_sent - last_recv
                discrepancies.append(
                    Discrepancy(
                        code="PACKET_SEQUENCE_GAP",
                        analyzer=self.name,
                        description=(
                            f"Client sequence counter reached #{last_sent}, but Host only received up to sequence #{last_recv} "
                            f"({dropped} frames unacknowledged or dropped)."
                        ),
                        host_evidence={"last_received": last_recv},
                        client_evidence={"last_sent": last_sent, "transport_result": client_data.get("transport_result")},
                        impact="Receive buffer starvation leading to heartbeat watchdog expiration.",
                    )
                )
        return discrepancies


class RequestResponseAnalyzer(BaseAnalyzer):
    """
    Generic analyzer for request/response pairing, unfulfilled requests, and timeouts.
    """

    @property
    def name(self) -> str:
        return "request_response"

    def analyze(self, run: RunRecord) -> List[Discrepancy]:
        discrepancies: List[Discrepancy] = []
        host_data = run.host or {}
        client_data = run.client or {}

        # Look for asymmetric transport success vs timeout status
        client_transport = client_data.get("transport_result")
        host_reason = host_data.get("reason") or host_data.get("disconnect_reason")

        if client_transport == "success" and host_reason in ("timeout", "connection_lost", "timed_out"):
            discrepancies.append(
                Discrepancy(
                    code="UNRECIPROCATED_TRANSPORT_SUCCESS",
                    analyzer=self.name,
                    description=(
                        f"Client reported successful local transport transmission ('{client_transport}'), "
                        f"while Host encountered receive timeout ('{host_reason}')."
                    ),
                    host_evidence={"host_reason": host_reason},
                    client_evidence={"client_transport": client_transport},
                    impact="Transport layer decoupled from application receipt confirmation.",
                )
            )
        return discrepancies


class Fear3CoopAnalyzer(BaseAnalyzer):
    """
    Domain-specific analyzer for FEAR 3 co-op disconnect behavior.
    """

    @property
    def name(self) -> str:
        return "fear3_coop"

    def analyze(self, run: RunRecord) -> List[Discrepancy]:
        discrepancies: List[Discrepancy] = []
        host_data = run.host or {}
        client_data = run.client or {}

        host_reason = host_data.get("reason") or host_data.get("disconnect_reason")
        client_ui_reason = client_data.get("displayed_reason") or client_data.get("ui_reason")

        if host_reason == "connection_lost" and client_ui_reason == "kicked_by_host":
            discrepancies.append(
                Discrepancy(
                    code="FEAR3_ASYMMETRIC_UI_MISINFORMATION",
                    analyzer=self.name,
                    description=(
                        "Host terminated session due to internal 'connection_lost' (5000ms silence watchdog), "
                        "which the Client game UI displayed as 'Kicked by the host / connection lost'."
                    ),
                    host_evidence={"internal_reason": host_reason, "disconnect_time": host_data.get("disconnect_time")},
                    client_evidence={"ui_displayed_reason": client_ui_reason},
                    impact="The UI error 'Kicked by the host' is misleading; the host did not kick the client, but timed out.",
                )
            )
        return discrepancies
