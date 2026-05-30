"""
QNTM — Nightly Data Refresh Script
====================================
Pulls live fundamentals + price data from yfinance for all 963 tickers
and writes results to Supabase signal_log table.

Run nightly via:
  - Streamlit Cloud scheduled run (set QNTM_REFRESH_MODE=1)
  - Cron job: 0 2 * * * python data_refresh.py
  - Manual: python data_refresh.py

Rate limiting: 0.25s delay between tickers → ~4 min for full 963-ticker pass.
Failed tickers fall back to universe_data.py static fundamentals silently.

Usage from app.py (to load cached scores):
  from data_refresh import load_cached_scores, get_cached_fundamentals
"""

import os, sys, time, json, hashlib, logging
from datetime import datetime, date, timedelta
from typing import Optional

# Add project root to path so universe_data imports work
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("qntm.refresh")

# ── CONFIG ────────────────────────────────────────────────────────────────────
RATE_LIMIT_DELAY   = 0.25   # seconds between yfinance calls
BATCH_SIZE         = 50     # tickers per Supabase upsert batch
MAX_RETRIES        = 2      # retry failed tickers once
STALE_HOURS        = 20     # treat cache as stale after this many hours
FUNDAMENTALS_TABLE = "fundamentals_cache"   # new table (see schema addition below)
SIGNAL_TABLE       = "signal_log"


# ── SUPABASE CLIENT ───────────────────────────────────────────────────────────

def _get_supabase():
    """Return Supabase client from env or Streamlit secrets."""
    try:
        from supabase import create_client
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")

        # Try Streamlit secrets when running inside Streamlit
        if not url:
            try:
                import streamlit as st
                url = st.secrets.get("SUPABASE_URL", "")
                key = st.secrets.get("SUPABASE_SERVICE_KEY") or st.secrets.get("SUPABASE_ANON_KEY", "")
            except Exception:
                pass

        if url and key:
            return create_client(url, key)
    except Exception as e:
        log.warning(f"Supabase unavailable: {e}")
    return None


# ── YFINANCE FUNDAMENTALS FETCH ───────────────────────────────────────────────

# Keys we want from yfinance .info and how to map them to QNTM's schema
_YFINANCE_MAP = {
    "returnOnEquity":          "roe",    # fraction → multiply by 100
    "profitMargins":           "pm",     # fraction → multiply by 100
    "revenueGrowth":           "rg",     # fraction → multiply by 100
    "earningsGrowth":          "eg",     # fraction → multiply by 100
    "forwardPE":               "fpe",    # raw
    "shortPercentOfFloat":     "sp",     # fraction → multiply by 100
    "marketCap":               "mktcap_raw",  # raw int, converted below
    "freeCashflow":            "fcf_raw",
    "totalRevenue":            "rev_raw",
    "trailingEps":             "eps",
    "fiftyTwoWeekHigh":        "w52h",
    "fiftyTwoWeekLow":         "w52l",
    "regularMarketPrice":      "price",
    "currentPrice":            "price_alt",
    "averageVolume":           "avg_vol",
    "volume":                  "cur_vol",
    "regularMarketVolume":     "mkt_vol",
}


def _safe_pct(val) -> Optional[float]:
    """Convert yfinance fractional value to percentage. Returns None on failure."""
    try:
        f = float(val)
        return round(f * 100, 2)
    except (TypeError, ValueError):
        return None


def _mktcap_bucket(raw) -> str:
    """Convert raw market cap int to QNTM bucket."""
    try:
        mc = int(raw)
        if mc >= 10_000_000_000:
            return "large"
        elif mc >= 2_000_000_000:
            return "mid"
        else:
            return "small"
    except (TypeError, ValueError):
        return "large"


def _volume_ratio(cur_vol, avg_vol) -> Optional[float]:
    """Relative volume: current / average. >1.5 = elevated, <0.5 = low."""
    try:
        ratio = float(cur_vol) / float(avg_vol)
        return round(ratio, 3)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _insider_buy_ratio(ticker_obj) -> Optional[float]:
    """
    Estimate insider buy ratio from yfinance insider_purchases DataFrame.
    Returns % of insider transactions that are buys (0-100).
    Falls back to None if data unavailable.
    """
    try:
        ip = ticker_obj.insider_purchases
        if ip is None or ip.empty:
            return None
        # yfinance returns a df with Purchases/Sales rows
        buys  = ip.loc[ip.index.str.contains("Purchase", case=False), :].values.sum()
        sales = ip.loc[ip.index.str.contains("Sale",     case=False), :].values.sum()
        total = buys + sales
        if total == 0:
            return None
        return round(buys / total * 100, 1)
    except Exception:
        return None


