"""
QNTM — Seed the live model-portfolio cohort (forward track record).
================================================================================
Starts a fresh 50-stock model portfolio from TODAY's signals on the corrected
universe + fixed engine, tagged epoch='live'. This is the forward track record;
the prior cohort should already be sealed via freeze_inception.py.

  - Picks the highest adj_composite >= 60 names from today's signal_log
  - In the current universe only (out-of-universe names are skipped)
  - Equal-weighted $2,000 / position, target 50, 30% sector cap (15) via sector_of
  - entry_date = today, epoch = 'live'

Run order: migration -> freeze_inception.py --execute -> seed_live_portfolio.py --execute

    SUPABASE_URL='https://...' SUPABASE_SERVICE_KEY='...' python3 seed_live_portfolio.py
    SUPABASE_URL='https://...' SUPABASE_SERVICE_KEY='...' python3 seed_live_portfolio.py --execute
"""
import os, sys, argparse
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from universe_data import SECTORS, sector_of
from model_engine import MODEL_EPOCH, ENTRY_THRESHOLD

TARGET   = 50
POS_SIZE = 2000.0
SECT_CAP = 15          # 30% of 50


def _get_supabase():
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url:
        try:
            import toml
            s = toml.load(".streamlit/secrets.toml")
            s = s.get("default", s) if isinstance(s, dict) else s
            url = s.get("SUPABASE_URL", "")
        except Exception:
            pass
    if not url or not key:
        print("ERROR: set SUPABASE_URL and SUPABASE_SERVICE_KEY (service key) in the environment.")
        sys.exit(1)
    from supabase import create_client
    return create_client(url, key)


def _fetch_all(build, page=1000):
    rows, off = [], 0
    while True:
        b = build().range(off, off + page - 1).execute().data or []
        rows.extend(b)
        if len(b) < page:
            break
        off += page
    return rows


def main(execute: bool):
    sb = _get_supabase()
    today = date.today().isoformat()
    universe = set(SECTORS)

    # Guard: refuse to seed if a live cohort already exists (avoid double-seed).
    existing = sb.table("model_portfolio_positions").select("id") \
        .eq("epoch", MODEL_EPOCH).eq("is_active", True).limit(1).execute().data or []
    if existing:
        print(f"A live cohort (epoch='{MODEL_EPOCH}') already has active positions. "
              "Refusing to double-seed. Clear it first if you really mean to re-seed.")
        return

    # Latest scored day
    md = sb.table("signal_log").select("signal_date") \
        .order("signal_date", desc=True).limit(1).execute().data
    sig_date = md[0]["signal_date"] if md else today
    score_rows = _fetch_all(lambda: sb.table("signal_log")
        .select("ticker,adj_composite,composite,price").eq("signal_date", sig_date))

    candidates = sorted(
        [r for r in score_rows
         if r["ticker"] in universe
         and float(r.get("adj_composite") or 0) >= ENTRY_THRESHOLD
         and r.get("price")],
        key=lambda x: float(x.get("adj_composite") or 0), reverse=True)

    picks, sector_counts, blocked = [], {}, 0
    for r in candidates:
        if len(picks) >= TARGET:
            break
        tk = r["ticker"]
        s  = sector_of(tk)
        if sector_counts.get(s, 0) >= SECT_CAP:
            blocked += 1
            continue
        picks.append({"ticker": tk, "sector": s,
                      "price": float(r["price"]),
                      "score": round(float(r["adj_composite"]), 1)})
        sector_counts[s] = sector_counts.get(s, 0) + 1

    print(f"\nLive cohort seed (epoch='{MODEL_EPOCH}', inception {today}) — source signal_log @ {sig_date}")
    print(f"Candidates >= {ENTRY_THRESHOLD}: {len(candidates)}  |  selected: {len(picks)}/{TARGET}"
          + (f"  |  {blocked} skipped by 30% sector cap" if blocked else ""))
    print("\n=== PICKS ===")
    for p in picks:
        print(f"  {p['ticker']:6} {p['sector']:16} @ ${p['price']:.2f}  score {p['score']}")
    print("\n=== SECTOR BREAKDOWN ===")
    for s, c in sorted(sector_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {s:18} {c}{'  <-- AT CAP' if c >= SECT_CAP else ''}")
    print(f"  notional: ${POS_SIZE * len(picks):,.0f}  ($2,000 x {len(picks)})")

    if len(picks) < TARGET:
        print(f"\n  NOTE: only {len(picks)} names cleared the bar — fewer than {TARGET}. "
              "Seeding what qualifies; the cron fills remaining slots as names qualify.")

    if not execute:
        print("\nDRY RUN — no writes. Re-run with --execute to start the live cohort.")
        return

    print("\nWriting...")
    for p in picks:
        sb.table("model_portfolio_positions").insert({
            "ticker":        p["ticker"],
            "entry_date":    today,
            "entry_price":   p["price"],
            "entry_score":   p["score"],
            "position_size": POS_SIZE,
            "is_active":     True,
            "epoch":         MODEL_EPOCH,
        }).execute()
    print(f"Done. Live cohort started: {len(picks)} positions, epoch='{MODEL_EPOCH}', inception {today}.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="Write (default is a dry run)")
    main(execute=ap.parse_args().execute)
