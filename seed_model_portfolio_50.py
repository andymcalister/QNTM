"""
QNTM — Seed 50-Stock Model Portfolio
=====================================
Builds a 50-stock portfolio seeded across May 19-23, 2026:
  - ~10 stocks per day (Mon–Fri)
  - Takes the highest scoring HIGH conviction (adj_composite >= 60) signals
    from signal_log for each date, skipping any already in the portfolio
  - Equal-weighted $10,000 per position
  - Replaces existing active model_portfolio_positions

Run once:
    python seed_model_portfolio_50.py
    python seed_model_portfolio_50.py --dry-run
    python seed_model_portfolio_50.py --force   # re-seed even if positions exist
"""

import os, sys, argparse, logging
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("qntm.seed50")

# Target: 10 entries per day across 5 days = 50 total
SEED_DATES = ["2026-05-19","2026-05-20","2026-05-21","2026-05-22","2026-05-23"]
TOTAL      = 50
POS_SIZE   = 2000.0


def get_supabase():
    from supabase import create_client
    url = os.getenv("SUPABASE_URL","")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_ANON_KEY","")
    if not url:
        try:
            import streamlit as st
            url = st.secrets.get("SUPABASE_URL","")
            key = st.secrets.get("SUPABASE_SERVICE_KEY") or st.secrets.get("SUPABASE_ANON_KEY","")
        except Exception:
            pass
    if url and key:
        return create_client(url, key)
    raise RuntimeError("No Supabase credentials found")


def fetch_high_conviction(sb, signal_date: str, exclude: set, cap: int = 999) -> list:
    """Return ALL HIGH conviction tickers for a date, excluding already-held ones.
    
    Monday: returns everything scored >= 60 (up to cap)
    Tue-Fri: returns new entries not already in portfolio (up to cap remaining slots)
    """
    resp = sb.table("signal_log") \
        .select("ticker,adj_composite,composite,price,momentum,quality,volume,value,sentiment") \
        .eq("signal_date", signal_date) \
        .gte("adj_composite", 60) \
        .order("adj_composite", desc=True) \
        .limit(cap + len(exclude) + 20) \
        .execute()
    rows = [r for r in (resp.data or []) if r["ticker"] not in exclude]
    return rows[:cap]


def fetch_price_on_date(sb, ticker: str, signal_date: str):
    """Get the closing price for a ticker on a specific date from signal_log."""
    resp = sb.table("signal_log") \
        .select("price") \
        .eq("ticker", ticker) \
        .eq("signal_date", signal_date) \
        .limit(1) \
        .execute()
    if resp.data and resp.data[0].get("price"):
        return float(resp.data[0]["price"])
    return None


SECTOR_CAP_PCT = 0.30   # max 30% of portfolio in any one sector
MAX_SECTOR     = int(TOTAL * SECTOR_CAP_PCT)   # = 15 positions


# Load SECTORS from universe_data.py (same directory as this script)
_SECTOR_CACHE: dict = {}

def load_sector_cache(sb=None) -> None:
    """Load sector data from universe_data.py."""
    global _SECTOR_CACHE
    if _SECTOR_CACHE:
        return
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from universe_data import SECTORS
        _SECTOR_CACHE = dict(SECTORS)
        log.info(f"Loaded {len(_SECTOR_CACHE)} sectors from universe_data.py")
    except Exception as e:
        log.warning(f"Could not load universe_data: {e} — sector cap disabled")


