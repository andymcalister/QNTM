"""
QNTM API — data access.

This is the only place the API touches Supabase. It deliberately REUSES the
existing engine rather than reimplementing scoring:

  * universe_data.SECTORS         → sector for each ticker (signal_log does NOT
                                    store sector; it's attached at read time,
                                    exactly as the Streamlit app and the macro
                                    pass do)
  * model_engine.ENTRY_THRESHOLD  → conviction tier boundaries (60 / 45), so the
    model_engine.EXIT_THRESHOLD     API's HIGH/MODERATE/LOW labels are identical
                                    to what the app shows
  * data_refresh._load_macro_state→ the canonical macro/regime read (same source
                                    the app banner and the marketing hero use)

The scored universe is small (~1,400 rows) and already precomputed by the crons,
so we load the whole latest-dated set once, cache it in-process for a short TTL,
and do filter/sort/paginate per request in Python. That sidesteps the fact that
`sector` lives in the code, not the DB, and keeps Supabase reads to ~1 per TTL
window regardless of traffic.
"""

from __future__ import annotations

import sys
import os
import time
import logging
from typing import Optional

# Ensure the repo root is importable so universe_data / model_engine /
# data_refresh resolve when this runs as `uvicorn api.main:app` from the root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .config import settings  # noqa: E402

log = logging.getLogger("qntm.api.data")

# ── Conviction tiers — single source of truth from the engine ─────────────────
try:
    from model_engine import ENTRY_THRESHOLD, EXIT_THRESHOLD  # 60, 45
except Exception:  # pragma: no cover - defensive if import path differs
    ENTRY_THRESHOLD, EXIT_THRESHOLD = 60, 45

try:
    from universe_data import SECTORS as _SECTORS
except Exception:  # pragma: no cover
    _SECTORS = {}


def conviction_label(adj: float) -> str:
    """HIGH / MODERATE / LOW — matches apply_macro_overlay's published bands."""
    if adj >= ENTRY_THRESHOLD:
        return "HIGH"
    if adj >= EXIT_THRESHOLD:
        return "MODERATE"
    return "LOW"


# ── Supabase client (anon, read-only) ─────────────────────────────────────────
_SB = None


def _get_supabase():
    global _SB
    if _SB is not None:
        return _SB
    if not settings.SUPABASE_URL or not settings.SUPABASE_ANON_KEY:
        log.error("Supabase creds missing — set SUPABASE_URL and SUPABASE_ANON_KEY")
        return None
    try:
        from supabase import create_client
        _SB = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
        return _SB
    except Exception as e:  # pragma: no cover
        log.error("Supabase client init failed: %s", e)
        return None


# ── Raw reads ─────────────────────────────────────────────────────────────────
_SCREENER_COLS = (
    "ticker,composite,adj_composite,momentum,quality,volume,value,sentiment,"
    "macro_overlay,price,is_hidden_gem,value_position,signal_date,"
    "mktcap,val_low,val_high,val_basis"
)


def _fetch_latest_scores() -> tuple[list[dict], Optional[str]]:
    """Return (rows, as_of_date) for the most recent scored signal_date.

    Only rows with a real (non-null) composite are returned — a null composite
    means the nightly rescore hasn't populated that row, and we never surface a
    fabricated score (same guard the macro pass uses)."""
    sb = _get_supabase()
    if not sb:
        return [], None

    # 1) newest scored date
    latest = (
        sb.table("signal_log")
        .select("signal_date")
        .order("signal_date", desc=True)
        .limit(1)
        .execute()
    )
    if not latest.data:
        return [], None
    as_of = latest.data[0]["signal_date"]

    # 2) all scored rows for that date (paginated; ~1,400 rows)
    rows: list[dict] = []
    PAGE = 1000
    page = 0
    while page < 6:  # safety cap
        resp = (
            sb.table("signal_log")
            .select(_SCREENER_COLS)
            .eq("signal_date", as_of)
            .not_.is_("composite", "null")
            .order("adj_composite", desc=True)
            .range(page * PAGE, (page + 1) * PAGE - 1)
            .execute()
        )
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < PAGE:
            break
        page += 1
    return rows, as_of


def _fetch_regime() -> dict:
    """Canonical macro/regime read, reusing the engine's own loader so the API,
    the app banner, and the marketing hero never disagree."""
    try:
        from data_refresh import _load_macro_state
        macro = _load_macro_state() or {}
    except Exception as e:
        log.warning("macro_state read failed: %s", e)
        macro = {}
    events = macro.get("event_labels") or []
    return {
        "label": macro.get("regime") or "NEUTRAL",
        "vix": macro.get("vix"),
        "event": events[0] if events else None,
        "summary": macro.get("summary"),
    }


