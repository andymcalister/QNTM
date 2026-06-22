"""
QNTM — Exit out-of-universe holdings and redeploy into current top picks.
================================================================================
The universe expansion to 1,402 (Russell 1000 + top-400 Russell 2000) dropped
names the model portfolio was holding from the May seed. This script:

  1. Finds active positions whose ticker is no longer in the screening universe
     (SECTORS), EXCLUDING the KEEP set — STX and CTRA are legitimate Russell 1000
     names that are merely missing from the iShares source file and will rejoin
     the universe at the June 26 reconstitution rebuild, so we hold them.
  2. Exits the genuinely-dropped names at current market price, tagged
     exit_reason='UNIVERSE_DROP' (a methodology exit, NOT a conviction-collapse
     SELL_SIGNAL — kept distinct so the track record reads honestly).
  3. Redeploys the freed slots into the highest-conviction names in the current
     universe (adj_composite >= 60, not already held), respecting the 30% sector
     cap (15 / 50). Retained out-of-universe holds (STX/CTRA) count toward their
     true sector via sector_of(), so the cap math is correct through the swap.

This is a deliberate, one-off rebalance — it does NOT use update_model_portfolio's
auto circuit breaker (which would refuse a 14-name exit as a data artifact).
It only ever exits the specific out-of-universe names, so it cannot run away.

DRY RUN by default. Review the plan, then re-run with --execute to write.

    SUPABASE_URL='https://...' SUPABASE_SERVICE_KEY='...' python3 exit_and_redeploy.py
    SUPABASE_URL='https://...' SUPABASE_SERVICE_KEY='...' python3 exit_and_redeploy.py --execute
"""
import os, sys, argparse
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from universe_data import SECTORS, sector_of

TARGET       = 50
POS_SIZE     = 2000.0
SECT_CAP     = 15          # 30% of 50
ENTRY_THRESH = 60.0        # High Conviction
KEEP         = {"STX", "CTRA"}   # legit R1000 names missing from source; rejoin at reconstitution


def _get_supabase():
    """Service key REQUIRED — writes against an anon key fail RLS silently, which
    is exactly the trap that ate an earlier run. Refuse to proceed without it."""
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
        print("ERROR: set SUPABASE_URL and SUPABASE_SERVICE_KEY (service key, not anon) "
              "in the environment. Writes need the service role.")
        sys.exit(1)
    from supabase import create_client
    return create_client(url, key)