def get_ticker_sector(ticker: str) -> str:
    return _SECTOR_CACHE.get(ticker, "Unknown")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force",   action="store_true")
    args = parser.parse_args()

    sb = get_supabase()

    # Check existing positions
    existing = sb.table("model_portfolio_positions").select("id,ticker").eq("is_active", True).execute()
    n_existing = len(existing.data or [])
    if n_existing > 0 and not args.force:
        log.info(f"{n_existing} active positions already exist. Use --force to reseed.")
        # Just show what's there
        for r in (existing.data or [])[:5]:
            log.info(f"  {r['ticker']}")
        sys.exit(0)

    if args.force and n_existing > 0:
        log.info(f"Force mode — deactivating {n_existing} existing positions...")
        if not args.dry_run:
            sb.table("model_portfolio_positions") \
                .update({"is_active": False, "exit_reason": "reseeded"}) \
                .eq("is_active", True) \
                .execute()

    # Load sector data from signal_log
    load_sector_cache(sb)

    portfolio: list[dict]      = []
    entered_tickers: set       = set()
    sector_counts: dict        = {}   # sector -> count

    for i, signal_date in enumerate(SEED_DATES):
        remaining = TOTAL - len(portfolio)
        if remaining <= 0:
            break

        day_name = ["Monday","Tuesday","Wednesday","Thursday","Friday"][i]
        log.info(f"\n── {signal_date} ({day_name}) — {remaining} slots remaining ──")

        # Show current sector distribution
        if sector_counts:
            top_sectors = sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            log.info(f"  Sector counts: {dict(top_sectors)}")

        # Fetch ALL high conviction stocks for this date, up to remaining slots
        # Fetch extra to account for sector cap rejections
        rows = fetch_high_conviction(sb, signal_date, entered_tickers, cap=remaining * 3)

        if not rows:
            log.warning(f"  No new HIGH conviction signals for {signal_date}")
            continue

        added = 0
        skipped_sector = 0
        for r in rows:
            if len(portfolio) >= TOTAL:
                break

            tk     = r["ticker"]
            score  = float(r.get("adj_composite") or r.get("composite") or 60)
            price  = r.get("price")
            sector = get_ticker_sector(tk) or "Unknown"

            if not price:
                log.info(f"  ✗ {tk}: no price, skipping")
                continue

            # Enforce 30% sector cap
            current_sector_count = sector_counts.get(sector, 0)
            if current_sector_count >= MAX_SECTOR:
                log.info(f"  ✗ {tk} ({sector}): sector cap {current_sector_count}/{MAX_SECTOR}, skipping")
                skipped_sector += 1
                continue

            portfolio.append({
                "ticker":        tk,
                "entry_date":    signal_date,
                "entry_price":   float(price),
                "entry_score":   round(score, 1),
                "position_size": POS_SIZE,
                "is_active":     True,
            })
            entered_tickers.add(tk)
            sector_counts[sector] = current_sector_count + 1
            added += 1
            log.info(f"  ✓ {tk} ({sector}): score={score:.0f}, ${price:.2f}")

        if skipped_sector:
            log.info(f"  Skipped {skipped_sector} due to 30% sector cap")
        log.info(f"  Added {added} · Portfolio: {len(portfolio)}/{TOTAL}")

    # Log final sector breakdown
    log.info(f"\n── Final sector breakdown ──────────────────────────")
    for sec, cnt in sorted(sector_counts.items(), key=lambda x: x[1], reverse=True):
        pct = cnt / max(len(portfolio), 1) * 100
        log.info(f"  {sec}: {cnt} positions ({pct:.0f}%)")

    log.info(f"\n── Summary: {len(portfolio)} positions across {len(SEED_DATES)} days ──")

    if args.dry_run:
        log.info("[DRY RUN] No data written.")
        for p in portfolio:
            log.info(f"  {p['entry_date']} {p['ticker']} ${p['entry_price']:.2f} score={p['entry_score']}")
        sys.exit(0)

    # Write to Supabase
    batch_size = 25
    written = 0
    for i in range(0, len(portfolio), batch_size):
        batch = portfolio[i:i+batch_size]
        sb.table("model_portfolio_positions").insert(batch).execute()
        written += len(batch)
        log.info(f"  Wrote batch {i//batch_size + 1}: {written}/{len(portfolio)}")

    log.info(f"\n✓ Seeded {written} positions into model_portfolio_positions")
    log.info("Run the app and navigate to Model Portfolio to see the results.")


if __name__ == "__main__":
    main()