def fetch_ticker_fundamentals(ticker: str) -> dict:
    """
    Fetch live fundamentals for a single ticker via yfinance.
    Returns a dict matching QNTM's FUNDAMENTALS schema.
    Returns {} on any failure so caller can fall back to static data.
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info or {}

        raw = {}
        for yf_key, qntm_key in _YFINANCE_MAP.items():
            raw[qntm_key] = info.get(yf_key)

        # Convert fractional metrics to percentages
        for frac_key in ("roe", "pm", "rg", "eg", "sp"):
            if raw.get(frac_key) is not None:
                raw[frac_key] = _safe_pct(raw[frac_key])

        # Forward P/E — keep raw
        if raw.get("fpe") is not None:
            try:
                raw["fpe"] = round(float(raw["fpe"]), 1)
            except (TypeError, ValueError):
                raw["fpe"] = None

        # Market cap bucket
        raw["mktcap"] = _mktcap_bucket(raw.pop("mktcap_raw", None))

        # FCF yield: free_cash_flow / market_cap
        fcf_raw = raw.pop("fcf_raw", None)
        rev_raw = raw.pop("rev_raw", None)
        mc_raw  = info.get("marketCap")
        if fcf_raw and mc_raw:
            try:
                raw["fcf"] = round(float(fcf_raw) / float(mc_raw) * 100, 2)
            except (TypeError, ValueError, ZeroDivisionError):
                raw["fcf"] = None
        else:
            raw["fcf"] = None

        # Live price (prefer currentPrice over regularMarketPrice)
        raw["price"] = raw.get("price_alt") or raw.get("price")
        raw.pop("price_alt", None)

        # Real volume ratio (replaces the math proxy)
        cur_vol = raw.pop("cur_vol", None) or raw.pop("mkt_vol", None)
        avg_vol = raw.pop("avg_vol", None)
        raw["vol_ratio"] = _volume_ratio(cur_vol, avg_vol)
        raw["avg_vol"]   = avg_vol

        # Insider buy ratio (requires extra call — skip if slow)
        raw["ib"] = _insider_buy_ratio(t)
        if raw["ib"] is None:
            # Fall back to static or 40 (neutral)
            raw["ib"] = None

        # Beat rate — yfinance doesn't expose this directly; keep static
        raw["br"] = None

        # Clean up unused
        for drop in ("eps", "w52h", "w52l"):
            raw.pop(drop, None)

        # Remove all None values so static fallback can fill gaps
        return {k: v for k, v in raw.items() if v is not None}

    except Exception as e:
        log.debug(f"yfinance fetch failed for {ticker}: {e}")
        return {}


# ── VOLUME PILLAR — REAL SCORE ────────────────────────────────────────────────

def score_volume_pillar(vol_ratio: Optional[float], price_history: list) -> float:
    """
    Real volume pillar score using:
      - Relative volume vs 30-day average (vol_ratio)
      - On-Balance Volume direction (from price history)
      - Price-volume divergence check

    Returns 0-100 score.
    Falls back to 50 (neutral) if data unavailable.
    """
    scores = []

    # 1. Relative volume component (40% of pillar)
    if vol_ratio is not None:
        # >2.0 = very high (institutional buying), <0.3 = very low (distribution)
        if   vol_ratio >= 2.0:  rv_score = 90
        elif vol_ratio >= 1.5:  rv_score = 75
        elif vol_ratio >= 1.0:  rv_score = 55
        elif vol_ratio >= 0.5:  rv_score = 40
        else:                    rv_score = 20
        scores.append(("rv", rv_score, 0.4))

    # 2. On-Balance Volume direction (40% of pillar)
    if price_history and len(price_history) >= 10:
        prices = price_history
        # Approximate OBV direction: count up-days vs down-days in recent 20 sessions
        recent = prices[-20:]
        up_days   = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i-1])
        down_days = len(recent) - 1 - up_days
        obv_pct   = up_days / (len(recent) - 1) * 100 if len(recent) > 1 else 50
        scores.append(("obv", obv_pct, 0.4))

        # 3. Price-volume divergence (20% of pillar)
        # If price trending up AND vol_ratio > 1: confirmation → boost
        # If price trending up AND vol_ratio < 0.7: divergence → penalty
        if vol_ratio is not None:
            price_up = prices[-1] > prices[-10] if len(prices) >= 10 else True
            if price_up and vol_ratio >= 1.0:
                div_score = 70   # confirmed
            elif price_up and vol_ratio < 0.7:
                div_score = 35   # divergence
            elif not price_up and vol_ratio >= 1.5:
                div_score = 35   # selling into strength
            else:
                div_score = 50   # neutral
            scores.append(("div", div_score, 0.2))

    if not scores:
        return 50.0

    total_weight = sum(w for _, _, w in scores)
    weighted     = sum(s * w for _, s, w in scores) / total_weight
    return round(max(0.0, min(100.0, weighted)), 1)


# ── SUPABASE CACHE: WRITE ─────────────────────────────────────────────────────

def write_fundamentals_cache(ticker_data: dict) -> bool:
    """
    Upsert a batch of ticker fundamentals into Supabase fundamentals_cache table.
    ticker_data: {ticker: {roe, pm, rg, eg, fpe, sp, ib, fcf, mktcap, vol_ratio, price, ...}}
    """
    sb = _get_supabase()
    if not sb:
        log.warning("No Supabase connection — fundamentals not persisted")
        return False

    today = date.today().isoformat()
    rows  = []
    for ticker, f in ticker_data.items():
        rows.append({
            "ticker":      ticker,
            "data_date":   today,
            "fundamentals": json.dumps(f),
            "price":       f.get("price"),
            "vol_ratio":   f.get("vol_ratio"),
            "refreshed_at": datetime.utcnow().isoformat(),
        })

    # Upsert in batches
    try:
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            sb.table(FUNDAMENTALS_TABLE).upsert(
                batch, on_conflict="ticker,data_date"
            ).execute()
        log.info(f"Wrote {len(rows)} rows to {FUNDAMENTALS_TABLE}")
        return True
    except Exception as e:
        log.error(f"Supabase write failed: {e}")
        return False


def write_signal_snapshot(scored_list: list) -> bool:
    """
    Write today's scored universe to signal_log for historical tracking
    and so the app can read pre-computed scores instead of scanning live.
    """
    sb = _get_supabase()
    if not sb:
        return False

    today = date.today().isoformat()
    rows  = []
    for s in scored_list:
        rows.append({
            "ticker":        s["ticker"],
            "signal_date":   today,
            "composite":     s.get("composite"),
            "momentum":      s.get("momentum"),
            "quality":       s.get("quality"),
            "volume":        s.get("volume"),
            "value":         s.get("value"),
            "sentiment":     s.get("sentiment"),
            "signal":        s.get("signal"),
            "macro_overlay": s.get("macro_overlay"),
            "adj_composite": s.get("adj_composite"),
            "price":         s.get("price"),
            "is_hidden_gem": s.get("is_hidden_gem", False),
            "hidden_gem_reason": (
                ", ".join(s.get("gem_reasons", [])) if s.get("gem_reasons") else None
            ),
        })

    try:
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            sb.table(SIGNAL_TABLE).upsert(
                batch, on_conflict="ticker,signal_date"
            ).execute()
        log.info(f"Wrote {len(rows)} signal rows to {SIGNAL_TABLE}")
        return True
    except Exception as e:
        log.error(f"Signal snapshot write failed: {e}")
        return False


def publish_signal_batch(scored_list: list, signal_date: str = None) -> Optional[str]:
    """
    ATOMIC, SIMULTANEOUS PUBLISH (compliance Part 1).

    Commits the entire day's signal batch in a SINGLE database transaction via
    the `publish_signal_batch` Postgres RPC (see migrations/atomic_publishing.sql).
    Either the whole new batch becomes visible at once, or — on any failure —
    nothing changes and the prior batch stays live. No partial/mixed state, and
    no per-user staggering: every reader of signal_log flips to the new batch at
    the same published_at instant.

    Also writes the append-only audit row (batch_id, published_at, ticker list,
    signal values, content hash) inside the same transaction as the evidence of
    when each signal became public.

    Returns the published_at ISO timestamp on success, else None.

    FLAG FOR ATTORNEY REVIEW before taking paying users.
    """
    import uuid

    sb = _get_supabase()
    if not sb:
        return False if False else None

    sig_date = signal_date or date.today().isoformat()
    batch_id = str(uuid.uuid4())

    rows = []
    for s in scored_list:
        rows.append({
            "ticker":        s["ticker"],
            "composite":     s.get("composite"),
            "momentum":      s.get("momentum"),
            "quality":       s.get("quality"),
            "volume":        s.get("volume"),
            "value":         s.get("value"),
            "sentiment":     s.get("sentiment"),
            "signal":        s.get("signal"),
            "macro_overlay": s.get("macro_overlay"),
            "adj_composite": s.get("adj_composite"),
            "price":         s.get("price"),
            "is_hidden_gem": s.get("is_hidden_gem", False),
            "hidden_gem_reason": (
                ", ".join(s.get("gem_reasons", [])) if s.get("gem_reasons") else None
            ),
        })

    # Canonical content hash of the batch (stable key ordering) — the integrity
    # fingerprint stored in the audit log.
    canonical = json.dumps(
        sorted(
            [{"t": r["ticker"], "a": r["adj_composite"], "s": r["signal"]} for r in rows],
            key=lambda x: x["t"],
        ),
        separators=(",", ":"), sort_keys=True,
    )
    content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    try:
        resp = sb.rpc("publish_signal_batch", {
            "p_batch_id":     batch_id,
            "p_signal_date":  sig_date,
            "p_rows":         rows,
            "p_content_hash": content_hash,
        }).execute()
        published_at = resp.data if isinstance(resp.data, str) else None
        # Out-of-band leakage guard (Part 1 #6): only log new signal values AFTER
        # the public commit and after published_at is set.
        log.info(f"Published batch {batch_id} ({len(rows)} signals) at {published_at}")
        return published_at or batch_id
    except Exception as e:
        log.error(f"Atomic publish failed (rolled back, prior batch still live): {e}")
        return None


# ── SUPABASE CACHE: READ ──────────────────────────────────────────────────────

def load_cached_fundamentals(max_age_hours: int = STALE_HOURS) -> dict:
    """
    Load today's fundamentals from Supabase fundamentals_cache.
    Returns {ticker: fundamentals_dict} or {} if unavailable/stale.
    """
    sb = _get_supabase()
    if not sb:
        return {}

    try:
        cutoff = (datetime.utcnow() - timedelta(hours=max_age_hours)).isoformat()
        resp   = sb.table(FUNDAMENTALS_TABLE).select(
            "ticker,fundamentals,refreshed_at"
        ).gte("refreshed_at", cutoff).execute()

        result = {}
        for row in (resp.data or []):
            ticker = row["ticker"]
            try:
                result[ticker] = json.loads(row["fundamentals"])
            except Exception:
                pass

        log.info(f"Loaded {len(result)} cached fundamentals from Supabase")
        return result
    except Exception as e:
        log.warning(f"Could not load fundamentals cache: {e}")
        return {}


def load_cached_scores(max_age_hours: int = STALE_HOURS) -> list:
    """
    Load today's pre-computed scores from signal_log.
    Returns list of score dicts (same format as run_full_scan) or [].
    """
    sb = _get_supabase()
    if not sb:
        return []

    try:
        today  = date.today().isoformat()
        cutoff = (datetime.utcnow() - timedelta(hours=max_age_hours)).isoformat()
        resp   = sb.table(SIGNAL_TABLE).select("*").eq(
            "signal_date", today
        ).gte("created_at", cutoff).execute()

        scores = []
        for row in (resp.data or []):
            scores.append({
                "ticker":        row["ticker"],
                "sector":        row.get("sector", "Unknown"),
                "composite":     float(row["composite"] or 50),
                "momentum":      float(row["momentum"]  or 50),
                "quality":       float(row["quality"]   or 50),
                "volume":        float(row["volume"]    or 50),
                "value":         float(row["value"]     or 50),
                "sentiment":     float(row["sentiment"] or 50),
                "signal":        row.get("signal", "MODERATE"),
                "macro_overlay": float(row["macro_overlay"] or 0),
                "adj_composite": float(row["adj_composite"] or 50),
                "price":         float(row["price"]) if row.get("price") else None,
                "is_hidden_gem": row.get("is_hidden_gem", False),
                "has_live_price": True,
            })

        if scores:
            log.info(f"Loaded {len(scores)} cached scores from signal_log")
        return scores
    except Exception as e:
        log.warning(f"Could not load cached scores: {e}")
        return []


def update_model_portfolio(scored_list: list) -> None:
    """
    Model portfolio maintenance — runs nightly AND intraday.

    Strategy:
    - Target: 50 positions, $2,000 equal weight ($100K total)
    - Entry:  adj_composite >= 60 (High Conviction)
    - Hold:   by default — no action while score stays >= 45
    - Exit:   adj_composite < 45 (conviction collapsed) → sell, log exit
    - Reinvest: immediately look for next High Conviction stock not held,
                respecting 30% sector cap (max 15 per sector).
                If none available, slot stays open — filled on next refresh
                that finds a qualifying stock.
    - Sector cap: max 30% of portfolio (15/50) in any one sector at entry time.
                  Existing positions are never force-exited for sector reasons —
                  only new entries are blocked.
    """
    sb = _get_supabase()
    if not sb:
        log.warning("[MODEL PORTFOLIO] No Supabase — skipping")
        return

    try:
        from universe_data import SECTORS as _SECTORS
    except Exception:
        _SECTORS = {}

    try:
        today     = date.today().isoformat()
        POS_SIZE  = 2000.0
        TARGET    = 50
        SECT_CAP  = 15   # 30% of 50

        score_map = {r["ticker"]: r for r in scored_list}

        # ── Load active positions ─────────────────────────────────────────────
        active_resp = sb.table("model_portfolio_positions") \
            .select("id,ticker,entry_date,entry_price,entry_score") \
            .eq("is_active", True) \
            .execute()
        active         = active_resp.data or []
        active_tickers = {p["ticker"] for p in active}

        # ── Build current sector counts from active positions ─────────────────
        sector_counts: dict = {}
        for p in active:
            sec = _SECTORS.get(p["ticker"], "Unknown")
            sector_counts[sec] = sector_counts.get(sec, 0) + 1

        # ── Step 1: Exit any position whose conviction has collapsed ──────────
        exited = []
        for pos in active:
            tk     = pos["ticker"]
            sc     = score_map.get(tk)
            if not sc:
                continue
            adj = float(sc.get("adj_composite", sc.get("composite", 50)) or 50)
            if adj < 45:
                sb.table("model_portfolio_positions").update({
                    "is_active":   False,
                    "exit_date":   today,
                    "exit_price":  sc.get("price"),
                    "exit_score":  round(adj, 1),
                    "exit_reason": "SELL_SIGNAL",
                }).eq("id", pos["id"]).execute()
                exited.append(tk)
                active_tickers.discard(tk)
                # Reduce sector count for exited position
                sec = _SECTORS.get(tk, "Unknown")
                sector_counts[sec] = max(0, sector_counts.get(sec, 1) - 1)
                log.info(f"[MODEL PORTFOLIO] EXIT {tk} score={adj:.1f} — conviction collapsed")

        # ── Step 2: Fill open slots up to TARGET ─────────────────────────────
        slots_needed = TARGET - len(active_tickers)
        if slots_needed <= 0:
            log.info(f"[MODEL PORTFOLIO] Full ({len(active_tickers)}/{TARGET}) — "
                     f"{len(exited)} exited this run")
            return

        # Rank all High Conviction stocks not already held
        candidates = sorted(
            [r for r in scored_list
             if float(r.get("adj_composite", r.get("composite", 0)) or 0) >= 60
             and r["ticker"] not in active_tickers
             and r.get("price")],
            key=lambda x: float(x.get("adj_composite", x.get("composite", 0)) or 0),
            reverse=True
        )

        entered = []
        skipped_cap = 0
        for r in candidates:
            if len(entered) >= slots_needed:
                break
            tk  = r["ticker"]
            sec = _SECTORS.get(tk, "Unknown")

            # Enforce 30% sector cap on new entries only
            if sector_counts.get(sec, 0) >= SECT_CAP:
                skipped_cap += 1
                continue

            adj = float(r.get("adj_composite", r.get("composite", 60)) or 60)
            sb.table("model_portfolio_positions").insert({
                "ticker":        tk,
                "entry_date":    today,
                "entry_price":   r.get("price"),
                "entry_score":   round(adj, 1),
                "position_size": POS_SIZE,
                "is_active":     True,
            }).execute()
            sector_counts[sec] = sector_counts.get(sec, 0) + 1
            active_tickers.add(tk)
            entered.append(tk)
            log.info(f"[MODEL PORTFOLIO] ENTER {tk} ({sec}) @ ${r.get('price')} score={adj:.1f}")

        remaining_open = slots_needed - len(entered)
        log.info(
            f"[MODEL PORTFOLIO] Run complete — "
            f"{len(exited)} exited, {len(entered)} entered, "
            f"{len(active_tickers)} active/{TARGET} target, "
            f"{remaining_open} slots open (waiting for conviction), "
            f"{skipped_cap} blocked by sector cap"
        )

    except Exception as e:
        log.error(f"[MODEL PORTFOLIO] Update failed: {e}")


def cache_is_fresh(max_age_hours: int = STALE_HOURS) -> bool:
    """Quick check: does today's cache exist and is it recent enough?"""
    sb = _get_supabase()
    if not sb:
        return False
    try:
        cutoff = (datetime.utcnow() - timedelta(hours=max_age_hours)).isoformat()
        resp   = sb.table(SIGNAL_TABLE).select("ticker").eq(
            "signal_date", date.today().isoformat()
        ).gte("created_at", cutoff).limit(1).execute()
        return bool(resp.data)
    except Exception:
        return False


