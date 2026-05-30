"""
QNTM — Backfill price_at_add for existing watchlist_items
=========================================================
Existing watchlist tickers (migrated from the old flat table) have no
price_at_add baseline, so "% since added" can't be computed for them.

This script fills price_at_add from the most recent signal_log price for
each ticker that's currently missing one.

Run once locally:
    python backfill_watchlist_prices.py
    python backfill_watchlist_prices.py --dry-run

Requires SUPABASE_URL + SUPABASE_SERVICE_KEY in env or .streamlit/secrets.toml
"""
import os, sys, argparse, logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("qntm.backfill")


def get_supabase():
    from supabase import create_client
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")
    if not url:
        try:
            import toml
            s = toml.load(".streamlit/secrets.toml")
            if "default" in s and isinstance(s["default"], dict):
                s = s["default"]
            url = s.get("SUPABASE_URL", "")
            key = s.get("SUPABASE_SERVICE_KEY") or s.get("SUPABASE_ANON_KEY", "")
        except Exception:
            pass
    if not url or not key:
        log.error("No Supabase credentials. Set SUPABASE_URL + SUPABASE_SERVICE_KEY.")
        sys.exit(1)
    return create_client(url, key)


def latest_price(sb, ticker: str):
    resp = sb.table("signal_log").select("price") \
        .eq("ticker", ticker).order("signal_date", desc=True).limit(1).execute()
    if resp.data and resp.data[0].get("price"):
        return float(resp.data[0]["price"])
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sb = get_supabase()

    # Pull items missing a price_at_add
    resp = sb.table("watchlist_items").select("id,ticker,price_at_add").execute()
    items = resp.data or []
    missing = [it for it in items if not it.get("price_at_add")]
    log.info(f"{len(items)} total items · {len(missing)} missing price_at_add")

    if not missing:
        log.info("Nothing to backfill.")
        return

    updated = skipped = 0
    for it in missing:
        px = latest_price(sb, it["ticker"])
        if not px:
            log.warning(f"  {it['ticker']}: no signal_log price — skipped")
            skipped += 1
            continue
        if args.dry_run:
            log.info(f"  [DRY] {it['ticker']}: would set price_at_add={px:.2f}")
            updated += 1
            continue
        sb.table("watchlist_items").update(
            {"price_at_add": round(px, 4)}
        ).eq("id", it["id"]).execute()
        log.info(f"  {it['ticker']}: price_at_add={px:.2f}")
        updated += 1

    log.info(f"\nDone. Updated {updated}, skipped {skipped}"
             + (" (dry run — nothing written)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
