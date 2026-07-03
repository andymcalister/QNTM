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
import json
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


# ── Conviction movers (day-over-day) ──────────────────────────────────────────
_MOVERS_CACHE: dict = {"ts": 0.0, "payload": None}
_PILL = ("momentum", "quality", "volume", "value", "sentiment")
_PLAB = {"momentum": "Momentum", "quality": "Quality", "volume": "Volume",
         "value": "Value", "sentiment": "Sentiment"}


def compute_movers(lookback_days: int = 10, top_n: int = 24,
                   compare_days: int = 1, collapse_macro: bool = True) -> list:
    """Day-over-day conviction movers for the hero feed — ported from the app's
    _conviction_movers. Compares each ticker's latest CLEAN scored row against
    the most recent clean row at least `compare_days` older, reports the
    adj_composite move and what drove it (biggest-moving pillar, or the macro
    overlay on regime days). Macro-driven names collapse into one summary chip so
    they don't flood the feed. Cached for CACHE_TTL_SECONDS; one batched read."""
    now_t = time.time()
    cached = _MOVERS_CACHE["payload"]
    if cached is not None and (now_t - _MOVERS_CACHE["ts"]) < settings.CACHE_TTL_SECONDS:
        return cached

    from datetime import date, timedelta

    sb = _get_supabase()
    if not sb:
        return []
    since = (date.today() - timedelta(days=lookback_days)).isoformat()

    rows: list[dict] = []
    PAGE, page = 1000, 0
    try:
        while page < 25:
            resp = (
                sb.table("signal_log")
                .select("ticker,signal_date,adj_composite,composite,"
                        "momentum,quality,volume,value,sentiment")
                .gte("signal_date", since)
                .not_.is_("composite", "null")
                .order("signal_date", desc=True)
                .range(page * PAGE, (page + 1) * PAGE - 1)
                .execute()
            )
            batch = resp.data or []
            rows.extend(batch)
            if len(batch) < PAGE:
                break
            page += 1
    except Exception as e:
        log.warning("movers read failed: %s", e)
        return []

    from datetime import date as _date

    def _pd(s):
        try:
            return _date.fromisoformat(s)
        except (TypeError, ValueError):
            return None

    by: dict = {}
    for r in rows:                       # already date-desc
        by.setdefault(r["ticker"], []).append(r)

    def _tier(v):
        return "HIGH" if v >= 60 else ("MOD" if v >= 45 else "LOW")

    movers = []
    for tk, rs in by.items():
        distinct, seen = [], set()
        for r in rs:
            d = r.get("signal_date")
            if d and d not in seen:
                seen.add(d); distinct.append(r)
        if len(distinct) < 2:
            continue
        now = distinct[0]
        nd = _pd(now.get("signal_date"))
        prev = None
        if nd:
            for r in distinct[1:]:
                rd = _pd(r.get("signal_date"))
                if rd and (nd - rd).days >= compare_days:
                    prev = r
                    break
        if prev is None:
            prev = distinct[-1]
        if prev.get("signal_date") == now.get("signal_date"):
            continue
        a_now, a_prev = _num(now.get("adj_composite")), _num(prev.get("adj_composite"))
        if a_now is None or a_prev is None:
            continue
        delta = round(a_now - a_prev, 1)
        if abs(round(delta)) < 1:
            continue
        c_now, c_prev = _num(now.get("composite")), _num(prev.get("composite"))
        comp_delta = (c_now - c_prev) if (c_now is not None and c_prev is not None) else 0.0
        macro_contrib = delta - comp_delta
        drv_p, drv_pd = None, 0.0
        for p in _PILL:
            pn, pp = _num(now.get(p)), _num(prev.get(p))
            if pn is None or pp is None:
                continue
            dd = pn - pp
            if abs(dd) > abs(drv_pd):
                drv_p, drv_pd = p, dd
        macro_only = abs(macro_contrib) >= 2 and abs(macro_contrib) > abs(comp_delta)
        if macro_only:
            driver, ddelta = "Macro overlay", round(macro_contrib, 1)
        elif drv_p and abs(drv_pd) >= 2:
            driver, ddelta = _PLAB[drv_p], round(drv_pd, 1)
        else:
            driver, ddelta = None, 0.0
        movers.append({
            "kind": "mover", "ticker": tk, "now": a_now, "prev": a_prev, "delta": delta,
            "quant_delta": round(comp_delta, 1), "macro_only": macro_only,
            "now_tier": _tier(a_now), "prev_tier": _tier(a_prev),
            "driver": driver, "driver_delta": ddelta,
        })

    quant = sorted([m for m in movers if not m["macro_only"]],
                   key=lambda m: abs(m["quant_delta"]), reverse=True)
    macro = sorted([m for m in movers if m["macro_only"]],
                   key=lambda m: abs(m["delta"]), reverse=True)
    if collapse_macro and len(macro) >= 3:
        ups = [m for m in macro if m["delta"] > 0]
        downs = [m for m in macro if m["delta"] < 0]
        grp = ups if len(ups) >= len(downs) else downs
        deltas = [m["delta"] for m in grp]
        out = quant[:top_n]
        out.append({"kind": "macro_summary", "count": len(grp),
                    "up": grp[0]["delta"] > 0, "lo": min(deltas), "hi": max(deltas)})
    else:
        out = (quant + macro)[:top_n]

    _MOVERS_CACHE.update(ts=now_t, payload=out)
    return out


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
        # The stored signal_log.is_hidden_gem is unreliable/empty, which made the
        # screener show 0 gems while the Gems page (live detection) found 12. Mark
        # gems here with the SAME detection so every consumer agrees.
        try:
            gem_list, _ = _compute_gems(rows, regime.get("label") or "NEUTRAL")
            gem_tickers = {g["ticker"] for g in gem_list}
            for r in rows:
                r["is_hidden_gem"] = r["ticker"] in gem_tickers
        except Exception as ge:
            log.warning("gem marking failed: %s", ge)
        payload = (rows, regime, as_of)
        _CACHE.update(ts=now, payload=payload)
        return payload
    except Exception as e:
        log.error("load_universe failed: %s", e)
        if cached is not None:
            return cached
        return ([], {"label": "NEUTRAL", "vix": None, "event": None, "summary": None}, None)


# ── Watchlist (authed read-write) ─────────────────────────────────────────────
# Writes use the service-role client (bypasses RLS); every function takes the
# user_id from the VERIFIED token at the call site (routers/watchlist.py), never
# from client input, so a user can only ever touch their own list.
_SB_ADMIN = None


def _get_supabase_admin():
    """Service-role Supabase client for per-user writes. None if no service key
    is configured (writes then no-op rather than silently hitting RLS)."""
    global _SB_ADMIN
    if _SB_ADMIN is not None:
        return _SB_ADMIN
    if not settings.SERVICE_KEY:
        log.warning("watchlist writes need a service key (SUPABASE_SERVICE_KEY) — none set")
        return None
    try:
        from supabase import create_client
        _SB_ADMIN = create_client(settings.SUPABASE_URL, settings.SERVICE_KEY)
        return _SB_ADMIN
    except Exception as e:
        log.warning("admin client init failed: %s", e)
        return None


