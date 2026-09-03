"""
Harness probe registry and dispatch.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from crosslab.engine.harness_probes.base import ProbeResult
from crosslab.engine.harness_probes.codex import probe_codex
from crosslab.engine.harness_probes.cursor_cli import probe_cursor_cli
from crosslab.engine.harness_probes.cursor_ide import cursor_ide_enabled, probe_cursor_ide
from crosslab.engine.harness_probes.opencode import probe_opencode

ProbeFn = Callable[[], Optional[ProbeResult]]


def probe_cursor() -> Optional[ProbeResult]:
    result = probe_cursor_cli()
    if result:
        return result
    if cursor_ide_enabled():
        return probe_cursor_ide()
    return None


HARNESS_PROBES: Dict[str, ProbeFn] = {
    "codex": probe_codex,
    "opencode": probe_opencode,
    "cursor": probe_cursor,
}

PROBE_ORDER = ("codex", "opencode", "cursor")
