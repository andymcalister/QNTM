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