def _resolve_default_list(sb, user_id: str):
    """Resolve (auto-creating if needed) the user's default watchlist id."""
    try:
        resp = (sb.table("watchlists").select("id,is_default")
                .eq("user_id", user_id)
                .order("is_default", desc=True).order("created_at", desc=False)
                .execute())
        lists = resp.data or []
        if lists:
            for w in lists:
                if w.get("is_default"):
                    return w["id"]
            return lists[0]["id"]
        created = (sb.table("watchlists")
                   .insert({"user_id": user_id, "name": "My Watchlist", "is_default": True})
                   .execute())
        return (created.data or [{}])[0].get("id")
    except Exception as e:
        log.warning("default-list resolve failed: %s", e)
        return None


def watchlist_items(user_id: str) -> list:
    """Raw items in the user's default list: [{ticker, price_at_add, added_at}]."""
    sb = _get_supabase_admin()
    if not sb:
        return []
    try:
        lid = _resolve_default_list(sb, user_id)
        if not lid:
            return []
        resp = (sb.table("watchlist_items").select("ticker,price_at_add,added_at")
                .eq("user_id", user_id).eq("watchlist_id", lid)
                .order("added_at", desc=True).execute())
        return resp.data or []
    except Exception as e:
        log.warning("watchlist read failed: %s", e)
        return []


def add_watchlist(user_id: str, ticker: str, price_at_add=None) -> bool:
    """Add a ticker to the user's default list (idempotent). Validates against
    the model universe first — refuses arbitrary strings."""
    tk = (ticker or "").strip().upper()
    if not tk or tk not in _SECTORS:
        return False
    sb = _get_supabase_admin()
    if not sb:
        return False
    try:
        lid = _resolve_default_list(sb, user_id)
        if not lid:
            return False
        payload = {"watchlist_id": lid, "user_id": user_id, "ticker": tk}
        if price_at_add:
            payload["price_at_add"] = round(float(price_at_add), 4)
        sb.table("watchlist_items").upsert(payload, on_conflict="watchlist_id,ticker").execute()
        return True
    except Exception as e:
        log.warning("watchlist add failed: %s", e)
        return False


def remove_watchlist(user_id: str, ticker: str) -> bool:
    tk = (ticker or "").strip().upper()
    if not tk:
        return False
    sb = _get_supabase_admin()
    if not sb:
        return False
    try:
        lid = _resolve_default_list(sb, user_id)
        if not lid:
            return False
        (sb.table("watchlist_items").delete()
         .eq("user_id", user_id).eq("watchlist_id", lid).eq("ticker", tk)
         .execute())
        return True
    except Exception as e:
        log.warning("watchlist remove failed: %s", e)
        return False


def _row_stub(tk: str) -> dict:
    """Minimal screener-row-shaped stub for a watched ticker that isn't in the
    latest scored set (so the card still renders)."""
    return {
        "ticker": tk, "sector": _SECTORS.get(tk, "Unknown"), "conviction": "LOW",
        "action": "SELL", "score": 0.0, "composite": 0.0, "momentum": 0.0,
        "quality": 0.0, "volume": 0.0, "value": 0.0, "sentiment": 0.0,
        "macro_overlay": None, "price": None, "value_position": None,
        "is_hidden_gem": False, "mktcap": None, "val_low": None, "val_high": None,
        "val_basis": None, "signal_date": None,
    }


def load_watchlist(user_id: str) -> list:
    """The user's watched tickers, each enriched with its current screener row
    plus the watchlist metadata (price_at_add, added_at, change-since-add)."""
    items = watchlist_items(user_id)
    if not items:
        return []
    rows, _regime, _as_of = load_universe()
    by_ticker = {r["ticker"]: r for r in rows}
    out = []
    for it in items:
        tk = it.get("ticker")
        base = by_ticker.get(tk) or _row_stub(tk)
        pa = it.get("price_at_add")
        cur = base.get("price")
        change_pct = None
        if pa and cur:
            try:
                change_pct = round((float(cur) - float(pa)) / float(pa) * 100, 2)
            except (TypeError, ValueError, ZeroDivisionError):
                change_pct = None
        out.append({**base, "price_at_add": _num(pa), "added_at": it.get("added_at"),
                    "change_pct": change_pct})
    return out


# ── Single-stock detail ───────────────────────────────────────────────────────
def stock_changes(ticker: str):
    """Per-pillar + macro-overlay deltas between the ticker's two most recent
    clean scored days (structured port of _whats_changed_html). None if there's
    no prior scored day to compare against."""
    tk = (ticker or "").strip().upper()
    if not tk:
        return None
    sb = _get_supabase()
    if not sb:
        return None
    from datetime import date, timedelta, date as _date
    since = (date.today() - timedelta(days=21)).isoformat()
    try:
        rows = (sb.table("signal_log")
                .select("signal_date,adj_composite,composite,momentum,quality,volume,value,sentiment")
                .eq("ticker", tk).gte("signal_date", since)
                .not_.is_("composite", "null")
                .order("signal_date", desc=True).execute()).data or []
    except Exception as e:
        log.warning("stock_changes read failed: %s", e)
        return None

    def _pd(s):
        try:
            return _date.fromisoformat(s)
        except (TypeError, ValueError):
            return None

    distinct, seen = [], set()
    for rr in rows:
        d = rr.get("signal_date")
        if d and d not in seen:
            seen.add(d); distinct.append(rr)
    if len(distinct) < 2:
        return None
    now = distinct[0]
    nd = _pd(now.get("signal_date"))
    prev = None
    if nd:
        for rr in distinct[1:]:
            rd = _pd(rr.get("signal_date"))
            if rd and (nd - rd).days >= 1:
                prev = rr
                break
    if prev is None:
        prev = distinct[-1]
    if prev.get("signal_date") == now.get("signal_date"):
        return None

    def _f(x, k):
        try:
            return float(x.get(k))
        except (TypeError, ValueError):
            return None

    pillars = []
    for key, lab in (("momentum", "Momentum"), ("quality", "Quality"),
                     ("volume", "Volume"), ("value", "Value"), ("sentiment", "Sentiment")):
        pn, pp = _f(now, key), _f(prev, key)
        if pn is None or pp is None:
            continue
        dd = round(pn - pp)
        if abs(dd) < 1:
            continue
        pillars.append({"key": key, "label": lab, "delta": int(dd)})

    a_now, c_now = _f(now, "adj_composite"), _f(now, "composite")
    a_prev, c_prev = _f(prev, "adj_composite"), _f(prev, "composite")
    macro_delta, macro_unchanged = None, False
    if None not in (a_now, c_now, a_prev, c_prev):
        md = round((a_now - c_now) - (a_prev - c_prev))
        if abs(md) >= 1:
            macro_delta = int(md)
        else:
            macro_unchanged = True

    return {
        "prev_date": prev.get("signal_date"),
        "prev_score": round(a_prev) if a_prev is not None else None,
        "now_score": round(a_now) if a_now is not None else None,
        "pillars": pillars,
        "macro_delta": macro_delta,
        "macro_unchanged": macro_unchanged,
    }


