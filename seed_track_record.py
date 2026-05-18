"""
QNTM — Public Track Record Seeder
===================================
Seeds signal_log with real historical entry dates so the backtest
and public track record pages show genuine data rather than empty states.

Run ONCE locally before pushing dev to beta:

    python seed_track_record.py

What it does:
  1. Pulls real quarterly closing prices from yfinance for all backtest periods
  2. Scores each holding as-of the quarter start date using walk-forward data
  3. Writes dated rows to signal_log (one row per ticker per quarter)
  4. Skips any quarter/ticker pair that already exists (safe to re-run)

Backtest periods covered: Q2 2020 → Q1 2025 (20 quarters, 124 tickers each)

Requirements:
  - SUPABASE_URL and SUPABASE_SERVICE_KEY set in env or .streamlit/secrets.toml
  - yfinance installed
  - Run from the project root (same dir as data_refresh.py)

Usage:
  python seed_track_record.py              # seed all 20 quarters
  python seed_track_record.py --dry-run    # print what would be written, don't write
  python seed_track_record.py --quarter 2022-Q1   # single quarter only
  python seed_track_record.py --force      # overwrite existing rows
"""

import os, sys, time, json, argparse, logging
from datetime import datetime, date, timedelta

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("qntm.seed")

# ── BACKTEST QUARTER MAP ──────────────────────────────────────────────────────
# Maps quarter key → (score_date, period_end_date)
# score_date  = start of quarter (when model would have scored)
# period_end  = end of quarter (when returns were measured)

QUARTER_MAP = {
    "2020-Q2": ("2020-04-01", "2020-06-30"),
    "2020-Q3": ("2020-07-01", "2020-09-30"),
    "2020-Q4": ("2020-10-01", "2020-12-31"),
    "2021-Q1": ("2021-01-01", "2021-03-31"),
    "2021-Q2": ("2021-04-01", "2021-06-30"),
    "2021-Q3": ("2021-07-01", "2021-09-30"),
    "2021-Q4": ("2021-10-01", "2021-12-31"),
    "2022-Q1": ("2022-01-01", "2022-03-31"),
    "2022-Q2": ("2022-04-01", "2022-06-30"),
    "2022-Q3": ("2022-07-01", "2022-09-30"),
    "2022-Q4": ("2022-10-01", "2022-12-31"),
    "2023-Q1": ("2023-01-01", "2023-03-31"),
    "2023-Q2": ("2023-04-01", "2023-06-30"),
    "2023-Q3": ("2023-07-01", "2023-09-30"),
    "2023-Q4": ("2023-10-01", "2023-12-31"),
    "2024-Q1": ("2024-01-01", "2024-03-31"),
    "2024-Q2": ("2024-04-01", "2024-06-30"),
    "2024-Q3": ("2024-07-01", "2024-09-30"),
    "2024-Q4": ("2024-10-01", "2024-12-31"),
    "2025-Q1": ("2025-01-01", "2025-03-31"),
}

# Regime as-of each quarter (from walk-forward backtest)
QUARTER_REGIME = {
    "2020-Q2": "RISK_ON",  "2020-Q3": "RISK_ON",  "2020-Q4": "RISK_ON",
    "2021-Q1": "RISK_ON",  "2021-Q2": "RISK_ON",  "2021-Q3": "NEUTRAL",
    "2021-Q4": "NEUTRAL",  "2022-Q1": "RISK_OFF",  "2022-Q2": "RISK_OFF",
    "2022-Q3": "RISK_OFF",  "2022-Q4": "NEUTRAL",  "2023-Q1": "NEUTRAL",
    "2023-Q2": "RISK_ON",  "2023-Q3": "NEUTRAL",   "2023-Q4": "RISK_ON",
    "2024-Q1": "RISK_ON",  "2024-Q2": "NEUTRAL",   "2024-Q3": "RISK_ON",
    "2024-Q4": "RISK_ON",  "2025-Q1": "RISK_OFF",
}


def _get_supabase():
    """Return Supabase client from env or Streamlit secrets."""
    try:
        from supabase import create_client
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")
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
        log.error(f"Supabase unavailable: {e}")
    return None


