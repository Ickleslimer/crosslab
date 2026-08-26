"""
FEAR 3 Client Machine Diagnostic Harness & Simulation.
Instruments outgoing packet transmission, Steam P2P send status, and UI disconnect notifications.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class Fear3ClientHarness:
    """
    Simulates / instruments FEAR 3 Client game session.
    Tracks outgoing sends, transport layer return codes, and UI dialog messages.
    """

    def __init__(self):
        self.last_sent_packet: int = 8800
        self.transport_result: str = "success"
        self.displayed_reason: Optional[str] = None
        self.events: List[Dict[str, Any]] = []
        self.instrumentation_enabled: bool = False

    def enable_instrumentation(self, probe_name: str = "send_path_trace") -> None:
        self.instrumentation_enabled = True
        self._log_event(f"Instrumentation probe '{probe_name}' attached to SteamNetworkingSockets sender.")

    def _log_event(self, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        event = {
            "timestamp": timestamp,
            "source": "client",
            "message": message,
        }
        if extra:
            event.update(extra)
        self.events.append(event)

    def run_session_simulation(self, total_packets_to_send: int = 35) -> Dict[str, Any]:
        """
        Executes a simulated gameplay interval for the client.
        Sends packets 8801 through 8835. All return k_EResultOK at the transport layer,
        even as the host stops receiving after 8831.
        """
        self.events.clear()
        self.last_sent_packet = 8800

        self._log_event("Client session connected to Host Steam P2P session.")

        for i in range(1, total_packets_to_send + 1):
            pkt_id = 8800 + i
            self.last_sent_packet = pkt_id
            # Steam SendP2PPacket returns true / k_EResultOK
            self.transport_result = "success"

            if self.instrumentation_enabled and (pkt_id > 8830 or pkt_id % 10 == 0):
                self._log_event(
                    f"SendP2PPacket(pkt #{pkt_id}) returned k_EResultOK (transport=success).",
                    {"packet_id": pkt_id, "transport_result": "success"},
                )

        self._log_event(f"Client transmission ongoing. Packets 8832-8835 dispatched during host silence window.")

        # Client receives connection tear-down packet from Host
        self.displayed_reason = "kicked_by_host"
        self._log_event(
            "Host closed session socket. Game UI displayed modal dialog: 'Kicked by the host / connection lost'.",
            {"displayed_reason": "kicked_by_host"},
        )

        return self.get_telemetry()

    def get_telemetry(self) -> Dict[str, Any]:
        return {
            "last_sent_packet": self.last_sent_packet,
            "transport_result": self.transport_result,
            "displayed_reason": self.displayed_reason or "kicked_by_host",
            "instrumented": self.instrumentation_enabled,
            "events": self.events,
        }