def load_stock(ticker: str):
    """Enriched screener row for one ticker + its universe percentile + the
    what's-changed deltas. None if the ticker isn't in the scored universe."""
    tk = (ticker or "").strip().upper()
    if not tk:
        return None
    rows, _regime, _as_of = load_universe()
    row = next((r for r in rows if r["ticker"] == tk), None)
    if row is None:
        return None
    import bisect
    scores = sorted(r["score"] for r in rows)
    n = len(scores) or 1
    pct_rank = round(bisect.bisect_right(scores, row["score"]) / n * 100)
    return {**row, "pct_rank": pct_rank, "changes": stock_changes(tk)}


# ── vs-SPY price series (stored-first, no live pull) ──────────────────────────
def stock_price_series(ticker: str, days: int = 20):
    """The ticker's recent daily prices (from signal_log) alongside SPY (from
    benchmark_price) over the same sessions — the data for the detail page's
    vs-SPY sparkline. Entirely from stored data: the same source the model
    portfolio rebuilds its equity curve from. Returns raw price pairs; the client
    rebases to 0%. Degrades to empty series (chart skipped) if history is thin."""
    tk = (ticker or "").strip().upper()
    if not tk:
        return None
    sb = _get_supabase_admin() or _get_supabase()
    if not sb:
        return None
    from datetime import date, timedelta
    since = (date.today() - timedelta(days=int(days * 1.6) + 10)).isoformat()

    try:
        srows = (sb.table("signal_log").select("signal_date,price")
                 .eq("ticker", tk).gte("signal_date", since)
                 .not_.is_("price", "null")
                 .order("signal_date", desc=False).execute()).data or []
    except Exception as e:
        log.warning("price series (stock) failed: %s", e)
        return None

    smap = {}
    for r in srows:
        d = r.get("signal_date"); p = _num(r.get("price"))
        if d and p is not None:
            smap[d] = p                       # asc order → last write per date wins
    sdates = sorted(smap.keys())[-days:]
    empty = {"ticker": tk, "days": days, "stock": [], "spy": [], "stock_ret_pct": None, "spy_ret_pct": None}
    if len(sdates) < 2:
        return empty

    try:
        brows = (sb.table("benchmark_price").select("d,close")
                 .gte("d", sdates[0]).lte("d", sdates[-1])
                 .order("d", desc=False).execute()).data or []
    except Exception as e:
        log.warning("price series (spy) failed: %s", e)
        brows = []
    kmap = {}
    for r in brows:
        d = r.get("d"); c = _num(r.get("close"))
        if d and c is not None:
            kmap[d] = c

    stock = [{"d": d, "v": smap[d]} for d in sdates]
    spy = [{"d": d, "v": kmap[d]} for d in sdates if d in kmap]

    def _ret(arr):
        if len(arr) >= 2 and arr[0]["v"]:
            return round((arr[-1]["v"] / arr[0]["v"] - 1) * 100, 1)
        return None

    return {"ticker": tk, "days": days, "stock": stock, "spy": spy,
            "stock_ret_pct": _ret(stock), "spy_ret_pct": _ret(spy)}


# ── Portfolio / holdings (authed read-write) ──────────────────────────────────
# Same security model as the watchlist: service-role writes, user_id always from
# the verified token. Adds shares/avg_cost so we can surface market value + P&L
# on top of the conviction scores.
def portfolio_holdings(user_id: str) -> list:
    sb = _get_supabase_admin()
    if not sb:
        return []
    try:
        resp = (sb.table("holdings").select("ticker,shares,avg_cost,entry_date,notes")
                .eq("user_id", user_id).order("ticker").execute())
        return resp.data or []
    except Exception as e:
        log.warning("holdings read failed: %s", e)
        return []


def upsert_holding(user_id: str, ticker: str, shares, avg_cost, entry_date=None, notes: str = "") -> bool:
    from datetime import date, datetime
    tk = (ticker or "").strip().upper()
    if not tk or tk not in _SECTORS:
        return False
    try:
        sh = round(float(shares), 4)
        ac = round(float(avg_cost), 4)
    except (TypeError, ValueError):
        return False
    if sh <= 0 or ac < 0:
        return False
    sb = _get_supabase_admin()
    if not sb:
        return False
    try:
        rec = {"user_id": user_id, "ticker": tk, "shares": sh, "avg_cost": ac,
               "entry_date": str(entry_date or date.today()), "notes": (notes or "")[:200],
               "updated_at": datetime.now().isoformat()}
        sb.table("holdings").upsert(rec, on_conflict="user_id,ticker").execute()
        return True
    except Exception as e:
        log.warning("holding upsert failed: %s", e)
        return False


def delete_holding(user_id: str, ticker: str) -> bool:
    tk = (ticker or "").strip().upper()
    if not tk:
        return False
    sb = _get_supabase_admin()
    if not sb:
        return False
    try:
        sb.table("holdings").delete().eq("user_id", user_id).eq("ticker", tk).execute()
        return True
    except Exception as e:
        log.warning("holding delete failed: %s", e)
        return False


def _tier(score: float) -> str:
    return "HIGH" if score >= 60 else ("LOW" if score < 45 else "MOD")


def load_portfolio(user_id: str) -> dict:
    """Holdings enriched with current conviction rows + per-position market value
    and unrealized P&L, plus a portfolio-level conviction/P&L summary."""
    items = portfolio_holdings(user_id)
    rows, regime, _as_of = load_universe()
    by = {r["ticker"]: r for r in rows}
    out = []
    tv = tc = 0.0
    scores = []
    hi = mo = lo = 0
    for it in items:
        tk = it.get("ticker")
        base = by.get(tk) or _row_stub(tk)
        shares = _num(it.get("shares")) or 0.0
        avg_cost = _num(it.get("avg_cost")) or 0.0
        price = base.get("price")
        mv = round(shares * price, 2) if price else None
        cb = round(shares * avg_cost, 2) if avg_cost else None
        pnl = round(mv - cb, 2) if (mv is not None and cb is not None) else None
        pnl_pct = round(pnl / cb * 100, 2) if (pnl is not None and cb) else None
        out.append({**base, "shares": shares, "avg_cost": avg_cost,
                    "entry_date": it.get("entry_date"), "notes": it.get("notes"),
                    "market_value": mv, "cost_basis": cb, "pnl": pnl, "pnl_pct": pnl_pct})
        if mv is not None:
            tv += mv
        if cb is not None:
            tc += cb
        if tk in by:
            s = float(base.get("score", 0.0) or 0.0)
            scores.append(s)
            t = _tier(s)
            hi += t == "HIGH"
            mo += t == "MOD"
            lo += t == "LOW"

    total_pnl = round(tv - tc, 2)
    summary = {
        "count": len(items), "hi": hi, "mo": mo, "lo": lo,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
        "total_value": round(tv, 2), "total_cost": round(tc, 2),
        "total_pnl": total_pnl,
        "total_pnl_pct": round(total_pnl / tc * 100, 2) if tc else None,
    }
    return {"regime": regime, "summary": summary, "holdings": out}


