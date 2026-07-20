"""Per-factor Information Coefficient (IC) over signal_log — DIAGNOSTIC.
Daily cross-sectional Spearman IC per factor vs forward excess-over-SPY, averaged
across days (not pooled). Also splits by a market-vol regime proxy (SPY trailing
realized-vol median split) to test whether a factor's sign flips by regime.
CAVEAT: short single-regime samples over-fit; this informs hypotheses, it does
NOT justify re-weighting PILLAR_W. Recomputes from signal_log each call.
"""
import math
from collections import defaultdict
from datetime import date, timedelta

FACTORS = ["momentum", "quality", "value", "volume", "sentiment"]
# current live weights (model_engine PILLAR_W v2.0) — shown for weight-vs-IC context
PILLAR_W = {"momentum": 0.30, "quality": 0.30, "value": 0.20, "volume": 0.10, "sentiment": 0.10}


def _is_trading_day(d) -> bool:
    """Mon-Fri only. The scorer also runs weekends, writing phantom sessions that
    re-stamp Friday's prices; those duplicates inflate day counts and t-stats."""
    try:
        return date.fromisoformat(str(d)[:10]).weekday() < 5
    except Exception:
        return True


def _sb():
    from data_refresh import _get_supabase
    return _get_supabase()


def _spearman(xs, ys):
    n = len(xs)
    if n < 5:
        return None

    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    vx = sum((rx[i] - mx) ** 2 for i in range(n))
    vy = sum((ry[i] - my) ** 2 for i in range(n))
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


def _load(sb, start):
    cols = "ticker,signal_date,price,composite,adj_composite," + ",".join(FACTORS)
    rows, page, size = [], 0, 1000
    while page < 300:
        res = (sb.table("signal_log").select(cols).gte("signal_date", start)
               .order("signal_date").range(page * size, page * size + size - 1).execute())
        b = res.data or []
        rows.extend(b)
        if len(b) < size:
            break
        page += 1
    bench = {}
    r = sb.table("benchmark_price").select("d,close").gte("d", start).order("d").execute()
    for x in (r.data or []):
        if x.get("d") is not None and x.get("close") is not None:
            bench[str(x["d"])[:10]] = float(x["close"])
    rows = [r for r in rows if _is_trading_day(r.get("signal_date"))]
    bench = {d: v for d, v in bench.items() if _is_trading_day(d)}
    return rows, bench