def _enrich(r: dict) -> dict:
    """Attach sector + conviction tier and coerce numeric types for the API
    contract. signal_log values can arrive as strings via PostgREST."""
    def f(key, default=None):
        v = r.get(key)
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    adj = f("adj_composite") or f("composite") or 0.0
    tier = conviction_label(adj)
    # action maps 1:1 to the conviction tier (same ENTRY/EXIT thresholds the
    # model uses), so derive it here rather than depend on a stored column.
    _action = {"HIGH": "BUY", "MODERATE": "HOLD", "LOW": "SELL"}[tier]
    _cap = str(r.get("mktcap") or "").strip().lower() or None
    return {
        "ticker": r["ticker"],
        "sector": _SECTORS.get(r["ticker"], "Unknown"),
        "conviction": tier,
        "action": _action,
        "score": round(adj, 1),
        "composite": round(f("composite") or 0.0, 1),
        "momentum": round(f("momentum") or 0.0, 1),
        "quality": round(f("quality") or 0.0, 1),
        "volume": round(f("volume") or 0.0, 1),
        "value": round(f("value") or 0.0, 1),
        "sentiment": round(f("sentiment") or 0.0, 1),
        "macro_overlay": f("macro_overlay"),
        "price": f("price"),
        "value_position": f("value_position"),
        "is_hidden_gem": bool(r.get("is_hidden_gem")),
        # ── card fields ──
        "mktcap": _cap if _cap in ("large", "mid", "small") else None,
        "val_low": f("val_low"),
        "val_high": f("val_high"),
        "val_basis": (r.get("val_basis") or None),
        "signal_date": r.get("signal_date"),
    }


# ── TTL-cached universe load ───────────────────────────────────────────────────
_CACHE: dict = {"ts": 0.0, "payload": None}
_MACRO_CACHE: dict = {"ts": 0.0, "payload": None}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_macro_detail() -> dict:
    """Full macro overlay for the regime banner — regime, indicators, the
    'what's moving the regime' driver breakdown, and per-event headlines.

    Passes through the same persisted overlay the Streamlit banner reads
    (_load_macro_state), so the banner, screener, and marketing hero never
    disagree. Cached for CACHE_TTL_SECONDS (the overlay only changes on the
    ~30-min macro cron)."""
    now = time.time()
    cached = _MACRO_CACHE["payload"]
    if cached is not None and (now - _MACRO_CACHE["ts"]) < settings.CACHE_TTL_SECONDS:
        return cached
    try:
        from data_refresh import _load_macro_state
        m = _load_macro_state() or {}
    except Exception as e:
        log.warning("macro detail read failed: %s", e)
        m = {}

    drivers = []
    for d in (m.get("drivers") or [])[:8]:
        drivers.append({
            "label": str(d.get("label", "")),
            "contribution": _num(d.get("contribution")) or 0.0,
            "signals": int(d.get("signals") or 0),
            "event": d.get("event"),
        })

    payload = {
        "regime": m.get("regime") or "NEUTRAL",
        "vix": _num(m.get("vix")),
        "oil_price": _num(m.get("oil_price")),
        "active_events": list(m.get("active_events") or []),
        "source": m.get("source"),
        "live": bool(m.get("live")),
        "headlines_scanned": int(m.get("headlines_scanned") or 0),
        "narrative": m.get("narrative"),
        "summary": m.get("summary"),
        "regime_score": _num(m.get("regime_score")),
        "drivers": drivers,
        "event_headlines": {k: list(v)[:3] for k, v in (m.get("event_headlines") or {}).items()},
    }
    _MACRO_CACHE.update(ts=now, payload=payload)
    return payload


def load_universe() -> tuple[list[dict], dict, Optional[str]]:
    """Return (enriched_rows, regime, as_of). Cached for CACHE_TTL_SECONDS.

    On a read failure we serve the last good cache if we have one (graceful
    degradation, same philosophy as the marketing hero's fallback); only if we
    have nothing cached do we return an empty set with a neutral regime."""
    now = time.time()
    cached = _CACHE["payload"]
    if cached is not None and (now - _CACHE["ts"]) < settings.CACHE_TTL_SECONDS:
        return cached

    try:
        raw, as_of = _fetch_latest_scores()
        regime = _fetch_regime()
        rows = [_enrich(r) for r in raw]
        payload = (rows, regime, as_of)
        _CACHE.update(ts=now, payload=payload)
        return payload
    except Exception as e:
        log.error("load_universe failed: %s", e)
        if cached is not None:
            return cached
        return ([], {"label": "NEUTRAL", "vix": None, "event": None, "summary": None}, None)