# ── Model portfolio / track record ─────────────────────────────────────────────
# Faithful port of app.py `_track_record_data`: a real $100K ledger, $2K per
# position, entries deploy cash (shares = 2000/entry_price), exits return
# shares x exit_price to cash (so realized P&L sticks), and the whole book is
# marked to the daily close every session. SPY benchmark = $100K invested at
# inception, marked daily. DB-only: held-ticker closes from signal_log, SPY from
# benchmark_price — no pandas, no yfinance. Rebuilt from data the intraday price
# cron keeps fresh, cached briefly (MODEL_CACHE_TTL_SECONDS).
MODEL_EPOCH = "live"
_MP_POS_SIZE = 2000.0
_MP_BASE = 100000.0
_MODEL_CACHE: dict = {"ts": 0.0, "payload": None}
_MP_EMPTY = {"inception": None, "curve": [], "stats": None, "day": None,
             "prices_as_of": None, "positions": [], "exits": [], "sector_counts": []}


def _model_sec_map() -> dict:
    """SECTORS merged with held-but-dropped overrides so out-of-universe holdings
    (e.g. a name not yet back after a Russell reconstitution) still resolve to a
    real sector instead of 'Unknown'."""
    try:
        from universe_data import SECTORS, HELD_SECTOR_OVERRIDES  # type: ignore
        return {**SECTORS, **HELD_SECTOR_OVERRIDES}
    except Exception:
        return dict(_SECTORS)


def _mp_fetch_all(sb, table, cols, filters, order_col, desc=False, cap=8):
    """Paginated select. filters = list of (method_name, args_tuple)."""
    out: list = []
    PAGE = 1000
    page = 0
    while page < cap:
        q = sb.table(table).select(cols)
        for meth, args in filters:
            q = getattr(q, meth)(*args)
        q = q.order(order_col, desc=desc).range(page * PAGE, (page + 1) * PAGE - 1)
        batch = q.execute().data or []
        out.extend(batch)
        if len(batch) < PAGE:
            break
        page += 1
    return out


def load_model_portfolio() -> dict:
    """Equity curve vs SPY + track-record stats + open positions (enriched from
    signal_log) + closed trades for the live model cohort. Cached briefly."""
    now = time.time()
    cached = _MODEL_CACHE["payload"]
    if cached is not None and (now - _MODEL_CACHE["ts"]) < settings.MODEL_CACHE_TTL_SECONDS:
        return cached

    sb = _get_supabase_admin() or _get_supabase()
    if not sb:
        return _MP_EMPTY
    try:
        SEC = _model_sec_map()

        # 1) every position in the live cohort (needed for the ledger replay)
        allpos = _mp_fetch_all(sb, "model_portfolio_positions", "*",
                               [("eq", ("epoch", MODEL_EPOCH))], "entry_date")
        if not allpos:
            _MODEL_CACHE.update(ts=now, payload=_MP_EMPTY)
            return _MP_EMPTY
        # dedup exact (ticker, entry_date, exit_date); newest id wins
        seen: dict = {}
        for p in allpos:
            k = (p["ticker"], str(p.get("entry_date") or "")[:10], str(p.get("exit_date") or "")[:10])
            if k not in seen or (p.get("id") or 0) > (seen[k].get("id") or 0):
                seen[k] = p
        positions = list(seen.values())

        inception = min(str(p["entry_date"])[:10] for p in positions)
        tickers = sorted({p["ticker"] for p in positions})

        # 2) stored price frame — SPY spine (date axis) + held-ticker closes
        brows = _mp_fetch_all(sb, "benchmark_price", "d,close",
                              [("gte", ("d", inception))], "d")
        spy = {str(r["d"])[:10]: float(r["close"]) for r in brows
               if r.get("close") is not None}
        srows = _mp_fetch_all(sb, "signal_log", "ticker,signal_date,price",
                              [("in_", ("ticker", tickers)), ("gte", ("signal_date", inception))],
                              "signal_date")
        pmap: dict = {}
        for r in srows:
            tk = r.get("ticker"); pv = r.get("price")
            d = str(r.get("signal_date") or "")[:10]
            if tk and pv is not None and len(d) == 10:
                pmap.setdefault(tk, {})[d] = float(pv)

        curve: list = []
        stats = None
        day = None

        if len(spy) >= 2:
            dates = sorted(spy.keys())

            def price_on(tk, d, fallback):
                m = pmap.get(tk)
                if not m:
                    return fallback
                if d in m:
                    return m[d]
                prior = [dt for dt in m if dt <= d]
                return m[max(prior)] if prior else fallback

            entries_by_date: dict = {}
            exits_by_date: dict = {}
            for p in positions:
                entries_by_date.setdefault(str(p["entry_date"])[:10], []).append(p)
                xd = str(p.get("exit_date") or "")[:10]
                if len(xd) == 10:
                    exits_by_date.setdefault(xd, []).append(p)

            cash = _MP_BASE
            open_lots: dict = {}
            model_series: list = []
            for d in dates:
                for p in exits_by_date.get(d, []):
                    lot = open_lots.pop(p.get("id"), None)
                    if lot:
                        xp = p.get("exit_price") or price_on(lot["ticker"], d, lot["entry_price"])
                        cash += lot["shares"] * float(xp)
                for p in entries_by_date.get(d, []):
                    ep = p.get("entry_price")
                    if not ep or float(ep) <= 0:
                        continue
                    open_lots[p.get("id")] = {"ticker": p["ticker"],
                                              "shares": _MP_POS_SIZE / float(ep),
                                              "entry_price": float(ep)}
                    cash -= _MP_POS_SIZE
                mtm = cash + sum(lot["shares"] * price_on(lot["ticker"], d, lot["entry_price"])
                                 for lot in open_lots.values())
                model_series.append((d, mtm))

            spy0 = spy[dates[0]]
            spy_series = [(d, _MP_BASE * spy[d] / spy0) for d in dates]
            curve = [{"d": d, "model": round(m, 2), "spy": round(s, 2)}
                     for (d, m), (_, s) in zip(model_series, spy_series)]

            m_last = model_series[-1][1]; s_last = spy_series[-1][1]
            model_ret = (m_last / _MP_BASE - 1) * 100
            spy_ret = (s_last / _MP_BASE - 1) * 100
            day_model = ((model_series[-1][1] / model_series[-2][1] - 1) * 100
                         if len(model_series) > 1 and model_series[-2][1] else 0.0)
            day_spy = ((spy_series[-1][1] / spy_series[-2][1] - 1) * 100
                       if len(spy_series) > 1 and spy_series[-2][1] else 0.0)

            # DAY move — mark TODAY's open book at the prior session's closes and
            # compare to now. `now` reflects the intraday cron (incl. pre/post-
            # market), so this is the position-weighted "prev close → now" move
            # the Streamlit TODAY card shows, robust to same-day entries/exits.
            if len(dates) >= 2:
                d_prev = dates[-2]
                model_prev = cash + sum(
                    lot["shares"] * price_on(lot["ticker"], d_prev, lot["entry_price"])
                    for lot in open_lots.values())
                model_now = m_last
                dm_dollar = model_now - model_prev
                dm_pct = (dm_dollar / model_prev * 100) if model_prev else 0.0
                spy_prev_v = _MP_BASE * spy[d_prev] / spy0
                spy_now_v = s_last
                ds_pct = ((spy[dates[-1]] / spy[d_prev] - 1) * 100) if spy[d_prev] else 0.0
                day = {
                    "model_now": round(model_now, 2), "model_prev": round(model_prev, 2),
                    "model_pct": round(dm_pct, 2), "model_dollar": round(dm_dollar, 2),
                    "spy_now": round(spy_now_v, 2), "spy_prev": round(spy_prev_v, 2),
                    "spy_pct": round(ds_pct, 2), "spy_dollar": round(spy_now_v - spy_prev_v, 2),
                    "vs_spy_pct": round(dm_pct - ds_pct, 2),
                }
            stats = {
                "inception": inception,
                "model_value": round(m_last, 2), "spy_value": round(s_last, 2),
                "model_ret": round(model_ret, 2), "spy_ret": round(spy_ret, 2),
                "alpha": round(model_ret - spy_ret, 2),
                "day_model": round(day_model, 2), "day_spy": round(day_spy, 2),
                "basis": _MP_BASE, "n_sessions": len(dates),
            }

        # 3) closed trades
        exits: list = []
        for p in positions:
            xd = str(p.get("exit_date") or "")[:10]
            if len(xd) == 10 and p.get("exit_price") and p.get("entry_price"):
                try:
                    ret = (float(p["exit_price"]) / float(p["entry_price"]) - 1) * 100
                except Exception:
                    ret = 0.0
                exits.append({"ticker": p["ticker"], "sector": SEC.get(p["ticker"], "\u2014"),
                              "entry_date": str(p["entry_date"])[:10], "exit_date": xd,
                              "ret": round(ret, 2), "reason": p.get("exit_reason") or "\u2014"})
        exits.sort(key=lambda x: x["exit_date"], reverse=True)

        # 4) open positions — active rows deduped newest-per-ticker, enriched
        active = [p for p in positions if p.get("is_active")]
        adedup: dict = {}
        for p in active:
            tk = p["ticker"]; ed = str(p.get("entry_date") or ""); pid = p.get("id") or 0
            cur = adedup.get(tk)
            if (cur is None or ed > str(cur.get("entry_date") or "")
                    or (ed == str(cur.get("entry_date") or "") and pid > (cur.get("id") or 0))):
                adedup[tk] = p
        active = list(adedup.values())
        atk = sorted({p["ticker"] for p in active})

        latest_rows: dict = {}
        if atk:
            lresp = (sb.table("signal_log").select(_SCREENER_COLS)
                     .in_("ticker", atk).order("signal_date", desc=True)
                     .limit(len(atk) * 4).execute())
            for r in (lresp.data or []):
                latest_rows.setdefault(r["ticker"], r)

        open_positions: list = []
        sect: dict = {}
        for p in active:
            tk = p["ticker"]
            raw = latest_rows.get(tk)
            base = _enrich(raw) if raw else _row_stub(tk)
            base["sector"] = SEC.get(tk, base.get("sector") or "Unknown")
            entry_price = _num(p.get("entry_price"))
            cur_price = base.get("price")
            ret_since = (round((cur_price / entry_price - 1) * 100, 2)
                         if (entry_price and cur_price) else None)
            open_positions.append({**base,
                                   "entry_date": (str(p.get("entry_date") or "")[:10] or None),
                                   "entry_price": entry_price,
                                   "entry_score": _num(p.get("entry_score")),
                                   "current_price": cur_price,
                                   "ret_since_entry": ret_since})
            s = SEC.get(tk, "Unknown")
            sect[s] = sect.get(s, 0) + 1
        open_positions.sort(key=lambda r: (r.get("score") or 0.0), reverse=True)
        sector_counts = [{"sector": s, "count": c}
                         for s, c in sorted(sect.items(), key=lambda x: x[1], reverse=True)]

        # prices-as-of — freshness of the stored intraday marks (SPY's
        # benchmark_price row is rewritten every cron cycle), doubles as a cron
        # heartbeat. Returned as ISO; the client formats + ages it.
        prices_as_of = None
        try:
            fr = (sb.table("benchmark_price").select("updated_at")
                  .not_.is_("updated_at", "null")
                  .order("updated_at", desc=True).limit(1).execute())
            if fr.data and fr.data[0].get("updated_at"):
                prices_as_of = str(fr.data[0]["updated_at"])
        except Exception:
            prices_as_of = None

        payload = {"inception": inception, "curve": curve, "stats": stats, "day": day,
                   "prices_as_of": prices_as_of,
                   "positions": open_positions, "exits": exits,
                   "sector_counts": sector_counts}
        _MODEL_CACHE.update(ts=now, payload=payload)
        return payload
    except Exception as e:
        logging.warning("load_model_portfolio failed: %s", e)
        return _MP_EMPTY


