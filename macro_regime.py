"""macro_regime.py - per-date macro drag reconstructed from signal_log.
macro_state holds only the CURRENT overlay (no history table exists), so the
historical regime is rebuilt from stored scores.
DRAG = mean(adj_composite) - mean(composite) across the universe on each
signal_date: the points the macro overlay added or removed. This is the exact
measure the 2026-07-17 mass-exit post-mortem used (composite flat, adj -4.46).
Sector tilts are already applied per name, so nothing cancels the way a mean of
raw macro_overlay does.
Trading days only - phantom weekend rows re-stamp Friday prices."""
from __future__ import annotations
import datetime as _dt
#
_CACHE = {}
#
def _sb():
    import factor_analysis as fa
    return fa._sb()
#
def _trading(d):
    import factor_analysis as fa
    try:
        return fa._is_trading_day(d)
    except Exception:
        return True
#
def drag_by_date(history_days=120, page=1000):
    """{date: (mean_adj - mean_composite)} in score points, trading days only."""
    key = ("drag", int(history_days))
    if key in _CACHE:
        return _CACHE[key]
    start = (_dt.date.today() - _dt.timedelta(days=int(history_days))).isoformat()
    sb = _sb()
    acc, lo = {}, 0
    while True:
        r = (sb.table("signal_log").select("signal_date,composite,adj_composite")
             .gte("signal_date", start).order("signal_date", desc=False)
             .range(lo, lo + page - 1).execute())
        batch = r.data or []
        for row in batch:
            d = str(row.get("signal_date"))[:10]
            c, a = row.get("composite"), row.get("adj_composite")
            if c is None or a is None:
                continue
            try:
                c, a = float(c), float(a)
            except (TypeError, ValueError):
                continue
            sc, sa, n = acc.get(d, (0.0, 0.0, 0))
            acc[d] = (sc + c, sa + a, n + 1)
        if len(batch) < page:
            break
        lo += page
    out = {d: (sa / n) - (sc / n)
           for d, (sc, sa, n) in acc.items() if n > 0 and _trading(d)}
    _CACHE[key] = out
    return out
#
def counts_by_date(history_days=120):
    return {d: 1 for d in drag_by_date(history_days)}
#
def risk_off_by_date(history_days=120, cutoff=0.0):
    """{date: True/False}. cutoff=0.0 means any net macro drag counts."""
    key = ("risk", int(history_days), float(cutoff))
    if key in _CACHE:
        return _CACHE[key]
    out = {d: (v < cutoff) for d, v in drag_by_date(history_days).items()}
    _CACHE[key] = out
    return out
#
def distribution(history_days=120):
    """Percentiles of the drag, so a cutoff is chosen against evidence."""
    v = sorted(drag_by_date(history_days).values())
    if not v:
        return {}
    def q(p):
        return v[min(len(v) - 1, max(0, int(round(p * (len(v) - 1)))))]
    return {"n": len(v), "min": v[0], "p10": q(.10), "p25": q(.25),
            "median": q(.50), "p75": q(.75), "p90": q(.90), "max": v[-1],
            "pct_negative": 100.0 * sum(1 for x in v if x < 0) / len(v)}
#
def clear_cache():
    _CACHE.clear()
#
if __name__ == "__main__":
    d = drag_by_date()
    dist = distribution()
    print("macro drag (mean adj - mean composite), trading days only")
    print("n=%(n)d  min %(min)+.2f  p10 %(p10)+.2f  p25 %(p25)+.2f  "
          "median %(median)+.2f  p75 %(p75)+.2f  p90 %(p90)+.2f  max %(max)+.2f"
          % dist)
    print("negative on %.0f%% of days" % dist["pct_negative"])
    print()
    for c in (0.0, -0.5, -1.0, -2.0, -3.0):
        n = sum(1 for v in d.values() if v < c)
        print("  cutoff %+5.1f -> risk-off on %3d / %d days (%3.0f%%)"
              % (c, n, len(d), 100.0 * n / len(d)))
    print()
    for k in sorted(d)[-14:]:
        print("  %s  drag %+7.3f" % (k, d[k]))
    assert d, "no rows returned"
    assert all(_trading(k) for k in d), "non-trading day leaked through"
    print("OK")
