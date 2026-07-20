"""shadow_headtohead.py - live adj_composite vs shadow_composite, head to head.
Read-only. Imports factor_analysis internals rather than duplicating the IC
math, so both sides are measured identically.
The honest test is the PAIRED DAILY DIFFERENCE (shadow IC minus live IC on the
same date), not two independent means - the two series share the same universe
and the same market shocks, so the difference cancels most of that common
variance. Significance is overlap-corrected via ic_stats."""
from __future__ import annotations
import datetime as _dt
import math
#
import factor_analysis as fa
import ic_stats
#
COLS = ["adj_composite", "shadow_composite"]
#
def _load_rows(history_days=120):
    """Rebuild the same rows/bench ic_report uses, with shadow attached."""
    start = (_dt.date.today() - _dt.timedelta(days=int(history_days))).isoformat()
    sb = fa._sb()
    loaded = fa._load(sb, start)
    assert isinstance(loaded, (tuple, list)) and len(loaded) == 2, \
        "unexpected _load return shape: %r" % (type(loaded),)
    rows, bench = loaded
    assert rows, "no signal_log rows returned since %s" % start
    assert bench, "no benchmark_price rows returned since %s" % start
    from shadow import _market_states as _ms, shadow_composite as _shadow
    dts = sorted({str(r["signal_date"])[:10] for r in rows})
    states = _ms(bench, dts)
    crash_days = sum(1 for v in states.values() if v.get("crash_risk"))
    n_shadow = 0
    for r in rows:
        r["shadow_composite"] = _shadow(r, states.get(str(r["signal_date"])[:10]))
        if r.get("shadow_composite") is not None:
            n_shadow += 1
    assert n_shadow > 0, "shadow_composite came back empty for every row"
    return rows, bench, start, crash_days, n_shadow
#
def _paired(daily_live, daily_shadow):
    """Align the two IC series by date and return (dates, live, shadow, diff)."""
    lm = {d: ic for d, ic, *_ in daily_live}
    sm = {d: ic for d, ic, *_ in daily_shadow}
    ds = sorted(set(lm) & set(sm))
    live = [lm[d] for d in ds]
    shad = [sm[d] for d in ds]
    diff = [s - l for s, l in zip(shad, live)]
    return ds, live, shad, diff
#
def head_to_head(history_days=120, fwds=(5, 10)):
    rows, bench, start, crash_days, n_shadow = _load_rows(history_days)
    out = {"start": start, "crash_days": crash_days, "n_shadow_rows": n_shadow,
           "fwds": {}}
    for fwd in fwds:
        daily, dates = fa._daily_ics(rows, bench, fwd, COLS)
        reg = fa._vol_regime(bench, dates)
        ds, live, shad, diff = _paired(daily["adj_composite"],
                                       daily["shadow_composite"])
        blk = {"n_days": len(ds),
               "live": fa._agg(daily["adj_composite"]),
               "shadow": fa._agg(daily["shadow_composite"]),
               "diff_mean": (sum(diff) / len(diff)) if diff else None,
               "diff_stats": ic_stats.nw_stats(diff, fwd=fwd),
               "shadow_wins_pct": (100.0 * sum(1 for x in diff if x > 0) / len(diff)) if diff else None,
               "by_regime": {}}
        for rl in ("Elevated Vol", "Normal Vol"):
            keep = [i for i, d in enumerate(ds) if reg.get(d) == rl]
            sub = [diff[i] for i in keep]
            blk["by_regime"][rl] = {
                "n": len(sub),
                "live_mean": (sum(live[i] for i in keep) / len(keep)) if keep else None,
                "shadow_mean": (sum(shad[i] for i in keep) / len(keep)) if keep else None,
                "diff_mean": (sum(sub) / len(sub)) if sub else None,
            }
        blk["gate"] = ic_stats.confidence_gate(diff, fwd=fwd)
        blk["caveat"] = ic_stats.overlap_caveat(diff, fwd=fwd)
        out["fwds"][fwd] = blk
    return out
#
def _f(v, nd=3):
    return "-" if v is None or (isinstance(v, float) and math.isnan(v)) else ("%+.*f" % (nd, v))
#
def print_head_to_head(res=None, history_days=120, fwds=(5, 10)):
    r = res or head_to_head(history_days, fwds)
    print("\nSHADOW vs LIVE - head to head | since %s | crash-risk days: %d | shadow rows: %d"
          % (r["start"], r["crash_days"], r["n_shadow_rows"]))
    for fwd, b in sorted(r["fwds"].items()):
        print("\n=== fwd=%d | %d paired sessions ===" % (fwd, b["n_days"]))
        print("  %-16s %10s %10s" % ("", "IC", "n_eff/n"))
        for lbl, agg, series_key in (("live adj_composite", b["live"], None),
                                     ("shadow_composite", b["shadow"], None)):
            print("  %-16s %10s" % (lbl, _f(agg.get("mean"))))
        d = b["diff_stats"]
        print("  %-16s %10s   n_eff %.1f/%d   t_nw %s"
              % ("difference", _f(b["diff_mean"]), d["n_eff"], d["n"],
                 _f(d["t_nw"], 2)))
        print("  shadow better on %s of paired days"
              % ("-" if b["shadow_wins_pct"] is None else "%d%%" % round(b["shadow_wins_pct"])))
        for rl, s in b["by_regime"].items():
            print("    %-14s n=%-3d live %s  shadow %s  diff %s"
                  % (rl, s["n"], _f(s["live_mean"]), _f(s["shadow_mean"]),
                     _f(s["diff_mean"])))
        ok, why = b["gate"]
        print("  VERDICT: %s (%s)" % ("actionable" if ok else "NOT actionable", why))
        if b["caveat"]:
            print("  " + b["caveat"])
    print("\nNOTE: shadow halves momentum under below-trend + elevated vol, and")
    print("momentum's IC is most negative in exactly that regime. A shadow win")
    print("in this sample is MECHANICAL, not validation. The falsifying test is")
    print("a TRENDING stretch where momentum should turn positive.")
    return r
#
if __name__ == "__main__":
    print_head_to_head()