# ── Hidden gems ─────────────────────────────────────────────────────────────────
# Faithful port of model_engine.detect_hidden_gems: a curated shortlist (max 12)
# of under-followed mid/small-caps clearing a high conviction bar, with a reason
# string per name. Regime sets the thresholds; mega-caps and large-caps excluded.
_GEM_MEGA = {
    "NVDA", "MSFT", "AAPL", "META", "GOOGL", "GOOG", "AMZN", "TSLA", "NFLX",
    "JPM", "V", "MA", "UNH", "JNJ", "ABBV", "PG", "KO", "WMT", "COST",
    "XOM", "CVX", "BAC", "GS", "MS", "BLK", "LLY", "MRK", "TMO", "HD", "LOW",
}
_GEMS_CACHE: dict = {"ts": 0.0, "payload": None}


def _gem_reasons(f: dict, mom: float, qua: float, vol: float, regime: str) -> list:
    reasons: list = []
    rg = f.get("rg")
    if rg and rg > 20: reasons.append(f"Revenue growing {rg:.0f}% YoY")
    elif rg and rg > 10: reasons.append(f"Revenue +{rg:.0f}% YoY")
    eg = f.get("eg")
    if eg and eg > 40: reasons.append(f"Earnings accelerating {eg:.0f}% YoY")
    elif eg and eg > 20: reasons.append(f"Earnings +{eg:.0f}% YoY")
    ib = f.get("ib")
    if ib and ib > 50: reasons.append(f"Strong insider buying ({ib:.0f}% buy ratio)")
    elif ib and ib > 35: reasons.append(f"Insider buying elevated ({ib:.0f}%)")
    sp = f.get("sp")
    if sp is not None and sp < 3: reasons.append(f"Low short interest ({sp:.1f}%)")
    elif sp is not None and sp < 5: reasons.append(f"Modest short interest ({sp:.1f}%)")
    br = f.get("br")
    if br and br == 100: reasons.append("Beat estimates all 4 quarters")
    elif br and br >= 75: reasons.append(f"Beat estimates {br:.0f}% of quarters")
    fcf = f.get("fcf")
    if fcf and fcf > 5: reasons.append(f"Strong FCF yield ({fcf:.1f}%)")
    if len(reasons) < 2:
        if mom >= 70: reasons.append(f"Strong price momentum (score {mom:.0f})")
        if qua >= 70: reasons.append(f"High quality fundamentals (score {qua:.0f})")
        if vol >= 65: reasons.append(f"Elevated institutional volume (score {vol:.0f})")
        if regime == "RISK_OFF": reasons.append("Surfaced in RISK-OFF screen — high-conviction filter applied")
        elif regime == "RISK_ON": reasons.append("Strong signal in risk-on environment")
    return reasons[:4]


