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
HIGH_VOL_MIN = 70   # entry gate tightens to this in HIGH VOLATILITY regime
#
def _is_high_vol(regime) -> bool:
    if not regime:
        return False
    r = str(regime).upper().replace("_", " ").replace("-", " ")
    r = " ".join(r.split())
    return r in ("HIGH VOLATILITY", "HIGH VOL", "HIGHVOL")
#
def entry_min(regime=None) -> int:
    """Entry threshold for the current regime: HIGH_VOL_MIN in high-vol, else HIGH_MIN."""
    return HIGH_VOL_MIN if _is_high_vol(regime) else HIGH_MIN
#
def is_entry(adj, regime=None) -> bool:
    """Portfolio entry gate: rounded conviction >= entry_min(regime).
    Regime tightens ONLY the buy gate; the label and exit stay flat."""
    try:
        return _r(adj) >= entry_min(regime)
    except (TypeError, ValueError):
        return False
#
def is_exit(adj) -> bool:
    """Portfolio exit trigger: rounded conviction <= LOW_MAX."""
    try:
        return _r(adj) <= LOW_MAX
    except (TypeError, ValueError):
        return False
#
# Value-trap guard: decline ENTRY when value >= 85 AND sentiment <= 30 — the
# classic value-trap signature (cheap, but the market is actively rejecting it).
# Portfolio construction only; the conviction label/screener still show the true
# score. Thresholds tunable.
VALUE_TRAP_VALUE_MIN = 85
VALUE_TRAP_SENT_MAX  = 30


def is_value_trap(value, sentiment) -> bool:
    """True if this name looks like a value trap and should be declined for entry."""
    try:
        return float(value) >= VALUE_TRAP_VALUE_MIN and float(sentiment) <= VALUE_TRAP_SENT_MAX
    except (TypeError, ValueError):
        return False


def conviction_action(adj) -> str:
    """BUY (entry) / SELL (exit) / HOLD, from the same rounded bands."""
    if is_entry(adj):
        return "BUY"
    if is_exit(adj):
        return "SELL"
    return "HOLD"
#
def conviction_short(adj) -> str:
    """HIGH / MOD / LOW short form."""
    lab = conviction_label(adj)
    return "MOD" if lab == "MODERATE" else lab
#
def conviction_color(adj, hi, mid, lo) -> str:
    """Pick hi/mid/lo by conviction bucket (HIGH/MODERATE/LOW)."""
    lab = conviction_label(adj)
    if lab == "HIGH":
        return hi
    if lab == "LOW":
        return lo
    return mid
