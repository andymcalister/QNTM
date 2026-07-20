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
from datetime import datetime, date, timedelta, timezone
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
BENCHMARK_TABLE    = "benchmark_price"      # SPY daily close for the Model Portfolio equity curve
MACRO_STATE_TABLE  = "macro_state"          # single-row live macro overlay (see schema below)


# ── SUPABASE CLIENT ───────────────────────────────────────────────────────────

_SB_SINGLETON = None

def _get_supabase():
    """Return a cached Supabase client (service key preferred), created once per
    process. Memoized so the Streamlit app doesn't create a new client on every
    rerun — it was being called many times per page load. Harmless in the cron
    processes too (one client per short-lived run)."""
    global _SB_SINGLETON
    if _SB_SINGLETON is not None:
        return _SB_SINGLETON
    try:
        from supabase import create_client
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")

        # Fall back to Streamlit secrets ONLY for whichever piece is still missing.
        # Critically, do NOT re-read the key from secrets if an env key was already
        # provided — otherwise exporting SUPABASE_SERVICE_KEY without SUPABASE_URL
        # silently clobbers it with the anon key in secrets.toml and every write
        # RLS-fails while the run still reports success.
        if not url or not key:
            try:
                import streamlit as st
                if not url:
                    url = st.secrets.get("SUPABASE_URL", "")
                if not key:
                    key = st.secrets.get("SUPABASE_SERVICE_KEY") or st.secrets.get("SUPABASE_ANON_KEY", "")
            except Exception:
                pass

        if url and key:
            _SB_SINGLETON = create_client(url, key)
            return _SB_SINGLETON
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
    "priceToSalesTrailing12Months": "ps",   # raw — for valuation_history
    "priceToBook":             "pb",     # raw — for valuation_history
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


def _write_macro_state(macro: dict) -> bool:
    """
    Persist the latest macro overlay so every reader (intraday pass, app banner,
    next macro pass) shares one source of truth. Stored json-encoded to match the
    fundamentals_cache convention.
    """
    sb = _get_supabase()
    if not sb:
        return False
    try:
        sb.table(MACRO_STATE_TABLE).upsert(
            {"id": 1,
             "overlay":    json.dumps(macro),
             "updated_at": datetime.utcnow().isoformat()},
            on_conflict="id"
        ).execute()
        return True
    except Exception as e:
        log.warning(f"macro_state write failed: {e}")
        return False


def _load_macro_state() -> dict:
    """Read the latest persisted macro overlay. Returns {} if unavailable/empty."""
    sb = _get_supabase()
    if not sb:
        return {}
    try:
        resp = sb.table(MACRO_STATE_TABLE).select("overlay").eq("id", 1).limit(1).execute()
        if resp.data:
            return json.loads(resp.data[0]["overlay"])
    except Exception:
        pass
    return {}


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
            "mktcap":        s.get("mktcap"),   # size bucket for the gem gate
            "is_hidden_gem": s.get("is_hidden_gem", False),
            "hidden_gem_reason": (
                ", ".join(s.get("gem_reasons", [])) if s.get("gem_reasons") else None
            ),
            # QNTM Valuation Range (descriptive valuation context, not a target)
            "val_low":        s.get("val_low"),
            "val_high":       s.get("val_high"),
            "value_position": s.get("value_position"),
            "val_basis":      s.get("val_basis"),
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


def write_valuation_history(live_data: dict) -> bool:
    """
    Snapshot today's raw valuation multiples (fpe / ps / pb) per ticker into
    valuation_history. This table accrues over time so that, after a few months,
    each name has a real distribution of its own multiples — enabling a
    history-percentile component in the Valuation Range anchor later (today the
    anchor is peer-relative only, since no multiple history existed at launch).
    Best-effort and non-fatal: a failure here never blocks the signal write.
    """
    sb = _get_supabase()
    if not sb:
        return False
    today = date.today().isoformat()

    def _num(x):
        try:
            x = float(x)
            # Reject NaN (x != x) AND infinities — neither is JSON-compliant and
            # yfinance returns inf for some multiples (e.g. div-by-zero book value).
            if x != x or x in (float("inf"), float("-inf")):
                return None
            return round(x, 3)
        except (TypeError, ValueError):
            return None

    rows = []
    for tk, f in (live_data or {}).items():
        fpe, ps, pb = _num(f.get("fpe")), _num(f.get("ps")), _num(f.get("pb"))
        if fpe is None and ps is None and pb is None:
            continue
        rows.append({"ticker": tk, "snapshot_date": today,
                     "fpe": fpe, "ps": ps, "pb": pb})
    if not rows:
        return False
    try:
        for i in range(0, len(rows), BATCH_SIZE):
            sb.table("valuation_history").upsert(
                rows[i:i + BATCH_SIZE], on_conflict="ticker,snapshot_date"
            ).execute()
        log.info(f"Wrote {len(rows)} rows to valuation_history")
        return True
    except Exception as e:
        log.warning(f"valuation_history write failed (non-fatal): {e}")
        return False


def _capture_extra_benchmarks(sb, yf) -> None:
    """Best-effort daily RSP + QQQ close onto today's benchmark_price row."""
    today = date.today().isoformat()
    for ticker, col in [("RSP", "rsp_close"), ("QQQ", "qqq_close")]:
        try:
            dl = yf.download(ticker, period="1d", auto_adjust=True, progress=False)
            if dl is None or dl.empty or "Close" not in dl:
                continue
            c = dl["Close"]
            if hasattr(c, "columns"):
                c = c[ticker] if ticker in c.columns else c.iloc[:, 0]
            c = c.ffill()
            px = float(c.iloc[-1])
            if px != px or px <= 0:
                continue
            sb.table(BENCHMARK_TABLE).update({col: round(px, 4)}).eq("d", today).execute()
            log.info(f"benchmark_price: {ticker} {px:.2f} @ {today}")
        except Exception as e:
            log.warning(f"{ticker} capture failed: {e}")