def _compute_gems(rows: list, regime: str) -> tuple:
    """Single source of truth for hidden-gem detection — used BOTH to set the
    screener's is_hidden_gem flag (via load_universe) and to build the Gems page
    list, so the two never disagree. Returns (gem_dicts_with_reasons[:12], threshold)."""
    if regime in ("RISK_OFF", "HIGH VOLATILITY"):
        th_c, th_q, th_m = 67, 58, 62
    else:
        th_c, th_q, th_m = 62, 55, 58
    try:
        from universe_data import FUNDAMENTALS, SMALL_MID_POOL  # type: ignore
    except Exception:
        FUNDAMENTALS, SMALL_MID_POOL = {}, set()

    gems: list = []
    for s in rows:
        tk = s.get("ticker")
        if not tk or tk in _GEM_MEGA:
            continue
        try:
            adj = float(s.get("score") or 0)
            mom = float(s.get("momentum") or 0)
            qua = float(s.get("quality") or 0)
            vol = float(s.get("volume") or 0)
        except (TypeError, ValueError):
            continue
        if adj < th_c or qua < th_q or mom < th_m:
            continue
        f = FUNDAMENTALS.get(tk, {})
        mktcap = s.get("mktcap") or f.get("mktcap")
        if mktcap == "large":
            continue
        if mktcap not in ("mid", "small") and tk not in SMALL_MID_POOL:
            continue
        reasons = _gem_reasons(f, mom, qua, vol, regime)
        if not reasons:
            continue
        gems.append({**s, "gem_reasons": reasons, "gem_regime": regime})

    gems.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    return gems[:12], th_c


def load_hidden_gems() -> dict:
    """Return {regime, threshold, as_of, count, gems[]} — the curated gem list,
    computed off the cached universe + macro regime (mirrors the Streamlit page's
    detect_hidden_gems). Cached briefly."""
    now = time.time()
    cached = _GEMS_CACHE["payload"]
    if cached is not None and (now - _GEMS_CACHE["ts"]) < settings.CACHE_TTL_SECONDS:
        return cached

    rows, _regime_obj, as_of = load_universe()
    regime = (load_macro_detail() or {}).get("regime") or "NEUTRAL"
    gems, th_c = _compute_gems(rows, regime)
    payload = {"regime": regime, "threshold": th_c, "as_of": as_of,
               "count": len(gems), "gems": gems}
    _GEMS_CACHE.update(ts=now, payload=payload)
    return payload


def get_user_plan(uid: str) -> str:
    """Live plan lookup from users.plan so a promotion to pro takes effect on the
    very next request — no re-login, no stale-token wait. Fail-closed to 'free'."""
    if not uid:
        return "free"
    sb = _get_supabase_admin() or _get_supabase()
    if not sb:
        return "free"
    try:
        r = sb.table("users").select("plan").eq("id", str(uid)).limit(1).execute()
        if r.data and r.data[0].get("plan"):
            return str(r.data[0]["plan"]).lower()
    except Exception as e:
        logging.warning("get_user_plan failed for %s: %s", uid, e)
    return "free"


# ── Portfolio simulator ─────────────────────────────────────────────────────────
# Port of page_simulator's profile_tickers: rank the scored universe by the
# profile metric (HIGH=momentum, LOW=(quality+value)/2, MEDIUM=conviction), take
# the top N with a per-sector cap for diversification, top off if thin. The
# client handles amount, weighting, and add/remove over these picks.
_SIM_PROFILES = {"HIGH", "MEDIUM", "LOW"}


def load_simulator(profile: str, n: int = 20, sector_cap: int = 4) -> dict:
    profile = (profile or "MEDIUM").upper()
    if profile not in _SIM_PROFILES:
        profile = "MEDIUM"
    rows, _regime_obj, as_of = load_universe()

    def key(r):
        if profile == "HIGH":
            return float(r.get("momentum") or 0)
        if profile == "LOW":
            return (float(r.get("quality") or 0) + float(r.get("value") or 0)) / 2.0
        return float(r.get("score") or 0)  # MEDIUM = conviction (adj_composite)

    ranked = sorted([r for r in rows if r.get("ticker")], key=key, reverse=True)
    picked: list = []
    sec_counts: dict = {}
    for r in ranked:
        sec = r.get("sector") or "Unknown"
        if sec_counts.get(sec, 0) >= sector_cap:
            continue
        picked.append(r)
        sec_counts[sec] = sec_counts.get(sec, 0) + 1
        if len(picked) >= n:
            break
    if len(picked) < n:  # top off if the sector cap left us short
        chosen = {r["ticker"] for r in picked}
        for r in ranked:
            if r["ticker"] not in chosen:
                picked.append(r)
                if len(picked) >= n:
                    break
    return {"profile": profile, "as_of": as_of, "count": len(picked), "picks": picked}


# ── Alerts ──────────────────────────────────────────────────────────────────────
# Port of the Streamlit alerts model: a notifications feed (system-generated
# conviction/macro/gem alerts) + user-defined price_alerts (CRUD). All writes go
# through the service-role client and are scoped to the caller's user_id so one
# user can never touch another's alerts.
ALERT_KINDS = {
    "value_lower": "Enters lower value range",
    "value_upper": "Enters upper value range",
    "price_below": "Price drops to / below",
    "price_above": "Price rises to / above",
    "conviction_high": "Moves to HIGH conviction",
    "conviction_low": "Drops to LOW conviction",
    "gem": "Flagged a hidden gem",
}
ALERT_SCOPES = {"ticker", "watchlist", "portfolio", "model"}
_ALERT_PRICE_KINDS = {"price_below", "price_above"}


def load_alerts(uid: str) -> dict:
    sb = _get_supabase_admin() or _get_supabase()
    if not sb or not uid:
        return {"notifications": [], "unread": 0, "alerts": []}
    notifs: list = []
    alerts: list = []
    try:
        nr = (sb.table("notifications").select("*").eq("user_id", str(uid))
              .order("created_at", desc=True).limit(50).execute())
        notifs = nr.data or []
    except Exception as e:
        logging.warning("load_alerts notifications failed: %s", e)
    try:
        ar = (sb.table("price_alerts").select("*").eq("user_id", str(uid))
              .order("created_at", desc=True).execute())
        alerts = ar.data or []
    except Exception as e:
        logging.warning("load_alerts price_alerts failed: %s", e)
    for n in notifs:
        n["id"] = str(n.get("id"))
    for a in alerts:
        a["id"] = str(a.get("id"))
        a["kind_label"] = ALERT_KINDS.get(a.get("kind"), a.get("kind"))
    unread = sum(1 for n in notifs if not n.get("is_read"))
    return {"notifications": notifs, "unread": unread, "alerts": alerts}