def _fetch_all(build, page=1000):
    """Page past the ~1000-row Supabase cap. build() returns a fresh query
    builder without .range()/.execute()."""
    rows, off = [], 0
    while True:
        batch = build().range(off, off + page - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        off += page
    return rows


def _live_price(ticker):
    """Current market price for an exit fill. Live last → recent close → None."""
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        try:
            p = float(tk.fast_info.last_price)
            if p and p > 0:
                return p
        except Exception:
            pass
        h = tk.history(period="5d")
        if len(h):
            return float(h["Close"].iloc[-1])
    except Exception:
        pass
    return None


def main(execute: bool):
    sb    = _get_supabase()
    today = date.today().isoformat()
    universe = set(SECTORS)

    # ── Active positions ──────────────────────────────────────────────────────
    active = sb.table("model_portfolio_positions") \
        .select("id,ticker,entry_date,entry_price,entry_score") \
        .eq("is_active", True).execute().data or []
    active_tickers = {p["ticker"] for p in active}

    out_of_universe = active_tickers - universe
    to_exit  = sorted(out_of_universe - KEEP)
    held_oos = sorted(out_of_universe & KEEP)

    print(f"\nActive positions: {len(active_tickers)}/{TARGET}")
    print(f"Out of universe:  {len(out_of_universe)}  -> exiting {len(to_exit)}, "
          f"holding {held_oos} (rejoin at reconstitution)")
    if not to_exit:
        print("Nothing to exit — portfolio is clean. Done.")
        return

    # ── Latest scored day (source for exit prices fallback + redeploy ranking) ──
    md = sb.table("signal_log").select("signal_date") \
        .order("signal_date", desc=True).limit(1).execute().data
    sig_date = md[0]["signal_date"] if md else today
    score_rows = _fetch_all(lambda: sb.table("signal_log")
        .select("ticker,adj_composite,composite,price").eq("signal_date", sig_date))
    score_map = {r["ticker"]: r for r in score_rows}
    print(f"Ranking source: signal_log @ {sig_date} ({len(score_rows)} rows)")

    # ── Plan exits ──────────────────────────────────────────────────────────────
    pos_by_ticker = {p["ticker"]: p for p in active}
    exits = []
    for tk in to_exit:
        p  = pos_by_ticker[tk]
        sc = score_map.get(tk)
        px, src = _live_price(tk), "live"
        if px is None and sc and sc.get("price"):
            px, src = float(sc["price"]), "last signal_log"
        if px is None and p.get("entry_price"):
            px, src = float(p["entry_price"]), "entry (est)"
        ep  = float(p["entry_price"]) if p.get("entry_price") is not None else None
        ret = ((px / ep - 1.0) * 100.0) if (px and ep) else None
        xsc = (round(float(sc["adj_composite"]), 1)
               if sc and sc.get("adj_composite") is not None else None)
        exits.append({"id": p["id"], "ticker": tk, "sector": sector_of(tk),
                      "entry": ep, "exit": px, "src": src, "ret": ret, "exit_score": xsc})

    # ── Plan redeploy ────────────────────────────────────────────────────────────
    remaining = active_tickers - set(to_exit)               # what we still hold
    sector_counts = {}
    for tk in remaining:
        s = sector_of(tk)
        sector_counts[s] = sector_counts.get(s, 0) + 1
    slots = TARGET - len(remaining)

    candidates = sorted(
        [r for r in score_rows
         if r["ticker"] in universe
         and r["ticker"] not in remaining
         and float(r.get("adj_composite") or 0) >= ENTRY_THRESH
         and r.get("price")],
        key=lambda x: float(x.get("adj_composite") or 0), reverse=True)

    entries, blocked = [], 0
    for r in candidates:
        if len(entries) >= slots:
            break
        tk = r["ticker"]
        s  = sector_of(tk)
        if sector_counts.get(s, 0) >= SECT_CAP:
            blocked += 1
            continue
        entries.append({"ticker": tk, "sector": s,
                        "price": float(r["price"]),
                        "score": round(float(r["adj_composite"]), 1)})
        sector_counts[s] = sector_counts.get(s, 0) + 1
        remaining.add(tk)

    # ── Report ────────────────────────────────────────────────────────────────
    print("\n=== EXITS (UNIVERSE_DROP) ===")
    realized = 0.0
    for e in exits:
        r = f"{e['ret']:+.1f}%" if e["ret"] is not None else "  n/a"
        ep = f"${e['entry']:.2f}" if e["entry"] is not None else "  n/a"
        xp = f"${e['exit']:.2f}" if e["exit"] is not None else "  n/a"
        if e["ret"] is not None:
            realized += POS_SIZE * (e["ret"] / 100.0)
        print(f"  {e['ticker']:6} {e['sector']:16} entry {ep:>8} -> exit {xp:>8}  {r:>8}  ({e['src']})")
    print(f"  realized P/L on exits: ${realized:,.0f}  | cash freed: ${POS_SIZE*len(exits):,.0f}")

    print(f"\n=== REDEPLOY ({len(entries)} of {slots} open slots) ===")
    for en in entries:
        print(f"  {en['ticker']:6} {en['sector']:16} @ ${en['price']:.2f}  score {en['score']}")
    if blocked:
        print(f"  ({blocked} higher-ranked candidates skipped by the 30% sector cap)")
    if len(entries) < slots:
        print(f"  {slots - len(entries)} slot(s) left open — no qualifying names under the cap")

    print("\n=== RESULTING SECTOR BREAKDOWN ===")
    for s, c in sorted(sector_counts.items(), key=lambda x: x[1], reverse=True):
        flag = "  <-- AT CAP" if c >= SECT_CAP else ""
        print(f"  {s:18} {c}{flag}")
    print(f"  final active: {len(remaining)}/{TARGET}")

    if not execute:
        print("\nDRY RUN — no writes. Re-run with --execute to commit.")
        return

    # ── Commit ────────────────────────────────────────────────────────────────
    print("\nWriting exits...")
    for e in exits:
        sb.table("model_portfolio_positions").update({
            "is_active":   False,
            "exit_date":   today,
            "exit_price":  e["exit"],
            "exit_score":  e["exit_score"],
            "exit_reason": "UNIVERSE_DROP",
        }).eq("id", e["id"]).execute()
    print(f"  exited {len(exits)}")

    print("Writing entries...")
    for en in entries:
        sb.table("model_portfolio_positions").insert({
            "ticker":        en["ticker"],
            "entry_date":    today,
            "entry_price":   en["price"],
            "entry_score":   en["score"],
            "position_size": POS_SIZE,
            "is_active":     True,
        }).execute()
    print(f"  entered {len(entries)}")
    print(f"\nDone. Portfolio now {len(remaining)}/{TARGET} active.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true",
                    help="Write the exits/entries (default is a dry run)")
    args = ap.parse_args()
    main(execute=args.execute)