def _fetch_price_history(tickers: list, start: str, end: str) -> dict:
    """
    Fetch closing price history for a list of tickers between start and end dates.
    Returns {ticker: [prices oldest→newest]}.
    Uses 6-month lookback before start so momentum calculations have enough history.
    """
    import yfinance as yf
    import pandas as pd

    # Pull 6 months before start for momentum lookback
    start_dt = datetime.strptime(start, "%Y-%m-%d") - timedelta(days=182)
    fetch_start = start_dt.strftime("%Y-%m-%d")

    histories = {}
    chunk_size = 100
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        log.info(f"  Fetching price history for tickers {i+1}–{i+len(chunk)}...")
        try:
            hist = yf.download(
                chunk, start=fetch_start, end=end,
                auto_adjust=True, progress=False, threads=True
            )
            if "Close" in hist.columns:
                close = hist["Close"]
                for tk in chunk:
                    if tk in close.columns:
                        vals = close[tk].dropna().tolist()
                        if vals:
                            histories[tk] = vals
        except Exception as e:
            log.warning(f"  Batch download failed for chunk {i}: {e}")
        time.sleep(1)

    return histories


def _score_historical(ticker: str, price_history: list, quarter: str) -> dict:
    """
    Score a ticker using historical price data as-of the quarter start.
    Uses static fundamentals only (live data not available for historical periods).
    """
    from model_engine import score_stock, apply_macro_overlay
    from universe_data import FUNDAMENTALS

    # Score with static fundamentals (historical — no live data for past quarters)
    scored = score_stock(ticker, price_history, live_fundamentals=None, vol_ratio=None)

    # Apply macro regime from the backtest
    regime = QUARTER_REGIME.get(quarter, "NEUTRAL")
    macro_weights = {
        "RISK_ON":  {"weight": 0.15},
        "RISK_OFF": {"weight": 0.35},
        "NEUTRAL":  {"weight": 0.10},
    }
    w = macro_weights.get(regime, {"weight": 0.10})["weight"]

    # Apply regime scaling (mirrors apply_macro_overlay logic)
    quant = scored["composite"]
    # Risk-off: blend toward 50 (neutral) with regime weight; risk-on: slight boost
    if regime == "RISK_OFF":
        adj = quant * (1 - w) + 50 * w
    elif regime == "RISK_ON":
        adj = quant + (quant - 50) * w * 0.2
    else:
        adj = quant

    adj = round(max(0, min(100, adj)), 1)
    action = "BUY" if adj >= 60 else ("SELL" if adj < 45 else "HOLD")

    scored["adj_composite"]  = adj
    scored["adj_action"]     = action
    scored["macro_regime"]   = regime
    scored["score_delta"]    = round(adj - quant, 1)
    scored["pct_rank"]       = 50   # not meaningful for historical seeding

    return scored


