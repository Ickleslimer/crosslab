"""
Protocol action types and constants for CrossLab A2A communication.
"""

from enum import Enum


class ActionType(str, Enum):
    # Discovery & Session Management
    HANDSHAKE = "handshake"
    HANDSHAKE_ACK = "handshake_ack"
    PING = "ping"
    PONG = "pong"
    SYNC_STATE = "sync_state"

    # Conversational & Reasoning
    CHAT = "chat"

    # Hypotheses & Evidence Graph
    PROPOSE_HYPOTHESIS = "propose_hypothesis"
    CHALLENGE_HYPOTHESIS = "challenge_hypothesis"
    UPDATE_HYPOTHESIS = "update_hypothesis"
    ASSESS_HYPOTHESIS = "assess_hypothesis"
    ADD_EVIDENCE = "add_evidence"
    RESOLVE_HYPOTHESIS = "resolve_hypothesis"

    # Experiments
    PROPOSE_EXPERIMENT = "propose_experiment"
    ACCEPT_EXPERIMENT = "accept_experiment"
    REJECT_EXPERIMENT = "reject_experiment"
    MODIFY_EXPERIMENT = "modify_experiment"

    # Run Coordination (Synchronized Execution)
    START_RUN = "start_run"
    SYNC_READY = "sync_ready"
    RUN_IN_PROGRESS = "run_in_progress"
    END_RUN = "end_run"
    ABORT_RUN = "abort_run"

    # Observations & Telemetry
    REPORT_OBSERVATION = "report_observation"
    REQUEST_OBSERVATION = "request_observation"

    # Instrumentation
    REQUEST_INSTRUMENTATION = "request_instrumentation"
    # Payload: {"run_id": N, "pid": N, "process_start_time": epoch_seconds, "probe_hash": "..."}
    # Only the attaching agent should emit this action (not a peer describing another machine's PID).
    REPORT_INSTRUMENTATION_READY = "report_instrumentation_ready"

    # Artifacts & Code
    SHARE_LOG = "share_log"
    SHARE_FILE = "share_file"
    SHARE_PATCH = "share_patch"

    # Human operator coordination
    HUMAN_REPRO_REQUEST = "human_repro_request"
    HUMAN_SIGNAL = "human_signal"

    # Results & Failures
    REPORT_RESULT = "report_result"
    REPORT_FAILURE = "report_failure"
    CORRELATION_ANALYSIS = "correlation_analysis"


class EvidenceType(str, Enum):
    RUN = "run"
    OBSERVATION = "observation"
    LOG = "log"
    COUNTER_HYPOTHESIS = "counter_hypothesis"
    EXPERIMENT = "experiment"


class EvidenceRelation(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    QUALIFIES = "qualifies"
    INCONCLUSIVE = "inconclusive"


class HypothesisStatus(str, Enum):
    PROPOSED = "proposed"
    UNDER_TEST = "under_test"
    ACTIVE = "active"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INCONCLUSIVE = "inconclusive"
    RESOLVED = "resolved"
    ABANDONED = "abandoned"


class ExperimentStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class RunOutcome(str, Enum):
    PENDING = "pending"
    REPRODUCED = "reproduced"
    NOT_REPRODUCED = "not_reproduced"
    INCONCLUSIVE = "inconclusive"
    CRASH = "crash"
    TIMEOUT = "timeout"
    SUCCESS = "success"


class AgentRole(str, Enum):
    HOST = "host"
    CLIENT = "client"
    OBSERVER = "observer"
    COORDINATOR = "coordinator"
