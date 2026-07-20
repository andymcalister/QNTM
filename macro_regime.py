"""macro_regime.py - per-date macro regime derived from stored signal_log rows.
macro_state holds only the CURRENT overlay, so historical regime is reconstructed
from the universe-mean macro_overlay on each signal_date.
Definition is deliberately parameter-free: mean overlay < 0 means the macro
overlay was a net drag that day = risk-off. No tunable cutoff, so this cannot be
fitted to make any downstream comparison look better."""
from __future__ import annotations
import datetime as _dt
#
_CACHE = {}
#
def _sb():
    import factor_analysis as fa
    return fa._sb()
#
def mean_overlay_by_date(history_days=120, page=1000):
    """{date: mean macro_overlay} across the whole scored universe."""
    key = ("mean", int(history_days))
    if key in _CACHE:
        return _CACHE[key]
    start = (_dt.date.today() - _dt.timedelta(days=int(history_days))).isoformat()
    sb = _sb()
    acc, lo = {}, 0
    while True:
        r = (sb.table("signal_log").select("signal_date,macro_overlay")
             .gte("signal_date", start).order("signal_date", desc=False)
             .range(lo, lo + page - 1).execute())
        batch = r.data or []
        for row in batch:
            d = str(row.get("signal_date"))[:10]
            v = row.get("macro_overlay")
            if v is None:
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            s, n = acc.get(d, (0.0, 0))
            acc[d] = (s + v, n + 1)
        if len(batch) < page:
            break
        lo += page
    out = {d: (s / n) for d, (s, n) in acc.items() if n > 0}
    _CACHE[key] = out
    return out
#
def risk_off_by_date(history_days=120):
    """{date: True/False} - True when the macro overlay was a net drag."""
    key = ("risk", int(history_days))
    if key in _CACHE:
        return _CACHE[key]
    out = {d: (m < 0.0) for d, m in mean_overlay_by_date(history_days).items()}
    _CACHE[key] = out
    return out
#
def summary(history_days=120):
    m = mean_overlay_by_date(history_days)
    r = risk_off_by_date(history_days)
    n_on = sum(1 for v in r.values() if v)
    return {"days": len(m), "risk_off_days": n_on,
            "pct": (100.0 * n_on / len(m)) if m else 0.0,
            "first": min(m) if m else None, "last": max(m) if m else None}
#
def clear_cache():
    _CACHE.clear()
#
if __name__ == "__main__":
    s = summary()
    print("macro regime: %d days, risk-off on %d (%.0f%%), %s .. %s"
          % (s["days"], s["risk_off_days"], s["pct"], s["first"], s["last"]))
    m = mean_overlay_by_date()
    for d in sorted(m)[-14:]:
        print("  %s  mean_overlay %+7.3f   risk_off=%s" % (d, m[d], m[d] < 0))
    assert s["days"] > 0, "no macro_overlay data returned"
    print("OK")
