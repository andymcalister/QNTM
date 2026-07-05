"""
force_exit_delisted.py — exit model-portfolio positions whose ticker left the
scored universe after a Russell reconstitution.

Dropped names no longer receive conviction scores, so the normal SELL_SIGNAL
exit (adj_composite < 45) can never fire for them — they'd sit in the book
forever, un-updated. This force-exits them at their last known close with
exit_reason=RECONSTITUTION, so realized P&L sticks and the ledger stays honest.

Dry-run by default. Re-run with --commit to actually write.

    python force_exit_delisted.py            # show what would exit
    python force_exit_delisted.py --commit   # exit them
"""
import logging
import sys
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("qntm.forceexit")


def _last_price(sb, ticker):
    try:
        r = (sb.table("signal_log").select("price,signal_date")
             .eq("ticker", ticker).not_.is_("price", "null")
             .order("signal_date", desc=True).limit(1).execute().data or [])
        return float(r[0]["price"]) if r and r[0].get("price") is not None else None
    except Exception as e:
        log.warning("price lookup failed for %s: %s", ticker, e)
        return None


def main():
    commit = "--commit" in sys.argv
    from data_refresh import _get_supabase
    from universe_data import SECTORS
    sb = _get_supabase()
    if not sb:
        log.error("no supabase client"); sys.exit(1)

    positions = (sb.table("model_portfolio_positions")
                 .select("id,ticker,entry_price,entry_date")
                 .eq("is_active", True).eq("epoch", "live").execute().data or [])
    delisted = [p for p in positions if (p.get("ticker") or "").upper() not in SECTORS]
    log.info("%d active positions; %d no longer in the universe", len(positions), len(delisted))
    if not delisted:
        log.info("Nothing to exit — every holding is still in the universe.")
        return

    today = date.today().isoformat()
    for p in delisted:
        tk = (p.get("ticker") or "").upper()
        px = _last_price(sb, tk)
        entry = p.get("entry_price")
        try:
            pnl = f"{(px / entry - 1) * 100:+.1f}%" if (px and entry) else "n/a"
        except Exception:
            pnl = "n/a"
        log.info("  %-6s entry=%s  last=%s  P&L=%s", tk, entry, px, pnl)
        if commit:
            sb.table("model_portfolio_positions").update({
                "is_active": False, "exit_date": today, "exit_price": px,
                "exit_score": None, "exit_reason": "RECONSTITUTION",
            }).eq("id", p["id"]).execute()

    if commit:
        log.info("Force-exited %d delisted position(s) at last known close.", len(delisted))
    else:
        log.info("[DRY RUN] re-run with --commit to exit these %d position(s).", len(delisted))


if __name__ == "__main__":
    main()
