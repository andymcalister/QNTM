"""QNTM conviction - single source of truth for thresholds & labels.
Scores are ROUNDED to the nearest integer before bucketing, so label / entry /
exit always agree with the rounded score shown in the UI.

Change 2026-07-16 (forward-only):
    HIGH     rounded >= 65   -- entry gate           (was 60)
    MODERATE rounded 56..64  -- held                 (was 45-59)
    LOW      rounded <= 55   -- exit trigger          (was < 45)
"""
from __future__ import annotations
#
HIGH_MIN = 65   # rounded adj_composite >= HIGH_MIN -> HIGH / entry
LOW_MAX  = 55   # rounded adj_composite <= LOW_MAX   -> LOW / exit
#
def _r(adj):
    return round(float(adj))
#
def conviction_label(adj) -> str:
    """Canonical HIGH / MODERATE / LOW from the ROUNDED adj_composite."""
    try:
        r = _r(adj)
    except (TypeError, ValueError):
        return "MODERATE"
    if r >= HIGH_MIN:
        return "HIGH"
    if r <= LOW_MAX:
        return "LOW"
    return "MODERATE"
#
def is_entry(adj) -> bool:
    """Portfolio entry gate: rounded conviction >= HIGH_MIN."""
    try:
        return _r(adj) >= HIGH_MIN
    except (TypeError, ValueError):
        return False
#
def is_exit(adj) -> bool:
    """Portfolio exit trigger: rounded conviction <= LOW_MAX."""
    try:
        return _r(adj) <= LOW_MAX
    except (TypeError, ValueError):
        return False