def update_benchmark_price() -> bool:
    """Append/refresh today's SPY close to benchmark_price so the Model Portfolio
    equity curve can be rebuilt entirely from stored data — no live SPY pull on
    the page. One cheap fetch, off the request path. Non-critical: on failure the
    page simply falls back to its live SPY download."""
    sb = _get_supabase()
    if not sb:
        return False
    try:
        import yfinance as yf
        # period="1d" tracks the live session (mirrors the app's old _live_quotes);
        # the previous "5d" took the last DAILY bar, which yfinance serves sticky/
        # delayed intraday and left stored SPY ~$5 under the real price all session.
        dl = yf.download("SPY", period="1d", auto_adjust=True, progress=False)
        if dl is None or dl.empty or "Close" not in dl:
            return False
        close = dl["Close"]
        # Newer yfinance returns Close as a one-column DataFrame for a single
        # ticker; collapse to a Series so iloc[-1] is a scalar.
        if hasattr(close, "columns"):
            close = close["SPY"] if "SPY" in close.columns else close.iloc[:, 0]
        close = close.ffill()
        px = float(close.iloc[-1])
        if px != px or px <= 0:
            return False
        sb.table(BENCHMARK_TABLE).upsert(
            {"d": date.today().isoformat(), "close": px,
             "updated_at": datetime.now(timezone.utc).isoformat()},
            on_conflict="d"
        ).execute()
        log.info(f"benchmark_price: SPY {px:.2f} @ {date.today().isoformat()}")
        try:
            _capture_extra_benchmarks(sb, yf)
        except Exception as _e:
            log.warning(f"extra benchmark capture failed: {_e}")
        return True
    except Exception as e:
        log.error(f"benchmark_price update failed: {e}")
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
            # Keep in sync with write_signal_snapshot. NOTE: this atomic path
            # writes via the publish_signal_batch Postgres RPC — for mktcap to
            # land, add the column to that function's INSERT in
            # migrations/atomic_publishing.sql before switching the live path
            # over to this writer. (Dormant today; run_refresh uses
            # write_signal_snapshot, which already persists mktcap.)
            "mktcap":        s.get("mktcap"),
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

def _fetch_all_rows(build_query, page_size: int = 1000) -> list:
    """Fetch EVERY row from a Supabase query, paging around the API's default
    row cap (hosted Supabase truncates an un-ranged .select() at ~1000 rows —
    which silently broke full-universe reads once the universe passed 1,000).
    `build_query` is a callable returning a FRESH query builder WITHOUT .range();
    it's re-invoked per page. Returns the concatenated list of row dicts."""
    rows, offset = [], 0
    while True:
        resp = build_query().range(offset, offset + page_size - 1).execute()
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


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
        rows = _fetch_all_rows(lambda: sb.table(FUNDAMENTALS_TABLE).select(
            "ticker,fundamentals,refreshed_at"
        ).gte("refreshed_at", cutoff))

        result = {}
        for row in rows:
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
        _rows  = _fetch_all_rows(lambda: sb.table(SIGNAL_TABLE).select("*").eq(
            "signal_date", today
        ).gte("created_at", cutoff))

        scores = []
        for row in _rows:
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
                "mktcap":        row.get("mktcap"),   # size bucket for the gem gate
                "is_hidden_gem": row.get("is_hidden_gem", False),
                "has_live_price": True,
            })

        if scores:
            log.info(f"Loaded {len(scores)} cached scores from signal_log")
        return scores
    except Exception as e:
        log.warning(f"Could not load cached scores: {e}")
        return []


def _entry_val_pos(r):
    """Position of price within a stock's valuation range, 0-100 (low = cheap).
    Prefers live price vs the stored band; falls back to stored value_position;
    None when the row carries no usable range (val_basis 'na')."""
    if (r.get("val_basis") or "na") == "na":
        return None
    lo, hi, pr = r.get("val_low"), r.get("val_high"), r.get("price")
    try:
        lo, hi = float(lo), float(hi)
        if pr is not None and hi > lo:
            return max(0.0, min(100.0, (float(pr) - lo) / (hi - lo) * 100.0))
    except (TypeError, ValueError):
        pass
    vp = r.get("value_position")
    try:
        return max(0.0, min(100.0, float(vp))) if vp is not None else None
    except (TypeError, ValueError):
        return None


# Model-portfolio entry blend — mirrors the screener Top-10 logic: conviction is
# the primary driver, valuation position adds a real tilt. When a slot opens we
# fill it with the highest-conviction stock that is ALSO trading cheap in its
# range, rather than the highest raw score regardless of price. The High
# Conviction gate (>=60) is unchanged — the blend only reorders WITHIN the
# eligible pool. Names with no valuation range get a neutral 50.
_ENTRY_CONV_W, _ENTRY_VALUE_W = 0.65, 0.35


def _entry_blend_score(r):
    """Higher = better model-portfolio entrant: high conviction AND cheap."""
    conv = float(r.get("adj_composite", r.get("composite", 0)) or 0)
    vp = _entry_val_pos(r)
    cheap = (100.0 - vp) if vp is not None else 50.0
    return _ENTRY_CONV_W * conv + _ENTRY_VALUE_W * cheap


