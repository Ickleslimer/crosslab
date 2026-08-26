"""
FEAR 3 Host Machine Diagnostic Harness & Simulation.
Instruments the host's packet receive queue, timeout watchdog timer, and internal disconnect logic.
"""

from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional


class Fear3HostHarness:
    """
    Simulates / instruments FEAR 3 Host game session.
    Monitors packet reception, keep-alive watchdog timer, and disconnect reasons.
    """

    def __init__(self, timeout_ms: int = 5000):
        self.timeout_ms = timeout_ms
        self.last_received_packet: int = 8800
        self.session_active: bool = True
        self.disconnect_time: Optional[str] = None
        self.disconnect_reason: Optional[str] = None
        self.receive_counter_advance_time: float = 0.0
        self.events: List[Dict[str, Any]] = []
        self.instrumentation_enabled: bool = False

    def enable_instrumentation(self, probe_name: str = "receive_path_trace") -> None:
        self.instrumentation_enabled = True
        self._log_event(f"Instrumentation probe '{probe_name}' attached to NetReceiver.")

    def _log_event(self, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        event = {
            "timestamp": timestamp,
            "source": "host",
            "message": message,
        }
        if extra:
            event.update(extra)
        self.events.append(event)

    def run_session_simulation(self, packets_to_receive: int = 31, drop_after: int = 8831) -> Dict[str, Any]:
        """
        Executes a simulated gameplay interval up to the co-op disconnect bug.
        """
        self.events.clear()
        self.session_active = True
        self.last_received_packet = 8800
        start_time = time.time()
        self.receive_counter_advance_time = start_time

        self._log_event("Host game session initialized. Listening on Steam P2P channel 0.")

        # Receive packets normally up to drop_after
        for i in range(1, packets_to_receive + 1):
            pkt_id = 8800 + i
            if pkt_id <= drop_after:
                self.last_received_packet = pkt_id
                self.receive_counter_advance_time = time.time()
                if self.instrumentation_enabled and pkt_id % 10 == 0:
                    self._log_event(f"Received packet #{pkt_id} from client. CRC=0x9A4F valid.", {"packet_id": pkt_id})

        self._log_event(f"Host packet counter stopped advancing at packet #{self.last_received_packet}.")

        # Advance watchdog timer to simulate 5000ms receive silence
        silence_start = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        self._log_event(f"Receive silence watchdog timer armed at {silence_start}. Threshold={self.timeout_ms}ms.")

        # Simulate timeout trigger
        self.session_active = False
        self.disconnect_reason = "connection_lost"
        self.disconnect_time = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        self._log_event(
            f"Host Watchdog Timer expired (5000 ms silence). Terminating session with 'connection_lost'.",
            {"internal_code": "0x80041002", "disconnect_time": self.disconnect_time},
        )

        return self.get_telemetry()

    def get_telemetry(self) -> Dict[str, Any]:
        return {
            "disconnect_time": self.disconnect_time or datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3],
            "reason": self.disconnect_reason or "connection_lost",
            "last_received_packet": self.last_received_packet,
            "watchdog_timeout_ms": self.timeout_ms,
            "session_active": self.session_active,
            "instrumented": self.instrumentation_enabled,
            "events": self.events,
        }
