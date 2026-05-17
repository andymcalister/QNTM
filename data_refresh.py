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


# ── ENTRYPOINT ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="QNTM Nightly Data Refresh")
    parser.add_argument("--force",   action="store_true", help="Bypass freshness check")
    parser.add_argument("--tickers", nargs="*",           help="Specific tickers to refresh")
    parser.add_argument("--schema",  action="store_true", help="Print schema SQL and exit")
    args = parser.parse_args()

    if args.schema:
        print(SCHEMA_SQL)
        sys.exit(0)

    result = run_refresh(tickers=args.tickers, force=args.force)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("success") else 1)
