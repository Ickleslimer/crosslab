"""
Tier A harness config probes for agent profile auto-detection.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from crosslab.engine.agent_profile import AgentProfile
from crosslab.engine.harness_probes.base import ProbeResult, normalize_harness_hint
from crosslab.engine.harness_probes.registry import HARNESS_PROBES, PROBE_ORDER


def probe_all(harness_hint: Optional[str] = None) -> List[ProbeResult]:
    hint = normalize_harness_hint(harness_hint)
    if hint:
        if hint not in HARNESS_PROBES:
            return []
        result = HARNESS_PROBES[hint]()
        return [result] if result else []

    results: List[ProbeResult] = []
    for name in PROBE_ORDER:
        probe_fn = HARNESS_PROBES[name]
        result = probe_fn()
        if result:
            results.append(result)
    return results


def detect_agent_profile(harness_hint: Optional[str] = None) -> Optional[AgentProfile]:
    """Return best probe result as AgentProfile, or None if ambiguous/unset."""
    candidates = probe_all(harness_hint=harness_hint)
    if not candidates:
        return None
    if harness_hint or len(candidates) == 1:
        return candidates[0].to_agent_profile()
    return None


def detect_summary(harness_hint: Optional[str] = None) -> Tuple[List[ProbeResult], Optional[AgentProfile]]:
    """Return all probe hits and the profile that would be selected."""
    candidates = probe_all(harness_hint=harness_hint)
    selected = detect_agent_profile(harness_hint=harness_hint)
    return candidates, selected


__all__ = [
    "ProbeResult",
    "detect_agent_profile",
    "detect_summary",
    "probe_all",
]