# ── MAIN REFRESH LOOP ─────────────────────────────────────────────────────────

def run_refresh(tickers: list = None, force: bool = False) -> dict:
    """
    Full nightly refresh:
      1. Skip if cache is fresh and force=False
      2. Fetch yfinance fundamentals for all tickers (rate-limited)
      3. Merge with static fallback for any failed tickers
      4. Write to Supabase fundamentals_cache
      5. Run model scoring with live data
      6. Write scored universe to signal_log
      7. Return summary stats

    Args:
        tickers: list of tickers to refresh (defaults to full universe)
        force:   bypass freshness check

    Returns:
        dict with keys: success, live_count, static_count, total, duration_s
    """
    from universe_data import SECTORS, FUNDAMENTALS

    if tickers is None:
        tickers = list(SECTORS.keys())

    if not force and cache_is_fresh():
        log.info("Cache is fresh — skipping refresh. Use force=True to override.")
        return {"success": True, "skipped": True, "reason": "cache_fresh"}

    log.info(f"Starting refresh for {len(tickers)} tickers")
    start = time.time()

    live_data    = {}
    static_used  = []
    failed       = []

    for i, ticker in enumerate(tickers):
        if i > 0 and i % 100 == 0:
            log.info(f"Progress: {i}/{len(tickers)} ({i/len(tickers)*100:.0f}%)")

        # Fetch live
        data = fetch_ticker_fundamentals(ticker)

        if data:
            # Merge: live data takes precedence, static fills gaps
            static = FUNDAMENTALS.get(ticker, {})
            merged = {**static, **data}   # live overwrites static
            live_data[ticker] = merged
        else:
            # Live fetch failed — use static only
            static_used.append(ticker)
            live_data[ticker] = FUNDAMENTALS.get(ticker, {})

        time.sleep(RATE_LIMIT_DELAY)

    # Retry failed tickers once
    retried = 0
    for ticker in failed[:MAX_RETRIES * 10]:
        data = fetch_ticker_fundamentals(ticker)
        if data:
            static = FUNDAMENTALS.get(ticker, {})
            live_data[ticker] = {**static, **data}
            static_used.remove(ticker) if ticker in static_used else None
            retried += 1
        time.sleep(RATE_LIMIT_DELAY * 2)

    log.info(f"Fetch complete: {len(tickers) - len(static_used)} live, {len(static_used)} static fallback")

    # Write fundamentals cache
    write_fundamentals_cache(live_data)

    # Score the universe with fresh data
    try:
        from model_engine import score_stock, apply_macro_overlay, fetch_macro_overlay
        import yfinance as yf

        # Fetch price histories (batched — yf.download is more efficient)
        log.info("Fetching price histories via yf.download...")
        try:
            import pandas as pd
            chunk_size = 200
            price_histories = {}
            for ci in range(0, len(tickers), chunk_size):
                chunk = tickers[ci:ci + chunk_size]
                hist  = yf.download(
                    chunk, period="1y", auto_adjust=True, progress=False, threads=True
                )
                if "Close" in hist.columns:
                    close = hist["Close"]
                    for tk in chunk:
                        if tk in close.columns:
                            vals = close[tk].dropna().tolist()
                            if vals:
                                price_histories[tk] = vals
                time.sleep(1)
            log.info(f"Price histories fetched for {len(price_histories)} tickers")
        except Exception as e:
            log.warning(f"Batch price download failed, scoring without history: {e}")
            price_histories = {}

        # Score with live fundamentals injected
        scores = []
        for ticker in tickers:
            hist   = price_histories.get(ticker, [])
            f      = live_data.get(ticker, {})
            vol_ratio = f.get("vol_ratio")

            s = score_stock(ticker, hist, live_fundamentals=f, vol_ratio=vol_ratio)
            s["has_live_price"] = len(hist) > 0
            scores.append(s)

        # Cross-sectional percentile ranking
        composites = [s["composite"] for s in scores]
        for s in scores:
            rank = sum(1 for c in composites if c <= s["composite"]) / len(composites) * 100
            s["pct_rank"] = round(rank, 1)

        scores.sort(key=lambda x: x["composite"], reverse=True)

        # Apply live macro overlay
        macro = fetch_macro_overlay(use_live_feeds=True)
        scored = apply_macro_overlay(scores, macro)

        # Write to signal_log
        write_signal_snapshot(scored)

        # Update model portfolio positions
        update_model_portfolio(scored)

        duration = round(time.time() - start, 1)
        log.info(f"Refresh complete in {duration}s")

        return {
            "success":       True,
            "live_count":    len(tickers) - len(static_used),
            "static_count":  len(static_used),
            "total":         len(tickers),
            "duration_s":    duration,
            "macro_regime":  macro.get("regime"),
            "macro_source":  macro.get("source"),
        }

    except Exception as e:
        log.error(f"Scoring phase failed: {e}")
        return {
            "success":      False,
            "error":        str(e),
            "live_count":   len(tickers) - len(static_used),
            "static_count": len(static_used),
            "total":        len(tickers),
        }