def create_alert(uid, ticker, kind, threshold=None, scope="ticker") -> tuple:
    """(ok, error_code). Validates kind/scope/ticker before insert."""
    if kind not in ALERT_KINDS:
        return False, "invalid_kind"
    if scope not in ALERT_SCOPES:
        return False, "invalid_scope"
    tk = (ticker or "").upper().strip() or None
    if scope == "ticker":
        if not tk or tk not in _SECTORS:
            return False, "invalid_ticker"
    else:
        tk = None  # collections don't carry a single ticker
        if kind in _ALERT_PRICE_KINDS:
            return False, "price_not_for_collections"
    th = None
    if threshold is not None:
        try:
            th = float(threshold)
        except (TypeError, ValueError):
            th = None
    sb = _get_supabase_admin()
    if not sb:
        return False, "no_db"
    try:
        sb.table("price_alerts").insert({
            "user_id": str(uid), "ticker": tk, "kind": kind,
            "threshold": th, "scope": scope, "active": True, "armed": True,
        }).execute()
        return True, None
    except Exception as e:
        logging.warning("create_alert failed: %s", e)
        return False, "insert_failed"


def delete_alert(uid, alert_id) -> bool:
    sb = _get_supabase_admin()
    if not sb:
        return False
    try:
        # user-scoped delete — cannot remove another user's alert
        sb.table("price_alerts").delete().eq("id", alert_id).eq("user_id", str(uid)).execute()
        try:
            sb.table("price_alert_state").delete().eq("alert_id", alert_id).execute()
        except Exception:
            pass  # best-effort; orphan state rows are harmless
        return True
    except Exception as e:
        logging.warning("delete_alert failed: %s", e)
        return False


def toggle_alert(uid, alert_id, active: bool) -> bool:
    sb = _get_supabase_admin()
    if not sb:
        return False
    try:
        # re-arm on resume so a paused-while-true alert can fire cleanly again
        (sb.table("price_alerts").update({"active": bool(active), "armed": True})
         .eq("id", alert_id).eq("user_id", str(uid)).execute())
        return True
    except Exception as e:
        logging.warning("toggle_alert failed: %s", e)
        return False


def mark_alerts_read(uid, ids=None) -> bool:
    sb = _get_supabase_admin()
    if not sb:
        return False
    try:
        q = sb.table("notifications").update({"is_read": True}).eq("user_id", str(uid))
        if ids:
            q = q.in_("id", ids)
        q.execute()
        return True
    except Exception as e:
        logging.warning("mark_alerts_read failed: %s", e)
        return False


# ── Account: notification preferences + phone verification ───────────────────────
# Delivery-channel prefs live in users.notifications (jsonb); phone verification in
# users.phone / phone_verified. The alerts cron (alerts_engine.notify) reads these
# to decide email/SMS fan-out, so this is the config surface that closes the loop.
_NOTIF_DEFAULTS = {
    "email": False,          # weekly digest
    "signals": True,         # in-app conviction-change bell
    "alerts": True,          # in-app macro-regime bell
    "low_alert_email": False,  # email on drop to LOW
    "alert_email": True,     # email when a user alert fires
    "alert_sms": False,      # SMS when a user alert fires (opt-in)
}


def _norm_phone(p: str) -> str:
    p = (p or "").strip()
    if not p:
        return ""
    if p.startswith("+"):
        return "+" + "".join(ch for ch in p[1:] if ch.isdigit())
    d = "".join(ch for ch in p if ch.isdigit())
    if len(d) == 10:
        return "+1" + d
    if len(d) == 11 and d.startswith("1"):
        return "+" + d
    return ("+" + d) if d else ""


def get_notification_prefs(uid: str) -> dict:
    """Return {prefs:{...}, phone, phone_verified}. Fail-safe to defaults."""
    out = {"prefs": dict(_NOTIF_DEFAULTS), "phone": "", "phone_verified": False}
    sb = _get_supabase_admin() or _get_supabase()
    if not sb or not uid:
        return out
    try:
        r = (sb.table("users").select("notifications,phone,phone_verified")
             .eq("id", str(uid)).limit(1).execute().data or [])
        if r:
            row = r[0]
            raw = row.get("notifications") or {}
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raw = {}
            out["prefs"] = {**_NOTIF_DEFAULTS, **(raw or {})}
            out["phone"] = row.get("phone") or ""
            out["phone_verified"] = bool(row.get("phone_verified"))
    except Exception as e:
        logging.warning("get_notification_prefs failed for %s: %s", uid, e)
    return out


def save_notification_prefs(uid: str, prefs: dict) -> bool:
    """Merge the six known keys into users.notifications (preserving any others)."""
    sb = _get_supabase_admin()
    if not sb or not uid:
        return False
    cur = get_notification_prefs(uid)["prefs"]
    merged = dict(cur)
    for k in _NOTIF_DEFAULTS:
        if k in (prefs or {}):
            merged[k] = bool(prefs[k])
    try:
        resp = (sb.table("users").update({"notifications": merged})
                .eq("id", str(uid)).execute())
        if not getattr(resp, "data", None):
            logging.warning("save_notification_prefs wrote 0 rows for %s", uid)
            return False
        return True
    except Exception as e:
        logging.warning("save_notification_prefs failed for %s: %s", uid, e)
        return False


def send_phone_verify_code(uid: str, phone: str) -> tuple:
    """Store phone (unverified) + a fresh 6-digit code and text it.
    (ok, msg). SMS fails soft until Twilio/A2P is live — the code is still saved."""
    import random
    from datetime import datetime, timedelta, timezone
    sb = _get_supabase_admin()
    if not sb or not uid:
        return (False, "No database connection")
    ph = _norm_phone(phone)
    if not ph or len(ph) < 11:
        return (False, "Enter a valid phone number")
    code = f"{random.randint(0, 999999):06d}"
    exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    try:
        sb.table("users").update({
            "phone": ph, "phone_verified": False,
            "phone_verify_code": code, "phone_verify_expires": exp,
        }).eq("id", str(uid)).execute()
    except Exception as e:
        logging.warning("send_phone_verify_code save failed: %s", e)
        return (False, "Could not save phone number")
    try:
        from sms import send_sms
        res = send_sms(ph, f"Your QNTM verification code is {code}. It expires in 10 minutes.")
    except Exception:
        res = {"success": False}
    if not res.get("success"):
        return (False, "Saved, but the text couldn't be sent yet — SMS goes live once "
                       "carrier registration (A2P 10DLC) is approved.")
    return (True, "Code sent — check your texts.")


def verify_phone_code(uid: str, code: str) -> tuple:
    """Check the code + expiry and mark phone_verified. (ok, msg)."""
    from datetime import datetime, timezone
    sb = _get_supabase_admin()
    if not sb or not uid:
        return (False, "No database connection")
    try:
        rows = (sb.table("users")
                .select("phone,phone_verify_code,phone_verify_expires")
                .eq("id", str(uid)).execute().data or [])
    except Exception:
        return (False, "Lookup failed")
    if not rows:
        return (False, "User not found")
    want = (rows[0].get("phone_verify_code") or "").strip()
    exp = rows[0].get("phone_verify_expires")
    if not want:
        return (False, "Request a code first")
    try:
        if exp and datetime.fromisoformat(str(exp).replace("Z", "+00:00")) < datetime.now(timezone.utc):
            return (False, "Code expired — request a new one")
    except Exception:
        pass
    if (code or "").strip() != want:
        return (False, "Incorrect code")
    try:
        sb.table("users").update({"phone_verified": True, "phone_verify_code": None}).eq("id", str(uid)).execute()
    except Exception:
        return (False, "Could not save verification")
    return (True, "Phone verified")

