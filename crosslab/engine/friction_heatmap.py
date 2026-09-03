"""
Friction study heatmap aggregation for harness × taxonomy matrix.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional


HARNESS_ORDER = ("fear3-debug", "antigravity", "codex", "opencode", "cursor", "other")
TAXONOMY_ORDER = (
    "T-TRANSPORT",
    "T-SYNC",
    "T-MCP",
    "T-AGENT-ATTN",
    "T-CONTEXT",
    "T-HUMAN",
    "T-OBS",
    "T-TOPOLOGY",
    "T-REPO",
)


def default_friction_csv_path() -> Path:
    """Resolve bundled friction-events.csv relative to repo root."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "docs" / "friction-events.csv"
        if candidate.exists():
            return candidate
    return Path("docs/friction-events.csv")


def parse_harness(source: str) -> str:
    lower = source.lower()
    if "fear3-debug" in lower or "fear3_debug" in lower:
        return "fear3-debug"
    if "antigravity" in lower:
        return "antigravity"
    if "codex" in lower:
        return "codex"
    if "opencode" in lower:
        return "opencode"
    if "cursor" in lower:
        return "cursor"
    return "other"


def parse_taxonomies(taxonomy: str) -> List[str]:
    return [t.strip() for t in taxonomy.split("|") if t.strip()]


def load_friction_events(csv_path: Optional[Path] = None) -> List[Dict[str, str]]:
    path = csv_path or default_friction_csv_path()
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_heatmap_matrix(rows: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    if rows is None:
        rows = load_friction_events()

    counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    cells: Dict[str, Dict[str, List[Dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
    harnesses_seen: set[str] = set()
    taxonomies_seen: set[str] = set()

    for row in rows:
        harness = parse_harness(row.get("source", ""))
        harnesses_seen.add(harness)
        for tax in parse_taxonomies(row.get("taxonomy", "")):
            taxonomies_seen.add(tax)
            counts[tax][harness] += 1
            cells[tax][harness].append({
                "id": row.get("id", ""),
                "status": row.get("status", ""),
                "severity": row.get("severity", ""),
            })

    taxonomies = [t for t in TAXONOMY_ORDER if t in taxonomies_seen]
    taxonomies.extend(sorted(taxonomies_seen - set(taxonomies)))

    harnesses = [h for h in HARNESS_ORDER if h in harnesses_seen]
    harnesses.extend(sorted(harnesses_seen - set(harnesses)))

    matrix: List[List[int]] = []
    for tax in taxonomies:
        matrix.append([counts[tax].get(h, 0) for h in harnesses])

    status_totals: Dict[str, int] = defaultdict(int)
    for row in rows:
        status_totals[row.get("status", "unknown")] += 1

    return {
        "taxonomies": taxonomies,
        "harnesses": harnesses,
        "counts": {t: dict(counts[t]) for t in taxonomies},
        "matrix": matrix,
        "cells": {t: dict(cells[t]) for t in taxonomies},
        "total_events": len(rows),
        "status_totals": dict(status_totals),
        "csv_path": str(default_friction_csv_path()),
    }