def update_model_portfolio(scored_list: list) -> None:
    """
    Model portfolio maintenance — runs nightly AND intraday.

    Strategy:
    - Target: 50 positions, $2,000 equal weight ($100K total)
    - Entry:  rounded adj_composite >= 65 (High Conviction; was 60)
    - Hold:   by default — no action while rounded score stays >= 56
    - Exit:   rounded adj_composite <= 55 (conviction collapsed; was <45) → sell, log exit
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

    # Market-session gate — never enter/exit when the market was closed. The cron
    # runs daily; on a closed day prices are re-stamped from the prior session
    # while scores still drift (macro recomputes), which fired phantom trades
    # (HST Sat 2026-07-18, BORR Sat 2026-05-30).
    from market_calendar import is_trading_day as _is_trading_day, why_closed as _why_closed
    if not _is_trading_day():
        log.warning("[MODEL PORTFOLIO] Market closed (%s) — no exits or entries." % _why_closed())
        return

    # Macro-applied gate - never trade on scores the overlay never touched.
    # A silent all-zero overlay (degraded-feed guard tripping before the
    # signal_log rescore) leaves adj_composite == composite universe-wide.
    try:
        _n_adj = 0
        _n_chk = 0
        for _r in (scored_list or []):
            _c = _r.get("composite")
            _a = _r.get("adj_composite")
            if _c is None or _a is None:
                continue
            _n_chk += 1
            if abs(float(_a) - float(_c)) > 1e-9:
                _n_adj += 1
        if _n_chk >= 100 and _n_adj == 0:
            log.error(
                "[MODEL PORTFOLIO] Macro overlay NOT APPLIED - adj_composite == "
                "composite for all %d scored names. Entries would clear the bar "
                "without the macro haircut and exits would run unadjusted. "
                "No exits or entries this run." % _n_chk
            )
            return
    except Exception as _e:
        log.warning("[MODEL PORTFOLIO] macro-applied gate check failed: %r" % (_e,))
    try:
        from universe_data import SECTORS as _SECTORS, sector_of as _sector_of
    except Exception:
        _SECTORS = {}
        def _sector_of(t): return "Unknown"
    from conviction import is_entry as _is_entry, is_exit as _is_exit

    try:
        today     = date.today().isoformat()
        POS_SIZE  = 2000.0
        TARGET    = 50
        SECT_CAP  = 15   # 30% of 50

        score_map = {r["ticker"]: r for r in scored_list}

        # ── Load active positions ─────────────────────────────────────────────
        try:
            from model_engine import MODEL_EPOCH as _EPOCH
        except Exception:
            _EPOCH = "live"
        active_resp = sb.table("model_portfolio_positions") \
            .select("id,ticker,entry_date,entry_price,entry_score") \
            .eq("is_active", True) \
            .eq("epoch", _EPOCH) \
            .execute()
        active         = active_resp.data or []
        active_tickers = {p["ticker"] for p in active}

        # ── Build current sector counts from active positions ─────────────────
        sector_counts: dict = {}
        for p in active:
            sec = _sector_of(p["ticker"])
            sector_counts[sec] = sector_counts.get(sec, 0) + 1

        # ── Run-health gate — never act on a degraded/garbage scoring run ─────
        #    A broken data or macro pass reverts scores to the neutral 50 fallback
        #    (every pillar == 50, composite == 50). Acting on that mass-exits good
        #    positions — the 2026-06 incident. Detect it and do nothing.
        EXIT_SCORE   = 45.0
        MIN_UNIVERSE = 100      # a healthy run scores the whole ~800-name universe
        def _is_neutral_fallback(r):
            try:
                if abs(float(r.get("composite", 0) or 0) - 50.0) > 0.5:
                    return False
                return all(
                    abs(float(r.get(k, 50) or 50) - 50.0) < 0.01
                    for k in ("momentum", "quality", "volume", "value", "sentiment")
                )
            except Exception:
                return False
        _n_scored  = len(scored_list)
        _n_neutral = sum(1 for r in scored_list if _is_neutral_fallback(r))
        if _n_scored < MIN_UNIVERSE or (_n_scored and _n_neutral / _n_scored > 0.40):
            log.error(
                f"[MODEL PORTFOLIO] ABORT — degraded scoring run "
                f"(scored={_n_scored}, neutral_fallback={_n_neutral}). "
                f"No exits or entries executed; positions left untouched."
            )
            return

        # ── Step 1: Exit positions whose conviction has collapsed ─────────────
        #    Exit on the macro-adjusted blend (adj_composite) — the published
        #    conviction score — so a sustained macro/sector headwind that drags a
        #    holding below 45 takes us out, by design.
        #
        #    SAFETY: only let the macro drive exits when the macro pass is healthy.
        #    The empty-overlay failure mode zeroes macro_overlay on every name; a
        #    bad-overlay run could instead tank adj_composite and force-sell good
        #    holdings (the June-6 incident class). If the overlay looks inactive
        #    this run, fall back to the macro-neutral composite so a degraded macro
        #    can NEVER trigger an exit. The run-health gate above already aborts the
        #    fully-degraded (neutral-50) case; this covers the empty/partial case,
        #    and the circuit breaker below still caps any one-run exit cluster.
        _n = len(scored_list) or 1
        _regime = (_load_macro_state() or {}).get("regime")
        _macro_live = (sum(1 for r in scored_list
                           if abs(float(r.get("macro_overlay", 0) or 0)) > 0.01) / _n) > 0.5
        _exit_field = "adj_composite" if _macro_live else "composite"
        if not _macro_live:
            log.warning(
                "[MODEL PORTFOLIO] macro overlay inactive this run (macro_overlay ~0 "
                "across the universe) — exiting on raw composite, not the blend, so a "
                "degraded macro can't force-sell holdings. Fix the overlay and re-run."
            )
        # EOD-only exits: never sell on an unsettled intraday print. The hourly
        # --rescore run rebalances mid-session, which sold CF on 2026-07-17 at a
        # transient 55.0 that settled at 59.6 the same day. Entries still fill
        # intraday; only the sell side waits for settled prices.
        from market_calendar import market_is_open_now as _mkt_open
        _eod_ok = not _mkt_open()
        if not _eod_ok:
            log.info("[MODEL PORTFOLIO] Session open — exits deferred to the settled EOD run.")
        exit_candidates = []
        for pos in active:
            sc = score_map.get(pos["ticker"])
            if not sc:
                continue
            gate = float(sc.get(_exit_field, sc.get("composite", 50)) or 50)
            if _eod_ok and _is_exit(gate):
                exit_candidates.append((pos, gate, sc))

        # ── Circuit breaker — a one-run cluster of exits is a data/model artifact,
        #    not real conviction collapse. Refuse to act and alert instead.
        MAX_EXITS_PER_RUN = max(5, int(0.20 * len(active)))
        if len(exit_candidates) > MAX_EXITS_PER_RUN:
            log.error(
                f"[MODEL PORTFOLIO] ABORT exits — {len(exit_candidates)} positions "
                f"would exit this run (cap {MAX_EXITS_PER_RUN}). Treating as a data/"
                f"model artifact rather than real conviction collapse; nothing exited."
            )
            return

        exited = []
        for pos, gate, sc in exit_candidates:
            tk = pos["ticker"]
            sb.table("model_portfolio_positions").update({
                "is_active":   False,
                "exit_date":   today,
                "exit_price":  sc.get("price"),
                "exit_score":  round(gate, 1),
                "exit_reason": "SELL_SIGNAL",
            }).eq("id", pos["id"]).execute()
            exited.append(tk)
            active_tickers.discard(tk)
            # Reduce sector count for exited position
            sec = _sector_of(tk)
            sector_counts[sec] = max(0, sector_counts.get(sec, 1) - 1)
            log.info(f"[MODEL PORTFOLIO] EXIT {tk} {_exit_field}={gate:.1f} — conviction collapsed")

        # ── Step 2: Fill open slots up to TARGET ─────────────────────────────
        slots_needed = TARGET - len(active_tickers)
        if slots_needed <= 0:
            log.info(f"[MODEL PORTFOLIO] Full ({len(active_tickers)}/{TARGET}) — "
                     f"{len(exited)} exited this run")
            return

        # Rank High Conviction stocks (>=60) not already held by the blend:
        # conviction primary, valuation position as the tie-breaking tilt — so an
        # opening slot is filled by the highest-conviction name trading cheapest
        # in its range, not just the top raw score.
        candidates = sorted(
            [r for r in scored_list
             if _is_entry(r.get("adj_composite", r.get("composite", 0)), _regime)
             and r["ticker"] not in active_tickers
             and r.get("price")],
            key=_entry_blend_score,
            reverse=True
        )

        # ── Redeploy freed capital, don't leak it ─────────────────────────────
        # Book NAV = base − total deployed + realized exit proceeds. Split the
        # available cash across the open slots, so a winner's proceeds go fully
        # back to work (compounding) instead of a flat $2K refill leaving the
        # gain parked in idle cash. Unfilled slots keep their share as cash.
        MP_BASE = TARGET * POS_SIZE
        _all_pos = (sb.table("model_portfolio_positions")
                    .select("position_size,entry_price,exit_price,is_active")
                    .eq("epoch", _EPOCH).execute().data or [])
        _cash = MP_BASE
        for _p in _all_pos:
            _ps = float(_p.get("position_size") or POS_SIZE)
            _cash -= _ps
            if (not _p.get("is_active")) and _p.get("exit_price") and _p.get("entry_price"):
                try:
                    _cash += (_ps / float(_p["entry_price"])) * float(_p["exit_price"])
                except (TypeError, ZeroDivisionError):
                    pass
        deploy_each = (_cash / slots_needed) if slots_needed > 0 else POS_SIZE
        if not (deploy_each > 0):
            deploy_each = POS_SIZE
        log.info(f"[MODEL PORTFOLIO] available cash ${_cash:,.0f} / {slots_needed} slot(s) "
                 f"= ${deploy_each:,.0f} per new position")

        entered = []
        skipped_cap = 0
        for r in candidates:
            if len(entered) >= slots_needed:
                break
            tk  = r["ticker"]
            sec = _sector_of(tk)

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
                "position_size": round(deploy_each, 2),
                "is_active":     True,
                "epoch":         _EPOCH,
            }).execute()
            sector_counts[sec] = sector_counts.get(sec, 0) + 1
            active_tickers.add(tk)
            entered.append(tk)
            _vp_log = _entry_val_pos(r)
            _vp_str = "n/a" if _vp_log is None else f"{_vp_log:.0f}"
            log.info(f"[MODEL PORTFOLIO] ENTER {tk} ({sec}) @ ${r.get('price')} "
                     f"score={adj:.1f} val_pos={_vp_str} blend={_entry_blend_score(r):.1f}")

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

def run_refresh(tickers: list = None, force: bool = False,
                use_cached_fundamentals: bool = False) -> dict:
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

    if use_cached_fundamentals:
        # Hourly intraday FULL re-score: reuse last night's fundamentals from the
        # cache (they don't move intraday) and skip the expensive per-ticker fetch
        # loop. Everything downstream — price download, scoring, health gates,
        # signal_log write, model-portfolio rebalance — runs exactly as nightly,
        # but on fresh intraday prices. This is what makes conviction/metrics move
        # through the day for the whole universe without re-pulling fundamentals.
        live_data = load_cached_fundamentals(max_age_hours=24 * 7) or {}
        static_used = [t for t in tickers if t not in live_data]
        for t in static_used:
            live_data[t] = FUNDAMENTALS.get(t, {})
        log.info(f"Intraday full re-score: {len(tickers) - len(static_used)} tickers from "
                 f"fundamentals cache, {len(static_used)} static fallback (no re-fetch).")
    else:
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
            # Carry raw valuation inputs for the Valuation Range pass (not written
            # to signal_log directly — consumed by compute_valuation_band below).
            s["_fpe"]  = f.get("fpe")
            s["_w52h"] = f.get("w52h")
            s["_w52l"] = f.get("w52l")
            scores.append(s)

        # Cross-sectional percentile ranking
        composites = [s["composite"] for s in scores]
        for s in scores:
            rank = sum(1 for c in composites if c <= s["composite"]) / len(composites) * 100
            s["pct_rank"] = round(rank, 1)

        scores.sort(key=lambda x: x["composite"], reverse=True)

        # ── Publish-health gate (pre-overlay, pre-write) ──────────────────
        # When the price-history (or fundamentals) fetch fails, score_stock
        # returns NEUTRAL 50 pillars even though the static composite survives.
        # Publishing that resets the entire screener to 50s and zeroes the macro
        # column (the 2026-06 reset). The older gate in update_model_portfolio
        # misses this because it also requires composite==50, which a static
        # composite is not — so detect the neutral-PILLAR signature directly
        # here and refuse to overwrite the last good batch.
        def _is_bad(r):
            # Unusable row: composite missing/NaN (serializes to NULL in
            # signal_log) OR every pillar missing/NaN/neutral-50 (the per-ticker
            # failure signature). NaN MUST be caught explicitly — it isn't None
            # and isn't 50, so the old neutral-only check let it through and it
            # wrote as NULL (the 2026-06 null-composite batches that reset the
            # screener to base 50s).
            import math as _math
            c = r.get("composite")
            try:
                if c is None or _math.isnan(float(c)):
                    return True
            except (TypeError, ValueError):
                return True
            try:
                bad = 0
                for k in ("momentum", "quality", "volume", "value", "sentiment"):
                    v = r.get(k)
                    if v is None:
                        bad += 1; continue
                    fv = float(v)
                    if _math.isnan(fv) or abs(fv - 50.0) < 0.01:
                        bad += 1
                return bad == 5
            except Exception:
                return False
        _n_sc  = len(scores)
        _n_neu = sum(1 for r in scores if _is_bad(r))
        if _n_sc < 100 or (_n_sc and _n_neu / _n_sc > 0.40):
            log.error(
                f"ABORT publish — degraded scoring run: {_n_neu}/{_n_sc} rows "
                f"have a null/NaN composite or all-neutral pillars (price "
                f"histories fetched for {len(price_histories)}/{len(tickers)}). "
                f"signal_log, macro_state and the model portfolio are left "
                f"untouched; the last good batch stays live."
            )
            return {
                "success": False, "degraded": True,
                "bad_rows": _n_neu, "scored": _n_sc,
                "history_coverage": len(price_histories), "total": len(tickers),
                "live_count": len(tickers) - len(static_used),
                "static_count": len(static_used),
                "reason": "degraded_scores",
            }

        # Apply live macro overlay
        macro = fetch_macro_overlay(use_live_feeds=True)
        _write_macro_state(macro)
        scored = apply_macro_overlay(scores, macro)

        # ── QNTM Valuation Range (Value Position) ─────────────────────────────
        # Descriptive valuation context, computed cross-sectionally so each name's
        # band is anchored to its sector's median forward multiple. Runs after the
        # overlay so it rides the same dicts written to signal_log.
        from model_engine import sector_fair_multiples, compute_valuation_band
        _sector_fpe = sector_fair_multiples(scored)
        _vr_n = 0
        for s in scored:
            band = compute_valuation_band(
                price=s.get("price"),
                fpe=s.get("_fpe"),
                sector_fair_fpe=_sector_fpe.get(s.get("sector")),
                quality=s.get("quality"),
                momentum=s.get("momentum"),
                price_history=price_histories.get(s["ticker"], []),
                w52_hi=s.get("_w52h"), w52_lo=s.get("_w52l"),
            )
            s.update(band)
            if band["val_basis"] != "na":
                _vr_n += 1
            for _k in ("_fpe", "_w52h", "_w52l"):
                s.pop(_k, None)
        log.info(f"Valuation Range computed for {_vr_n}/{len(scored)} names "
                 f"({len(_sector_fpe)} sectors with a median multiple)")

        # Write to signal_log
        write_signal_snapshot(scored)

        # Snapshot today's raw multiples so a real historical valuation range
        # accrues over time (unlocks a history-percentile anchor component later).
        write_valuation_history(live_data)

        # Update model portfolio positions
        update_model_portfolio(scored)

        # SPY benchmark close for the Model Portfolio equity curve (stored so the
        # page rebuilds the curve from Supabase, no live pull).
        update_benchmark_price()

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

-- ── macro_state: single-row live macro overlay (run once in Supabase SQL editor) ──
CREATE TABLE IF NOT EXISTS public.macro_state (
    id          INT PRIMARY KEY DEFAULT 1,
    overlay     JSONB NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT macro_state_singleton CHECK (id = 1)
);

ALTER TABLE public.macro_state ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Macro state public read" ON public.macro_state
    FOR SELECT USING (true);
"""


