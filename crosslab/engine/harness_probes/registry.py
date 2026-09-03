"""
Harness probe registry and dispatch.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from crosslab.engine.harness_probes.base import ProbeResult
from crosslab.engine.harness_probes.codex import probe_codex
from crosslab.engine.harness_probes.cursor_cli import probe_cursor_cli
from crosslab.engine.harness_probes.opencode import probe_opencode

ProbeFn = Callable[[], Optional[ProbeResult]]

HARNESS_PROBES: Dict[str, ProbeFn] = {
    "codex": probe_codex,
    "opencode": probe_opencode,
    "cursor": probe_cursor_cli,
}

PROBE_ORDER = ("codex", "opencode", "cursor")
