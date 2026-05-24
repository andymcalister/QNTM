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
PER_DAY    = 10
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


def fetch_top_signals(sb, signal_date: str, exclude: set, limit: int) -> list:
    """Return top HIGH conviction tickers from signal_log for a given date."""
    resp = sb.table("signal_log") \
        .select("ticker,adj_composite,composite,price,momentum,quality,volume,value,sentiment") \
        .eq("signal_date", signal_date) \
        .gte("adj_composite", 60) \
        .order("adj_composite", desc=True) \
        .limit(limit + len(exclude) + 20) \
        .execute()
    rows = [r for r in (resp.data or []) if r["ticker"] not in exclude]
    return rows[:limit]


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

    portfolio: list[dict] = []
    entered_tickers: set  = set()

    for signal_date in SEED_DATES:
        remaining = TOTAL - len(portfolio)
        if remaining <= 0:
            break
        daily_target = min(PER_DAY, remaining)

        log.info(f"\n── {signal_date} — targeting {daily_target} new entries ──")
        rows = fetch_top_signals(sb, signal_date, entered_tickers, daily_target)

        if not rows:
            log.warning(f"  No HIGH conviction signals found for {signal_date}")
            continue

        for r in rows:
            tk    = r["ticker"]
            score = float(r.get("adj_composite") or r.get("composite") or 60)
            price = r.get("price")

            if not price:
                log.warning(f"  {tk}: no price on {signal_date}, skipping")
                continue

            entry = {
                "ticker":        tk,
                "entry_date":    signal_date,
                "entry_price":   float(price),
                "entry_score":   round(score, 1),
                "position_size": POS_SIZE,
                "is_active":     True,
            }
            portfolio.append(entry)
            entered_tickers.add(tk)
            log.info(f"  ✓ {tk}: score={score:.0f}, entry=${price:.2f}")

        log.info(f"  Portfolio size: {len(portfolio)}/{TOTAL}")

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