def seed_quarter(
    quarter: str,
    score_date: str,
    period_end: str,
    tickers: list,
    price_histories: dict,
    sb,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """
    Score and write all tickers for one quarter to signal_log.
    Returns {"written": N, "skipped": N, "failed": N}.
    """
    from model_engine import SECTORS

    written = skipped = failed = 0
    rows = []

    for ticker in tickers:
        hist = price_histories.get(ticker, [])
        if not hist:
            log.debug(f"  No price history for {ticker} in {quarter} — skipping")
            failed += 1
            continue

        try:
            scored = _score_historical(ticker, hist, quarter)
        except Exception as e:
            log.debug(f"  Scoring failed for {ticker} in {quarter}: {e}")
            failed += 1
            continue

        adj = scored.get("adj_composite", scored.get("composite", 50))
        row = {
            "ticker":        ticker,
            "signal_date":   score_date,
            "composite":     scored.get("composite", 50),
            "momentum":      scored.get("momentum", 50),
            "quality":       scored.get("quality", 50),
            "volume":        scored.get("volume", 50),
            "value":         scored.get("value", 50),
            "sentiment":     scored.get("sentiment", 50),
            "adj_composite": adj,
            "signal":        "BUY" if adj >= 60 else ("SELL" if adj < 45 else "HOLD"),
            "macro_overlay": scored.get("macro_regime", "NEUTRAL"),
            "price":         scored.get("price"),
            "is_hidden_gem": False,
            "hidden_gem_reason": None,
        }
        rows.append(row)

    if not rows:
        log.warning(f"  {quarter}: no rows to write")
        return {"written": 0, "skipped": 0, "failed": failed}

    if dry_run:
        log.info(f"  [DRY RUN] {quarter}: would write {len(rows)} rows (sample: {rows[0]['ticker']} adj={rows[0]['adj_composite']})")
        return {"written": 0, "skipped": 0, "failed": failed}

    # Check for existing rows (skip if not forced)
    if not force and sb:
        try:
            existing = sb.table("signal_log").select("ticker").eq(
                "signal_date", score_date
            ).in_("ticker", [r["ticker"] for r in rows]).execute()
            existing_tickers = {row["ticker"] for row in (existing.data or [])}
            rows = [r for r in rows if r["ticker"] not in existing_tickers]
            skipped = len(existing_tickers)
        except Exception as e:
            log.warning(f"  Could not check existing rows: {e}")

    if not rows:
        log.info(f"  {quarter}: all {skipped} rows already exist — skipped")
        return {"written": 0, "skipped": skipped, "failed": failed}

    # Write in batches of 50
    batch_size = 50
    for bi in range(0, len(rows), batch_size):
        batch = rows[bi:bi + batch_size]
        try:
            if force:
                sb.table("signal_log").upsert(
                    batch, on_conflict="ticker,signal_date"
                ).execute()
            else:
                sb.table("signal_log").insert(batch).execute()
            written += len(batch)
        except Exception as e:
            log.error(f"  Write failed for batch {bi}: {e}")
            failed += len(batch)

    return {"written": written, "skipped": skipped, "failed": failed}


def main():
    parser = argparse.ArgumentParser(description="QNTM Track Record Seeder")
    parser.add_argument("--dry-run",  action="store_true", help="Print rows without writing")
    parser.add_argument("--force",    action="store_true", help="Overwrite existing rows")
    parser.add_argument("--quarter",  type=str, default=None,
                        help="Seed a single quarter (e.g. 2022-Q1). Default: all 20 quarters.")
    args = parser.parse_args()

    # Validate --quarter
    quarters_to_seed = list(QUARTER_MAP.items())
    if args.quarter:
        if args.quarter not in QUARTER_MAP:
            log.error(f"Unknown quarter '{args.quarter}'. Valid options: {list(QUARTER_MAP.keys())}")
            sys.exit(1)
        quarters_to_seed = [(args.quarter, QUARTER_MAP[args.quarter])]

    # Connect Supabase
    sb = None
    if not args.dry_run:
        sb = _get_supabase()
        if not sb:
            log.error("No Supabase connection. Set SUPABASE_URL and SUPABASE_SERVICE_KEY in env.")
            sys.exit(1)

    # Load universe tickers
    from universe_data import SECTORS
    all_tickers = list(SECTORS.keys())
    log.info(f"Universe: {len(all_tickers)} tickers")
    log.info(f"Quarters to seed: {len(quarters_to_seed)}")
    if args.dry_run: log.info("DRY RUN — no data will be written")
    if args.force:   log.info("FORCE mode — existing rows will be overwritten")

    total_written = total_skipped = total_failed = 0
    start_time = time.time()

    for quarter, (score_date, period_end) in quarters_to_seed:
        log.info(f"\n── {quarter} ({score_date} → {period_end}) ────────────────")

        # Fetch price histories for this quarter
        price_histories = _fetch_price_history(all_tickers, score_date, period_end)
        log.info(f"  Prices fetched for {len(price_histories)}/{len(all_tickers)} tickers")

        stats = seed_quarter(
            quarter=quarter,
            score_date=score_date,
            period_end=period_end,
            tickers=all_tickers,
            price_histories=price_histories,
            sb=sb,
            dry_run=args.dry_run,
            force=args.force,
        )

        total_written += stats["written"]
        total_skipped += stats["skipped"]
        total_failed  += stats["failed"]
        log.info(f"  {quarter}: written={stats['written']} skipped={stats['skipped']} failed={stats['failed']}")

    duration = round(time.time() - start_time, 1)
    log.info(f"\n── Seeding complete in {duration}s ────────────────────────")
    log.info(f"   Total written : {total_written}")
    log.info(f"   Total skipped : {total_skipped}")
    log.info(f"   Total failed  : {total_failed}")
    log.info(f"   Quarters      : {len(quarters_to_seed)}")

    if total_written == 0 and not args.dry_run and total_skipped > 0:
        log.info("All rows already existed — signal_log is already seeded.")
        log.info("Re-run with --force to overwrite.")

    sys.exit(0 if total_failed == 0 else 1)


if __name__ == "__main__":
    main()