# ── INTRADAY PRICE REFRESH ────────────────────────────────────────────────────

def run_intraday_refresh(tickers: list = None, prices_only: bool = False) -> dict:
    """
    Lightweight intraday refresh — updates price + momentum scores only.
    Runs every 15 minutes during US market hours (9:30 AM–4:45 PM ET, Mon–Fri).
    Skips fundamental re-fetch and full model re-score to stay within rate limits.
    Writes updated price to signal_log for today's date (upserts).

    prices_only=True refreshes prices + the SPY benchmark but SKIPS portfolio
    maintenance (exits/entries). Use it for the always-on freshness worker: it
    keeps stored prices current every ~90s without letting the model trade on
    intraday noise. Exit/entry decisions belong on a deliberate cadence (nightly
    full run / 30-min macro pass), matching the published conviction discipline.
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
    # Only refresh prices on tickers that ALREADY have a scored row for today.
    # Upserting a bare {ticker, signal_date, price} for a ticker with no scored
    # row INSERTs a new row with NULL composite/pillars — which is exactly what
    # reset the screener to base 50s (the 2026-06 null-composite rows). If the
    # nightly scored batch hasn't published for today, write nothing and let the
    # last good batch stand.
    try:
        _ex_rows = _fetch_all_rows(lambda: sb.table("signal_log").select("ticker")
            .eq("signal_date", today).not_.is_("composite", "null"))
        scored_today = {r["ticker"] for r in _ex_rows}
    except Exception:
        scored_today = set()
    if not scored_today:
        log.warning("Intraday refresh: no scored rows for today — skipping price "
                    "writes so no null-score rows are created.")
        return {"success": True, "updated": 0, "reason": "no_scored_batch_today"}
    updated = 0
    failed  = 0

    # Fetch current prices in batches of 200. SPY rides along in the bulk
    # download so the benchmark refreshes every cycle in the same rate-limited
    # batch as the stocks — instead of via a separate call that gets throttled
    # after the batch storm and leaves SPY stale (reading 0% intraday).
    spy_px = None
    _dl_tickers = list(tickers) + ["SPY"]
    chunk_size = 200
    for i in range(0, len(_dl_tickers), chunk_size):
        chunk = _dl_tickers[i:i + chunk_size]
        try:
            hist = yf.download(chunk, period="1d", auto_adjust=True, progress=False, threads=True)
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

            for _r in rows:
                if _r["ticker"] == "SPY" and _r.get("price"):
                    spy_px = _r["price"]
            rows = [r for r in rows if r["ticker"] in scored_today]
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

    # Keep the SPY benchmark close fresh intraday too, so the stored equity curve
    # tracks during market hours. Prefer the SPY price from the bulk download
    # above (reliable — same batch as the stocks); fall back to the standalone
    # fetch only if SPY wasn't captured in the bulk result.
    if spy_px and spy_px > 0:
        try:
            sb.table(BENCHMARK_TABLE).upsert(
                {"d": today, "close": float(spy_px),
                 "updated_at": datetime.now(timezone.utc).isoformat()},
                on_conflict="d"
            ).execute()
            log.info(f"benchmark_price: SPY {float(spy_px):.2f} @ {today} (bulk)")
        except Exception as e:
            log.warning(f"benchmark_price bulk upsert failed ({e}); using standalone")
            update_benchmark_price()
    else:
        update_benchmark_price()

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
    # SKIPPED when prices_only=True (the freshness worker) so the model doesn't
    # trade on intraday noise — exits/entries stay on the nightly / macro cadence.
    if prices_only:
        log.info("[MODEL PORTFOLIO] prices_only — skipping intraday exits/entries")
    else:
        try:
            today_str = date.today().isoformat()
            sig_rows = _fetch_all_rows(lambda: sb.table("signal_log")
                .select("ticker,adj_composite,composite,price,momentum,quality,volume,value,sentiment")
                .eq("signal_date", today_str))
            if sig_rows:
                # Apply macro overlay to get fresh adj_composite scores.
                try:
                    from model_engine import apply_macro_overlay, fetch_macro_overlay
                    macro = _load_macro_state() or fetch_macro_overlay(use_live_feeds=False)
                    # Sector is NOT stored in signal_log; attach it from the
                    # canonical universe_data.SECTORS map (same source score_stock
                    # uses) BEFORE applying the overlay. Without this every row is
                    # "Unknown", sector_overlays misses on all of them, and
                    # macro_overlay collapses to 0.0 across the entire universe —
                    # which trips the "macro overlay inactive" guard in
                    # update_model_portfolio and drops the macro tilt from intraday
                    # decisions. Mirrors run_macro_refresh step 4. Skip
                    # null-composite rows so a missed nightly can't fabricate
                    # overlays (the 2026-06-06 incident class).
                    try:
                        from universe_data import SECTORS as _SECTORS
                    except Exception:
                        _SECTORS = {}
                    scored_rows = []
                    for r in sig_rows:
                        if r.get("composite") is None:
                            continue
                        r["sector"]    = _SECTORS.get(r["ticker"], "Unknown")
                        r["composite"] = float(r["composite"])
                        scored_rows.append(r)
                    scored_today = apply_macro_overlay(scored_rows, macro)
                except Exception:
                    scored_today = sig_rows  # use raw if overlay fails
                update_model_portfolio(scored_today)
            else:
                log.info("[MODEL PORTFOLIO] No signal_log data for today — skipping intraday portfolio update")
        except Exception as e:
            log.warning(f"[MODEL PORTFOLIO] Intraday update failed: {e}")

    if updated == 0 and failed == len(tickers):
        return {"success": False, "error": f"All {failed} batches failed", "updated": 0, "duration_s": duration}
    return {"success": True, "updated": updated, "failed": failed, "duration_s": duration, "mode": "intraday"}


# ── LIVE MACRO REFRESH ────────────────────────────────────────────────────────
def run_macro_refresh(tickers: list = None) -> dict:
    """
    Lightweight live macro pass. Re-scans news/macro feeds and re-applies the
    sector overlay to today's EXISTING scores — no fundamental/price re-fetch.
    Cheap enough (a handful of RSS + VIX + WTI calls) to run every 30 min all
    day, including after hours and weekends, so a breaking macro/geopolitical
    event moves adj_composite intraday instead of waiting for the nightly run.

    Steps:
      1. fetch_macro_overlay(use_live_feeds=True)        — RSS headlines + VIX + WTI
      2. persist it to macro_state (single source of truth)
      3. load today's signal_log rows, attach sector from fundamentals_cache
      4. apply_macro_overlay -> fresh adj_composite / signal / macro_overlay
      5. write the refreshed rows back to signal_log
      6. update_model_portfolio on the new scores
    """
    from model_engine import fetch_macro_overlay, apply_macro_overlay

    log.info("Macro refresh: scanning live macro feeds")
    start = time.time()
    sb = _get_supabase()
    if not sb:
        return {"success": False, "error": "No Supabase connection", "mode": "macro"}

    today = date.today().isoformat()

    # 1-2. Live scan + persist (do this even if there are no scores yet to adjust)
    macro = fetch_macro_overlay(use_live_feeds=True)

    # ── Degraded-overlay guard ────────────────────────────────────────────────
    # A single macro pass overwrites adj_composite/macro_overlay for the ENTIRE
    # universe. If a transient feed dip (RSS timeout, thin scan) yields an empty
    # overlay, writing its zeros silently kills the macro tilt on ~1,400 names —
    # which is exactly how the 2026-06-24 zeroing went unnoticed until a stock
    # card read MACRO +0.0. Distinguish two empty-overlay cases:
    #   (a) genuinely quiet macro — healthy headline sample, nothing clears the
    #       activation bar. Empty overlay is CORRECT; just surface the transition
    #       loudly so a flat overlay is never a silent surprise again.
    #   (b) degraded feed — suspiciously thin scan produced the empty overlay.
    #       HOLD last-good macro_state and skip the rescore so a hiccup can't
    #       zero the universe. A sustained quiet market still zeroes via case (a)
    #       once the scan is healthy.
    _new_overlays = macro.get("sector_overlays") or {}
    _new_active   = any(abs(float(v or 0)) > 1e-9 for v in _new_overlays.values())
    if not _new_active:
        _prior          = _load_macro_state() or {}
        _prior_overlays = _prior.get("sector_overlays") or {}
        _prior_active   = any(abs(float(v or 0)) > 1e-9 for v in _prior_overlays.values())
        _scanned        = int(macro.get("headlines_scanned") or 0)
        _MIN_HEALTHY_SCAN = 25   # a normal live scan is ~100+; below this the feed is suspect
        if _prior_active and _scanned < _MIN_HEALTHY_SCAN:
            log.error(
                f"[MACRO] degraded-feed guard TRIPPED — new overlay empty on only "
                f"{_scanned} headlines while the stored overlay is active. Holding "
                f"last-good macro_state and SKIPPING the signal_log rescore so a feed "
                f"hiccup can't zero the universe overlay. Investigate the feed; re-run "
                f"a full refresh once it recovers."
            )
            duration = round(time.time() - start, 1)
            return {"success": True, "mode": "macro", "held_last_good": True,
                    "regime": _prior.get("regime"), "headlines_scanned": _scanned,
                    "updated": 0, "duration_s": duration}
        elif _prior_active:
            log.warning(
                f"[MACRO] overlay went FLAT this cycle — {_scanned} headlines scanned, "
                f"no event cleared the activation bar, so the universe overlay is being "
                f"reset to neutral (macro tilt OFF until an event re-activates). Expected "
                f"on a quiet news day; if unexpected, check the activation thresholds in "
                f"fetch_macro_overlay (CONFLICT_RESCUE_GATE / the >=2.0 generic gate)."
            )
    _write_macro_state(macro)

    # 3. Load today's scores
    try:
        rows = _fetch_all_rows(lambda: sb.table(SIGNAL_TABLE).select(
            "ticker,composite,momentum,quality,volume,value,sentiment,"
            "signal,macro_overlay,adj_composite,price,is_hidden_gem,hidden_gem_reason"
        ).eq("signal_date", today))
    except Exception as e:
        return {"success": False, "error": f"signal_log read failed: {e}",
                "mode": "macro", "regime": macro.get("regime")}

    if not rows:
        duration = round(time.time() - start, 1)
        log.info("Macro refresh: no signal_log rows for today yet — macro_state saved only")
        return {"success": True, "mode": "macro", "regime": macro.get("regime"),
                "source": macro.get("source"), "updated": 0, "duration_s": duration}

    # 4. Attach sector (required for the sector overlay). Sector is NOT stored
    #    in signal_log or in the fundamentals cache — the canonical source is the
    #    universe_data.SECTORS map, exactly what score_stock() uses to label each
    #    score and what apply_macro_overlay() looks up against SECTOR_EVENT_MAP.
    #    Without this, every row is "Unknown" and the sector overlay resolves to
    #    0.0 for the entire universe (MACRO +0.0 on every stock).
    try:
        from universe_data import SECTORS as _SECTORS
    except Exception:
        _SECTORS = {}
    # Only rows with a REAL composite from the nightly full scoring run get a
    # macro overlay. A null composite means the nightly rescore hasn't populated
    # this row yet — coercing it to 50 and writing a fabricated adj_composite is
    # exactly what produced the bogus scores and the mass tech exit on
    # 2026-06-06. Skip those rows so a missed nightly can't fabricate signals.
    scored_rows  = []
    skipped_null = 0
    for r in rows:
        if r.get("composite") is None:
            skipped_null += 1
            continue
        r["sector"]    = _SECTORS.get(r["ticker"], "Unknown")
        r["composite"] = float(r["composite"])
        r["momentum"]  = float(r.get("momentum") or 50)
        scored_rows.append(r)
    if skipped_null:
        log.warning(
            f"[MACRO] skipped {skipped_null}/{len(rows)} rows with null composite "
            f"(nightly rescore hasn't populated them) — no fabricated overlay written. "
            f"Run a full refresh (data_refresh.py --force) to repopulate scores."
        )

    # If the sector map didn't resolve (SECTORS import failed / universe drift),
    # the overlay silently collapses to 0.0 on every name (MACRO +0.0 everywhere).
    # Surface it loudly instead of shipping a no-op macro pass as if it were real.
    _unknown = sum(1 for r in scored_rows if r.get("sector", "Unknown") == "Unknown")
    if scored_rows and _unknown / len(scored_rows) > 0.5:
        log.error(
            f"[MACRO] sector map degraded — {_unknown}/{len(scored_rows)} rows resolved to "
            f"Unknown (SECTORS import or universe map likely broken). Overlay will be "
            f"~0 on every name; exits are gated on quant composite so this won't force "
            f"sells, but the macro tilt is effectively off until this is fixed."
        )

    scored = apply_macro_overlay(scored_rows, macro)

    # 5. Write back ONLY the macro-derived columns. The intraday price pass owns
    #    price/composite/momentum; this pass owns adj_composite/signal/macro_overlay.
    #    Disjoint column sets => the two jobs can run at the same instant safely
    #    (PostgREST upserts only the columns present; today's rows already exist).
    write_rows = []
    for s in scored:
        write_rows.append({
            "ticker":        s["ticker"],
            "signal_date":   today,
            "adj_composite": s.get("adj_composite"),
            "signal":        s.get("signal"),
            "macro_overlay": s.get("macro_overlay"),
        })
    updated = 0
    try:
        for i in range(0, len(write_rows), BATCH_SIZE):
            batch = write_rows[i:i + BATCH_SIZE]
            sb.table(SIGNAL_TABLE).upsert(batch, on_conflict="ticker,signal_date").execute()
            updated += len(batch)
    except Exception as e:
        return {"success": False, "error": f"signal_log write failed: {e}",
                "mode": "macro", "regime": macro.get("regime")}

    # 6. Refresh model portfolio (exits/entries) on the new scores
    try:
        update_model_portfolio(scored)
    except Exception as e:
        log.warning(f"[MODEL PORTFOLIO] Macro-pass update failed: {e}")

    # Touch the pill timestamp (reuse the intraday sentinel row)
    try:
        sb.table("fundamentals_cache").upsert(
            {"ticker": "_intraday_sentinel", "data_date": today,
             "refreshed_at": datetime.utcnow().isoformat(),
             "fundamentals": "{}", "price": None, "vol_ratio": None},
            on_conflict="ticker,data_date"
        ).execute()
    except Exception:
        pass

    duration = round(time.time() - start, 1)
    log.info(f"Macro refresh complete: regime={macro.get('regime')} "
             f"({macro.get('source')}) — {updated} rows re-scored in {duration}s")
    return {"success": True, "mode": "macro",
            "regime": macro.get("regime"), "source": macro.get("source"),
            "active_events": macro.get("active_events"),
            "updated": updated, "duration_s": duration}


# ── ENTRYPOINT ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="QNTM Nightly Data Refresh")
    parser.add_argument("--force",    action="store_true", help="Bypass freshness check")
    parser.add_argument("--intraday", action="store_true", help="Run lightweight intraday price refresh only")
    parser.add_argument("--rescore",  action="store_true", help="Hourly intraday FULL re-score (cached fundamentals + fresh prices: re-scores composite/pillars/conviction for the whole universe and rebalances the model portfolio)")
    parser.add_argument("--macro",    action="store_true", help="Run lightweight live macro re-scan + overlay re-apply only")
    parser.add_argument("--tickers",  nargs="*",           help="Specific tickers to refresh")
    parser.add_argument("--schema",   action="store_true", help="Print schema SQL and exit")
    args = parser.parse_args()

    if args.schema:
        print(SCHEMA_SQL)
        sys.exit(0)

    # Respect INTRADAY_RUN env var (set by GitHub Actions intraday cron)
    import os
    is_intraday = args.intraday or os.getenv("INTRADAY_RUN", "false").lower() == "true"
    is_macro    = args.macro    or os.getenv("MACRO_RUN",    "false").lower() == "true"
    is_rescore  = args.rescore  or os.getenv("RESCORE_RUN",  "false").lower() == "true"

    if is_macro:
        result = run_macro_refresh(tickers=args.tickers)
    elif is_rescore:
        result = run_refresh(tickers=args.tickers, force=True, use_cached_fundamentals=True)
    elif is_intraday:
        result = run_intraday_refresh(tickers=args.tickers)
    else:
        result = run_refresh(tickers=args.tickers, force=args.force)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("success") else 1)


def refresh_extended_prices(tickers=None, session="pre"):
    """Capture pre/post-market prices for held names + SPY, WITHOUT touching the
    regular `price` mark that feeds the equity curve.

    Stocks  -> signal_log.pre_price / .post_price  (only for tickers already
               scored today, to avoid creating null-composite rows).
    SPY     -> benchmark_price.pre_close / .post_close.

    session in {"pre","post"}. yfinance extended-hours data is thin for small-caps;
    callers should surface a coverage count rather than treat it as complete.
    """
    import yfinance as yf
    from universe_data import SECTORS
    if session not in ("pre", "post"):
        return {"success": False, "error": "session must be pre|post"}
    scol = "pre_price" if session == "pre" else "post_price"
    bcol = "pre_close" if session == "pre" else "post_close"
    if tickers is None:
        tickers = list(SECTORS.keys())
    sb = _get_supabase()
    if not sb:
        return {"success": False, "error": "No Supabase connection"}

    today = date.today().isoformat()
    try:
        _ex = _fetch_all_rows(lambda: sb.table("signal_log").select("ticker")
              .eq("signal_date", today).not_.is_("composite", "null"))
        scored_today = {r["ticker"] for r in _ex}
    except Exception:
        scored_today = set()
    if not scored_today:
        log.warning("Extended refresh: no scored rows today - skipping.")
        return {"success": True, "updated": 0, "reason": "no_scored_batch_today"}

    names = [t for t in list(tickers) if t in scored_today]
    _dl = names + ["SPY"]
    updated = 0
    chunk_size = 200
    for i in range(0, len(_dl), chunk_size):
        chunk = _dl[i:i + chunk_size]
        try:
            hist = yf.download(chunk, period="1d", interval="1m", prepost=True,
                               auto_adjust=True, progress=False, threads=True)
            if hist is None or hist.empty or "Close" not in hist.columns:
                continue
            close = hist["Close"]
            def _last(series):
                v = series.dropna()
                return round(float(v.iloc[-1]), 4) if not v.empty else None
            stock_rows, spy_px = [], None
            if hasattr(close, "columns"):
                for tk in chunk:
                    if tk in close.columns:
                        px = _last(close[tk])
                        if px is None:
                            continue
                        if tk == "SPY":
                            spy_px = px
                        elif tk in scored_today:
                            stock_rows.append({"ticker": tk, "signal_date": today, scol: px})
            elif len(chunk) == 1:
                px = _last(close)
                if px is not None:
                    if chunk[0] == "SPY":
                        spy_px = px
                    elif chunk[0] in scored_today:
                        stock_rows.append({"ticker": chunk[0], "signal_date": today, scol: px})
            if stock_rows:
                sb.table("signal_log").upsert(stock_rows, on_conflict="ticker,signal_date").execute()
                updated += len(stock_rows)
            if spy_px is not None:
                # benchmark_price.close is NOT NULL, so a partial upsert fails —
                # UPDATE the existing row (sets only the extended col); INSERT only
                # if today's row doesn't exist yet.
                _upd = sb.table("benchmark_price").update({bcol: spy_px}).eq("d", today).execute()
                if not (_upd.data or []):
                    try:
                        sb.table("benchmark_price").insert({"d": today, "close": spy_px, bcol: spy_px}).execute()
                    except Exception as _e:
                        log.warning("benchmark_price insert (extended) failed: %s", _e)
        except Exception as e:
            log.warning("Extended batch %s (%s) failed: %s", i, session, e)

    log.info("Extended refresh (%s): %s stock prices + SPY -> %s/%s", session, updated, scol, bcol)
    return {"success": True, "updated": updated, "session": session}