# ── SCHEMA ADDITION (run once in Supabase SQL editor) ─────────────────────────
SCHEMA_SQL = """
-- Add fundamentals_cache table (run once in Supabase SQL editor)
-- Stores refreshed fundamentals per ticker per day

CREATE TABLE IF NOT EXISTS public.fundamentals_cache (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker        TEXT NOT NULL,
    data_date     DATE NOT NULL DEFAULT CURRENT_DATE,
    fundamentals  JSONB NOT NULL,
    price         NUMERIC(12,4),
    vol_ratio     NUMERIC(8,4),
    refreshed_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(ticker, data_date)
);

-- No RLS needed — this is model data, not user data
-- Public read so the app can query it via anon key
CREATE POLICY "Fundamentals public read" ON public.fundamentals_cache
    FOR SELECT USING (true);

ALTER TABLE public.fundamentals_cache ENABLE ROW LEVEL SECURITY;

-- Index for fast date-filtered lookups
CREATE INDEX IF NOT EXISTS idx_fundamentals_cache_date
    ON public.fundamentals_cache(data_date, refreshed_at);
"""


# ── INTRADAY PRICE REFRESH ────────────────────────────────────────────────────

def run_intraday_refresh(tickers: list = None) -> dict:
    """
    Lightweight intraday refresh — updates price + momentum scores only.
    Runs every 15 minutes during US market hours (9:30 AM–4:45 PM ET, Mon–Fri).
    Skips fundamental re-fetch and full model re-score to stay within rate limits.
    Writes updated price to signal_log for today's date (upserts).
    """
    import yfinance as yf
    from universe_data import SECTORS

    if tickers is None:
        tickers = list(SECTORS.keys())

    log.info(f"Intraday refresh: updating prices for {len(tickers)} tickers")
    start = time.time()
    sb = _get_supabase()
    if not sb:
        return {"success": False, "error": "No Supabase connection"}

    today = date.today().isoformat()
    updated = 0
    failed  = 0

    # Fetch current prices in batches of 200
    chunk_size = 200
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        try:
            hist = yf.download(chunk, period="2d", auto_adjust=True, progress=False, threads=True)
            if hist.empty:
                log.warning(f"Intraday batch {i}: empty response from yfinance")
                continue
            rows = []
            # Handle both single-ticker (Series) and multi-ticker (MultiIndex DataFrame)
            if "Close" in hist.columns:
                close = hist["Close"]
                if hasattr(close, "columns"):
                    # MultiIndex — multiple tickers
                    for tk in chunk:
                        if tk in close.columns:
                            vals = close[tk].dropna()
                            if not vals.empty:
                                price = round(float(vals.iloc[-1]), 4)
                                rows.append({"ticker": tk, "signal_date": today, "price": price})
                else:
                    # Single ticker — close is a Series
                    vals = close.dropna()
                    if not vals.empty and len(chunk) == 1:
                        price = round(float(vals.iloc[-1]), 4)
                        rows.append({"ticker": chunk[0], "signal_date": today, "price": price})
            elif hasattr(hist.columns, "levels"):
                # MultiIndex columns — ("Close", "AAPL") format
                for tk in chunk:
                    try:
                        vals = hist["Close"][tk].dropna()
                        if not vals.empty:
                            price = round(float(vals.iloc[-1]), 4)
                            rows.append({"ticker": tk, "signal_date": today, "price": price})
                    except Exception:
                        pass

            if rows:
                sb.table("signal_log").upsert(
                    rows, on_conflict="ticker,signal_date"
                ).execute()
                updated += len(rows)
                log.info(f"Intraday batch {i}: updated {len(rows)} prices")
            else:
                log.warning(f"Intraday batch {i}: no prices extracted from response")
        except Exception as e:
            log.warning(f"Intraday batch {i} failed: {e}")
            failed += len(chunk)
        time.sleep(0.5)

    duration = round(time.time() - start, 1)
    log.info(f"Intraday refresh complete: {updated} prices updated in {duration}s")

    # Touch fundamentals_cache.refreshed_at so the app pill shows intraday time
    if sb and updated > 0:
        try:
            sb.table("fundamentals_cache").upsert(
                {"ticker": "_intraday_sentinel", "data_date": date.today().isoformat(),
                 "refreshed_at": datetime.utcnow().isoformat(),
                 "fundamentals": "{}", "price": None, "vol_ratio": None},
                on_conflict="ticker,data_date"
            ).execute()
        except Exception:
            pass  # non-critical

    # ── Model portfolio maintenance (exits + fills) ───────────────────────────
    # Load today's scored universe from signal_log and run portfolio logic.
    # This catches intraday conviction drops (exits) and new entries.
    try:
        today_str = date.today().isoformat()
        sig_resp = sb.table("signal_log") \
            .select("ticker,adj_composite,composite,price,momentum,quality,volume,value,sentiment") \
            .eq("signal_date", today_str) \
            .execute()
        if sig_resp.data:
            # Apply macro overlay to get fresh adj_composite scores
            try:
                from model_engine import apply_macro_overlay, fetch_macro_overlay
                macro = fetch_macro_overlay(use_live_feeds=False)
                scored_today = apply_macro_overlay(sig_resp.data, macro)
            except Exception:
                scored_today = sig_resp.data  # use raw if overlay fails
            update_model_portfolio(scored_today)
        else:
            log.info("[MODEL PORTFOLIO] No signal_log data for today — skipping intraday portfolio update")
    except Exception as e:
        log.warning(f"[MODEL PORTFOLIO] Intraday update failed: {e}")

    if updated == 0 and failed == len(tickers):
        return {"success": False, "error": f"All {failed} batches failed", "updated": 0, "duration_s": duration}
    return {"success": True, "updated": updated, "failed": failed, "duration_s": duration, "mode": "intraday"}


# ── ENTRYPOINT ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="QNTM Nightly Data Refresh")
    parser.add_argument("--force",    action="store_true", help="Bypass freshness check")
    parser.add_argument("--intraday", action="store_true", help="Run lightweight intraday price refresh only")
    parser.add_argument("--tickers",  nargs="*",           help="Specific tickers to refresh")
    parser.add_argument("--schema",   action="store_true", help="Print schema SQL and exit")
    args = parser.parse_args()

    if args.schema:
        print(SCHEMA_SQL)
        sys.exit(0)

    # Respect INTRADAY_RUN env var (set by GitHub Actions intraday cron)
    import os
    is_intraday = args.intraday or os.getenv("INTRADAY_RUN", "false").lower() == "true"

    if is_intraday:
        result = run_intraday_refresh(tickers=args.tickers)
    else:
        result = run_refresh(tickers=args.tickers, force=args.force)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("success") else 1)