def _vol_regime(bench, dates, lb=10):
    """SPY trailing lb-day realized-vol, median split -> Elevated/Normal per date."""
    rets = {}
    for i in range(1, len(dates)):
        d0, d1 = dates[i - 1], dates[i]
        if d0 in bench and d1 in bench and bench[d0]:
            rets[d1] = bench[d1] / bench[d0] - 1.0
    vol = {}
    for i in range(len(dates)):
        w = [rets[dates[j]] for j in range(max(0, i - lb + 1), i + 1) if dates[j] in rets]
        if len(w) >= 5:
            m = sum(w) / len(w)
            vol[dates[i]] = (sum((x - m) ** 2 for x in w) / (len(w) - 1)) ** 0.5
    if not vol:
        return {}
    med = sorted(vol.values())[len(vol) // 2]
    return {d: ("Elevated Vol" if v > med else "Normal Vol") for d, v in vol.items()}


def _daily_ics(rows, bench, fwd, cols):
    """{col: [(date, ic, n_names), ...]} — one cross-sectional IC per completed day."""
    price = defaultdict(dict)
    facts = {c: defaultdict(dict) for c in cols}
    for r in rows:
        d = str(r["signal_date"])[:10]
        tk = r["ticker"]
        if r.get("price") is not None:
            price[tk][d] = float(r["price"])
        for c in cols:
            if r.get(c) is not None:
                facts[c][tk][d] = float(r[c])
    dates = sorted({str(r["signal_date"])[:10] for r in rows})
    di = {d: i for i, d in enumerate(dates)}
    out = {c: [] for c in cols}
    for d in dates:
        i = di[d]
        if i + fwd >= len(dates):
            continue
        d2 = dates[i + fwd]
        if d not in bench or d2 not in bench or not bench[d]:
            continue
        spy_fwd = bench[d2] / bench[d] - 1.0
        excess = {tk: (pm[d2] / pm[d] - 1.0) - spy_fwd
                  for tk, pm in price.items() if d in pm and d2 in pm and pm[d]}
        if len(excess) < 20:
            continue
        for c in cols:
            fmap = facts[c]
            fx, fy = [], []
            for tk, ex in excess.items():
                if tk in fmap and d in fmap[tk]:
                    fx.append(fmap[tk][d]); fy.append(ex)
            ic = _spearman(fx, fy)
            if ic is not None:
                out[c].append((d, ic, len(fx)))
    return out, dates


def _agg(ics, fwd=1):
    import ic_stats as _ics
    if not ics:
        return {"mean": None, "tstat": None, "pct_pos": None, "ndays": 0}
    v = [x[1] for x in ics]
    n = len(v)
    mean = sum(v) / n
    sd = (sum((x - mean) ** 2 for x in v) / (n - 1)) ** 0.5 if n > 1 else 0.0
    return {"mean": round(mean, 3),
            "tstat": (lambda s: None if s["t_nw"] != s["t_nw"] else round(s["t_nw"], 2))(_ics.nw_stats(v, fwd=fwd)),
            "tstat_iid": (lambda s: None if s["t_iid"] != s["t_iid"] else round(s["t_iid"], 2))(_ics.nw_stats(v, fwd=fwd)),
            "n_eff": round(_ics.nw_stats(v, fwd=fwd)["n_eff"], 1),
            "overlapping": fwd > 1,
            "pct_pos": round(100.0 * sum(1 for x in v if x > 0) / n, 0),
            "ndays": n}


def ic_report(as_of=None, history_days=120, fwds=(5, 10)):
    """Everything the admin page needs: per-fwd factor table (overall + by vol
    regime) with weights, plus the composite daily IC series."""
    sb = _sb()
    ref = date.today() if not as_of else date.fromisoformat(as_of)
    start = (ref - timedelta(days=history_days)).isoformat()
    rows, bench = _load(sb, start)
    cols = FACTORS + ["composite", "adj_composite", "shadow_composite"]
    if not rows or not bench:
        return {"error": "no data", "rows": len(rows), "bench": len(bench)}
    # Shadow composite: regime-conditional weights, computed from the stored
    # pillars. Measured only — never written back, never traded.
    _crash_days = 0
    try:
        from shadow import _market_states as _ms, shadow_composite as _shadow
        _dts = sorted({str(r["signal_date"])[:10] for r in rows})
        _states = _ms(bench, _dts)
        _crash_days = sum(1 for v in _states.values() if v.get("crash_risk"))
        for r in rows:
            r["shadow_composite"] = _shadow(r, _states.get(str(r["signal_date"])[:10]))
    except Exception as e:
        print("[warn] shadow composite unavailable: " + repr(e))
    report = {"start": start, "weights": PILLAR_W, "crash_days": _crash_days, "fwds": {}}
    for fwd in fwds:
        daily, dates = _daily_ics(rows, bench, fwd, cols)
        reg = _vol_regime(bench, dates)
        table = {}
        for c in cols:
            ics = daily[c]
            overall = _agg(ics, fwd)
            by_reg = {}
            for rlabel in ("Elevated Vol", "Normal Vol"):
                sub = [x for x in ics if reg.get(x[0]) == rlabel]
                by_reg[rlabel] = _agg(sub, fwd)
            table[c] = {"weight": PILLAR_W.get(c), "overall": overall, "by_regime": by_reg}
        report["fwds"][fwd] = {
            "table": table,
            "composite_series": [(d, round(ic, 3)) for d, ic, _ in daily["adj_composite"]],
            "regime_days": {r: sum(1 for v in reg.values() if v == r)
                            for r in ("Elevated Vol", "Normal Vol")},
        }
    report["narrative"] = narrate(report)
    return report


if __name__ == "__main__":
    import json
    r = ic_report(history_days=120)
    if r.get("error"):
        print("no data:", r)
    else:
        for fwd, blk in r["fwds"].items():
            print("\n=== fwd=%d | since %s | regime days: %s ===" % (fwd, r["start"], blk["regime_days"]))
            print("%-14s %6s %8s %7s | %10s %10s" % ("factor", "wt", "IC", "%d+", "ElevVol IC", "NormVol IC"))
            for c, row in blk["table"].items():
                o = row["overall"]; e = row["by_regime"]["Elevated Vol"]; nv = row["by_regime"]["Normal Vol"]
                w = "" if row["weight"] is None else "%.2f" % row["weight"]
                print("%-14s %6s %+8.3f %6.0f%% | %+10s %+10s" % (
                    c, w, o["mean"] or 0, o["pct_pos"] or 0,
                    ("%.3f(%d)" % (e["mean"], e["ndays"])) if e["mean"] is not None else "-",
                    ("%.3f(%d)" % (nv["mean"], nv["ndays"])) if nv["mean"] is not None else "-"))


# ── Auto-commentary ──────────────────────────────────────────────────────────
# Reads an ic_report and says, in plain English, what the numbers mean and
# whether to tune or wait. Thresholds are deliberately conservative: the failure
# mode this guards against is acting on one regime's weather.
MEANINGFUL_IC = 0.02      # below this, treat as noise
DURABLE_IC    = 0.06      # above this, too big to be a standing premium
HEAVY_W       = 0.25
LIGHT_W       = 0.15
MIN_DAYS      = 60        # floor before acting even within one regime
MIN_REGIME_N  = 20        # per-bucket floor before comparing regimes


def narrate(report, fwd=None):
    fwds = report.get("fwds") or {}
    if not fwds:
        return {"verdict": "No data yet.", "bullets": [], "guidance": "", "confidence": "none"}
    key = fwd if fwd in fwds else sorted(fwds)[-1]
    blk = fwds[key]
    tbl = blk["table"]
    bullets, tensions = [], []
    ndays = max((r["overall"]["ndays"] for r in tbl.values()), default=0)
    biggest = 0.0

    for name, row in tbl.items():
        ic, w = row["overall"]["mean"], row.get("weight")
        if ic is None:
            continue
        biggest = max(biggest, abs(ic))
        if name == "adj_composite":
            if ic < -MEANINGFUL_IC:
                bullets.append(("bad", "The blended score ranked backwards over this window "
                                       "(IC %+.3f) \u2014 the model's ordering worked against it." % ic))
            elif ic > MEANINGFUL_IC:
                bullets.append(("good", "The blended score ranked correctly (IC %+.3f)." % ic))
            else:
                bullets.append(("flat", "The blended score had no measurable ranking power (IC %+.3f)." % ic))
            continue
        if w is None:
            continue
        pct = int(round(w * 100))
        if ic < -MEANINGFUL_IC and w >= HEAVY_W:
            tensions.append(name)
            bullets.append(("bad", "%s carries %d%% of the score but ranked backwards (IC %+.3f) \u2014 "
                                   "the single biggest drag." % (name, pct, ic)))
        elif ic < -MEANINGFUL_IC:
            bullets.append(("bad", "%s (%d%% weight) ranked backwards (IC %+.3f)." % (name, pct, ic)))
        elif ic > MEANINGFUL_IC and w <= LIGHT_W:
            bullets.append(("good", "%s ranked well (IC %+.3f) on only %d%% weight \u2014 carrying more "
                                    "than it's paid for." % (name, ic, pct)))
        elif ic > MEANINGFUL_IC:
            bullets.append(("good", "%s (%d%% weight) ranked correctly (IC %+.3f) \u2014 working as "
                                    "intended." % (name, pct, ic)))
        else:
            bullets.append(("flat", "%s (%d%% weight) showed no ranking power (IC %+.3f) \u2014 neither "
                                    "helping nor hurting." % (name, pct, ic)))

    base_ic = ((tbl.get("composite") or {}).get("overall") or {}).get("mean")
    shad_ic = ((tbl.get("shadow_composite") or {}).get("overall") or {}).get("mean")
    if base_ic is not None and shad_ic is not None:
        delta = shad_ic - base_ic
        if delta > MEANINGFUL_IC:
            bullets.append(("good", "SHADOW: regime-conditional weights ranked BETTER than the live "
                                    "blend (%+.3f vs %+.3f). Promising \u2014 but confirm it holds in a "
                                    "second, different regime before switching." % (shad_ic, base_ic)))
        elif delta < -MEANINGFUL_IC:
            bullets.append(("bad", "SHADOW: regime-conditional weights ranked WORSE than the live "
                                   "blend (%+.3f vs %+.3f). The tilt is not helping." % (shad_ic, base_ic)))
        else:
            bullets.append(("flat", "SHADOW: regime-conditional weights made no material difference "
                                    "(%+.3f vs %+.3f)." % (shad_ic, base_ic)))
    rd = blk.get("regime_days") or {}
    thin = [r for r, n in rd.items() if n < MIN_REGIME_N]
    regime_usable = bool(rd) and not thin
    flips = []
    for name, row in tbl.items():
        br = row.get("by_regime") or {}
        vals = {k: v["mean"] for k, v in br.items() if v and v.get("mean") is not None
                and v.get("ndays", 0) >= MIN_REGIME_N}
        if len(vals) >= 2 and max(vals.values()) > MEANINGFUL_IC and min(vals.values()) < -MEANINGFUL_IC:
            flips.append(name)

    if biggest > DURABLE_IC:
        bullets.append(("warn", "Several readings are far larger than a durable factor edge "
                                "(real ones sit near 0.02-0.05). Numbers this size are the "
                                "signature of one market environment, not a standing property."))
    if ndays < MIN_DAYS:
        bullets.append(("warn", "Only %d sessions measured. That is too short to separate a real "
                                "effect from this period's weather." % ndays))
    if not regime_usable:
        bullets.append(("warn", "The regime split isn't usable yet \u2014 at least one bucket is under "
                                "%d sessions, so any high-vol vs normal comparison is noise." % MIN_REGIME_N))

    if ndays < MIN_DAYS:
        verdict = "Too early to act \u2014 keep accumulating."
        guidance = ("WAIT. Nothing here justifies changing PILLAR_W. What would change that: another "
                    "%d+ sessions, and critically a TRENDING stretch. Momentum is expected to rank "
                    "backwards in a reversal market and correctly in a trending one \u2014 if it stays "
                    "negative through a trend, that's a real finding worth re-weighting on." % (MIN_DAYS - ndays))
        conf = "low"
    elif not regime_usable:
        verdict = "Signal is forming, but only one environment observed."
        guidance = ("WAIT on re-weighting; the sample covers a single regime. Collect a contrasting "
                    "regime before touching weights.")
        conf = "low"
    elif flips:
        verdict = "Regime-dependent behaviour detected in: %s." % ", ".join(flips)
        guidance = ("CONSIDER regime-conditional weighting \u2014 these factors change sign between "
                    "environments, which is what a conditional weight is for. Build it in shadow "
                    "first and compare before switching the live model.")
        conf = "medium"
    elif tensions:
        verdict = "Persistent drag from heavily-weighted %s." % ", ".join(tensions)
        guidance = ("CONSIDER trimming the flagged weight \u2014 the effect has held across both "
                    "regimes measured. Make one change, forward-only, and measure.")
        conf = "medium"
    else:
        verdict = "Weights look broadly consistent with what each factor delivered."
        guidance = "HOLD. Nothing indicates a change is needed."
        conf = "medium"

    return {"verdict": verdict, "bullets": bullets, "guidance": guidance,
            "confidence": conf, "ndays": ndays, "fwd": key}