# ── Billing state (Stripe) ────────────────────────────────────────────────────
# Service-role read/merge/write of the users.notifications JSON blob, mirroring
# db.set_stripe_billing / get_stripe_billing / schedule_cancellation WITHOUT
# Streamlit. Billing keys share the blob with notification prefs, so every write
# is read-merge-write to preserve the other keys.
_BILLING_KEYS = ("stripe_customer_id", "stripe_subscription_id", "billing_active",
                 "stripe_status", "cancel_at", "trial_end", "current_period_end")


def _read_notif_blob(uid: str) -> dict:
    sb = _get_supabase_admin() or _get_supabase()
    if not sb or not uid:
        return {}
    try:
        r = (sb.table("users").select("notifications").eq("id", str(uid)).limit(1).execute().data or [])
        if not r:
            return {}
        raw = r[0].get("notifications") or {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        return raw if isinstance(raw, dict) else {}
    except Exception as e:
        logging.warning("_read_notif_blob failed for %s: %s", uid, e)
        return {}


def _write_notif_blob(uid: str, blob: dict) -> bool:
    sb = _get_supabase_admin()
    if not sb or not uid:
        return False
    try:
        resp = sb.table("users").update({"notifications": blob}).eq("id", str(uid)).execute()
        return bool(getattr(resp, "data", None))
    except Exception as e:
        logging.warning("_write_notif_blob failed for %s: %s", uid, e)
        return False


def get_billing_state(uid: str) -> dict:
    p = _read_notif_blob(uid)
    return {
        "stripe_customer_id":     p.get("stripe_customer_id"),
        "stripe_subscription_id": p.get("stripe_subscription_id"),
        "billing_active":         bool(p.get("billing_active", False)),
        "stripe_status":          p.get("stripe_status"),
        "cancel_at":              p.get("cancel_at"),
        "trial_end":              p.get("trial_end"),
        "current_period_end":     p.get("current_period_end"),
    }


def set_billing_state(uid: str, **fields) -> bool:
    """Merge only the provided billing keys (None = preserve) into the blob."""
    blob = _read_notif_blob(uid)
    for k in _BILLING_KEYS:
        if k in fields and fields[k] is not None:
            blob[k] = bool(fields[k]) if k == "billing_active" else fields[k]
    return _write_notif_blob(uid, blob)


def schedule_cancellation(uid: str, cancel_at) -> bool:
    blob = _read_notif_blob(uid)
    blob["cancel_at"] = str(cancel_at)
    return _write_notif_blob(uid, blob)


def undo_cancellation(uid: str) -> bool:
    blob = _read_notif_blob(uid)
    if "cancel_at" not in blob:
        return True
    blob.pop("cancel_at", None)
    return _write_notif_blob(uid, blob)


def clear_billing_state(uid: str) -> bool:
    blob = _read_notif_blob(uid)
    for k in _BILLING_KEYS:
        blob.pop(k, None)
    return _write_notif_blob(uid, blob)


def set_plan(uid: str, plan: str) -> bool:
    sb = _get_supabase_admin()
    if not sb or not uid:
        return False
    try:
        resp = sb.table("users").update({"plan": plan}).eq("id", str(uid)).execute()
        return bool(getattr(resp, "data", None))
    except Exception as e:
        logging.warning("set_plan failed for %s: %s", uid, e)
        return False

# ── Founding membership (durable) ─────────────────────────────────────────────
FOUNDING_LIMIT = 50


def founding_spots_remaining() -> int:
    """Spots left in the first-50 window. Fails OPEN (returns the full limit) so a
    DB hiccup never blocks a legitimate free claim."""
    sb = _get_supabase_admin() or _get_supabase()
    if not sb:
        return FOUNDING_LIMIT
    try:
        r = (sb.table("users").select("id", count="exact")
             .filter("notifications->>founding_member", "eq", "true").execute())
        n = r.count if getattr(r, "count", None) is not None else len(r.data or [])
        return max(0, FOUNDING_LIMIT - int(n))
    except Exception as e:
        logging.warning("founding_spots_remaining failed: %s", e)
        return FOUNDING_LIMIT


def is_founding_member(uid: str) -> bool:
    return bool(_read_notif_blob(uid).get("founding_member"))


def claim_founding_member(uid: str) -> bool:
    """Grant free founding Pro if a spot remains. Idempotent for existing founders.
    Sets founding_member=true + plan=pro. Returns False if spots are exhausted."""
    if not uid:
        return False
    if is_founding_member(uid):
        return True
    if founding_spots_remaining() <= 0:
        return False
    blob = _read_notif_blob(uid)
    blob["founding_member"] = True
    if not _write_notif_blob(uid, blob):
        return False
    set_plan(uid, "pro")
    return True


def set_disclaimer_ack(uid: str, version: str) -> bool:
    from datetime import datetime as _dtm, timezone as _tzm
    blob = _read_notif_blob(uid)
    blob["disclaimer_ack"] = {"version": version, "at": _dtm.now(_tzm.utc).isoformat()}
    return _write_notif_blob(uid, blob)


def get_account_status(uid: str) -> dict:
    """One-read {plan, founding_member, billing_active} for the nav pill + /me."""
    out = {"plan": "free", "founding_member": False, "billing_active": False}
    sb = _get_supabase_admin() or _get_supabase()
    if not sb or not uid:
        return out
    try:
        r = (sb.table("users").select("plan,notifications").eq("id", str(uid)).limit(1).execute().data or [])
        if not r:
            return out
        blob = r[0].get("notifications") or {}
        if isinstance(blob, str):
            try:
                blob = json.loads(blob)
            except Exception:
                blob = {}
        return {"plan": (r[0].get("plan") or "free"),
                "founding_member": bool(blob.get("founding_member")),
                "billing_active": bool(blob.get("billing_active"))}
    except Exception as e:
        logging.warning("get_account_status failed for %s: %s", uid, e)
        return out


def get_admin_stats() -> dict:
    """Aggregate business metrics for the admin dashboard (counts off users)."""
    sb = _get_supabase_admin()
    out = {"founding_limit": FOUNDING_LIMIT}
    if not sb:
        return out

    def _count(q):
        try:
            return int(getattr(q.execute(), "count", 0) or 0)
        except Exception as e:
            logging.warning("admin stat failed: %s", e)
            return 0

    out["total_users"] = _count(sb.table("users").select("id", count="exact"))
    out["founding_members"] = _count(sb.table("users").select("id", count="exact")
                                     .filter("notifications->>founding_member", "eq", "true"))
    out["founding_spots_remaining"] = max(0, FOUNDING_LIMIT - out["founding_members"])
    out["pro_users"] = _count(sb.table("users").select("id", count="exact").eq("plan", "pro"))
    out["paying_subscribers"] = _count(sb.table("users").select("id", count="exact")
                                       .filter("notifications->>billing_active", "eq", "true"))
    out["email_verified"] = _count(sb.table("users").select("id", count="exact").eq("email_verified", True))
    out["mrr_estimate"] = out["paying_subscribers"] * 29
    try:
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        wk = (_dt.now(_tz.utc) - _td(days=7)).isoformat()
        out["signups_7d"] = _count(sb.table("users").select("id", count="exact").gte("created_at", wk))
    except Exception:
        pass
    return out
