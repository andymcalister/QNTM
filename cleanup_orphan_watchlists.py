"""
QNTM — one-time orphan watchlist cleanup
========================================
Removes watchlist_items whose ticker is no longer in the scored universe
(universe_data.SECTORS). The app already prunes these per-user on login
(_prune_orphan_watchlist_items), but that is lazy — it only runs when a user
logs in. This script clears EVERY user at once (including inactive ones) right
after a universe rebuild, so nobody is left tracking a stale name.

Holdings are intentionally NOT deleted (they carry cost basis); their orphan
count is reported read-only so you can decide on them separately.

Usage (Render shell — stage secrets first:
       mkdir -p .streamlit && cp /etc/secrets/secrets.toml .streamlit/secrets.toml):
    python cleanup_orphan_watchlists.py --dry-run   # report blast radius, delete nothing
    python cleanup_orphan_watchlists.py             # actually delete

Safety: refuses to run if universe_data.SECTORS imports empty (which would
otherwise wipe every watchlist). Idempotent — safe to run more than once.
"""
import sys
import logging
from collections import Counter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("qntm.wl_cleanup")

PAGE = 1000


def _all_rows(sb, table, cols):
    rows, off = [], 0
    while True:
        chunk = (sb.table(table).select(cols)
                 .range(off, off + PAGE - 1).execute().data or [])
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        off += PAGE
    return rows


def run(dry_run=False):
    try:
        from universe_data import SECTORS as UNI
    except Exception as e:
        log.error("cannot import universe_data.SECTORS: %s", e)
        return
    if not UNI:
        log.error("universe is EMPTY — refusing to run (would delete every watchlist).")
        return
    log.info("scored universe: %d tickers", len(UNI))

    try:
        from data_refresh import _get_supabase
    except Exception as e:
        log.error("cannot import _get_supabase: %s", e)
        return
    sb = _get_supabase()
    if not sb:
        log.error("no supabase service client — stage secrets first "
                  "(mkdir -p .streamlit && cp /etc/secrets/secrets.toml .streamlit/secrets.toml).")
        return

    # ── Watchlist orphans ──────────────────────────────────────────────────────
    items = _all_rows(sb, "watchlist_items", "id,ticker,user_id")
    log.info("watchlist_items total: %d", len(items))
    orphans = [r for r in items
               if (r.get("ticker") or "").strip().upper() not in UNI]
    by_tkr = Counter((r.get("ticker") or "").strip().upper() for r in orphans)
    users = {r.get("user_id") for r in orphans}
    log.info("watchlist orphans: %d rows · %d users · %d distinct tickers",
             len(orphans), len(users), len(by_tkr))
    for tk, n in by_tkr.most_common(60):
        log.info("   %-8s x%d", tk, n)

    # ── Holdings orphans (REPORT ONLY — never deleted) ─────────────────────────
    try:
        hold = _all_rows(sb, "holdings", "id,ticker,user_id")
        h_orph = [r for r in hold
                  if (r.get("ticker") or "").strip().upper() not in UNI]
        log.info("holdings orphans (NOT deleted): %d rows · %d users",
                 len(h_orph), len({r.get("user_id") for r in h_orph}))
        if h_orph:
            hc = Counter((r.get("ticker") or "").strip().upper() for r in h_orph)
            log.info("   held stale names: %s",
                     ", ".join(f"{t}x{n}" for t, n in hc.most_common(20)))
    except Exception as e:
        log.info("holdings check skipped: %s", e)

    if dry_run:
        log.info("[DRY RUN] nothing deleted. Re-run without --dry-run to remove "
                 "%d watchlist rows.", len(orphans))
        return
    if not orphans:
        log.info("nothing to delete — all watchlists are clean.")
        return

    ids = [r["id"] for r in orphans if r.get("id") is not None]
    deleted = 0
    for i in range(0, len(ids), 200):
        batch = ids[i:i + 200]
        try:
            sb.table("watchlist_items").delete().in_("id", batch).execute()
            deleted += len(batch)
        except Exception as e:
            log.error("delete batch failed (%d ids): %s", len(batch), e)
    log.info("DONE — deleted %d orphaned watchlist rows across %d users.",
             deleted, len(users))


if __name__ == "__main__":
    run(dry_run=("--dry-run" in sys.argv))
