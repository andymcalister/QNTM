"""backfill_benchmark.py - fill gaps in benchmark_price (SPY closes).
The signal record starts 2026-06-12 but benchmark_price starts 2026-06-22, so
every episode before that has no SPY baseline and drops out of any relative
calculation.
MUST RUN ON THE RENDER SHELL - Supabase writes need the service_role key. On a
local anon key the write RLS-fails SILENTLY and still returns HTTP 200, which is
why this self-verifies by re-reading the rows afterwards.
Dry run by default. Add --write to commit.
    python3 backfill_benchmark.py                # show gaps, write nothing
    python3 backfill_benchmark.py --write        # insert
    python3 backfill_benchmark.py --write --start 2026-06-01
"""
from __future__ import annotations
import sys
import datetime as dt
#
TABLE = "benchmark_price"
SYMBOL = "SPY"
DEFAULT_START = "2026-06-01"
#
def _sb():
    from data_refresh import _get_supabase
    return _get_supabase()
#
def existing(sb):
    out, lo, page = {}, 0, 1000
    while True:
        r = (sb.table(TABLE).select("d,close")
             .order("d", desc=False).range(lo, lo + page - 1).execute())
        b = r.data or []
        for row in b:
            d, c = row.get("d"), row.get("close")
            if d is None or c is None:
                continue
            try:
                out[str(d)[:10]] = float(c)
            except (TypeError, ValueError):
                pass
        if len(b) < page:
            break
        lo += page
    return out
#
def wanted_days(start, end):
    from market_calendar import is_trading_day
    days, cur = [], dt.date.fromisoformat(start)
    stop = dt.date.fromisoformat(end)
    while cur <= stop:
        iso = cur.isoformat()
        try:
            ok = is_trading_day(cur)
        except TypeError:
            ok = is_trading_day(iso)
        if ok:
            days.append(iso)
        cur += dt.timedelta(days=1)
    return days
#
def fetch_closes(start, end):
    import time
    import yfinance as yf
    last = None
    for attempt in range(3):
        try:
            df = yf.Ticker(SYMBOL).history(
                start=start,
                end=(dt.date.fromisoformat(end) + dt.timedelta(days=1)).isoformat(),
                auto_adjust=False)
            if df is not None and not df.empty:
                return {str(ix.date()): float(v)
                        for ix, v in df["Close"].items() if v == v}
            last = "empty frame"
        except Exception as e:
            last = repr(e)[:120]
        time.sleep(25 * (attempt + 1))
    raise RuntimeError("yfinance failed after retries: %s" % last)
#
def main():
    args = sys.argv[1:]
    do_write = "--write" in args
    start = DEFAULT_START
    if "--start" in args:
        start = args[args.index("--start") + 1]
    sb = _sb()
    have = existing(sb)
    if have:
        print("benchmark_price currently %d rows, %s .. %s"
              % (len(have), min(have), max(have)))
    else:
        print("benchmark_price is EMPTY")
    end = max(have) if have else dt.date.today().isoformat()
    want = wanted_days(start, end)
    missing = [d for d in want if d not in have]
    print("trading days %s .. %s: %d wanted, %d missing"
          % (start, end, len(want), len(missing)))
    if not missing:
        print("nothing to do")
        return
    print("missing:", ", ".join(missing))
    closes = fetch_closes(min(missing), max(missing))
    payload = [{"d": d, "close": round(closes[d], 4)}
               for d in missing if d in closes]
    unresolved = [d for d in missing if d not in closes]
    if unresolved:
        print("NO PRICE from yfinance for:", ", ".join(unresolved))
    for row in payload:
        print("  %s  %.4f" % (row["d"], row["close"]))
    if not do_write:
        print("\nDRY RUN - %d rows ready. Re-run with --write on the RENDER shell."
              % len(payload))
        return
    if not payload:
        print("nothing fetched, aborting")
        return
    sb.table(TABLE).upsert(payload, on_conflict="d").execute()
    after = existing(sb)
    landed = [r["d"] for r in payload if r["d"] in after]
    failed = [r["d"] for r in payload if r["d"] not in after]
    print("\nVERIFY: %d/%d rows present after write" % (len(landed), len(payload)))
    if failed:
        print("FAILED (silent RLS block? are you on Render with service_role?):",
              ", ".join(failed))
        sys.exit(1)
    print("benchmark_price now %d rows, %s .. %s"
          % (len(after), min(after), max(after)))
    print("OK")
#
if __name__ == "__main__":
    main()
