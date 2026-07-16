"""QNTM conviction - single source of truth for thresholds & labels.
Import this everywhere instead of hardcoding cutoffs, so a change lands in ONE
place and labels / entry / exit / alerts / validation can never disagree.

Threshold change 2026-07-16 (forward-only):
    HIGH     >= 65     (was 60)   -- portfolio entry gate
    MODERATE 55..64    (was 45-59) -- held
    LOW      <  55     (was 45)   -- portfolio EXIT trigger
"""
from __future__ import annotations
#
HIGH_MIN = 65
MODERATE_MIN = 55  # below MODERATE_MIN == LOW == exit trigger
#
def conviction_label(adj) -> str:
    """Canonical HIGH / MODERATE / LOW label from adj_composite."""
    try:
        a = float(adj)
    except (TypeError, ValueError):
        return "MODERATE"
    if a >= HIGH_MIN:
        return "HIGH"
    if a >= MODERATE_MIN:
        return "MODERATE"
    return "LOW"
#
def is_entry(adj) -> bool:
    """Portfolio entry gate: HIGH conviction (>= HIGH_MIN)."""
    try:
        return float(adj) >= HIGH_MIN
    except (TypeError, ValueError):
        return False
#
def is_exit(adj) -> bool:
    """Portfolio exit trigger: conviction dropped to LOW (< MODERATE_MIN)."""
    try:
        return float(adj) < MODERATE_MIN
    except (TypeError, ValueError):
        return False
