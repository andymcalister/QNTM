"""ic_stats.py - overlap-aware significance helpers for factor IC series.
Daily cross-sectional ICs measured against a fwd=k forward window overlap on
k-1 of their k days. Treating them as independent inflates |t| by roughly
sqrt(k) and makes %days+ saturate at 0/100. These helpers report a
Newey-West corrected t and an effective sample size instead.
Pure stdlib on purpose - no numpy/scipy/pandas dependency."""
from __future__ import annotations
import math
#
def _clean(xs):
    out = []
    for x in xs or []:
        if x is None:
            continue
        try:
            v = float(x)
        except (TypeError, ValueError):
            continue
        if math.isnan(v) or math.isinf(v):
            continue
        out.append(v)
    return out
#
def _mean(xs):
    return (sum(xs) / len(xs)) if xs else float("nan")
#
def _autocov(xs, k):
    n = len(xs)
    if k >= n:
        return 0.0
    m = _mean(xs)
    return sum((xs[i] - m) * (xs[i + k] - m) for i in range(n - k)) / n
#
def nw_lag(fwd):
    """Standard truncation lag for a fwd-session overlapping window."""
    try:
        return max(0, int(fwd) - 1)
    except (TypeError, ValueError):
        return 0
#
def nw_stats(series, fwd=1, lag=None):
    """Return mean, iid vs Newey-West t-stats, and effective N for an IC series.
    n_eff = n * gamma0 / var_nw : the number of independent observations the
    series is worth. With fwd=10 over ~15 sessions expect n_eff ~ 2, not 15."""
    xs = _clean(series)
    n = len(xs)
    out = {"n": n, "n_eff": float(n), "mean": float("nan"),
           "se_iid": float("nan"), "se_nw": float("nan"),
           "t_iid": float("nan"), "t_nw": float("nan"),
           "lag": 0, "overlapping": False}
    if n < 3:
        return out
    L = nw_lag(fwd) if lag is None else int(lag)
    L = max(0, min(L, n - 1))
    g0 = _autocov(xs, 0)
    if g0 <= 0:
        return out
    var_nw = g0
    for k in range(1, L + 1):
        w = 1.0 - (k / (L + 1.0))
        var_nw += 2.0 * w * _autocov(xs, k)
    if var_nw <= 0:
        var_nw = g0
    m = _mean(xs)
    se_iid = math.sqrt(g0 / n)
    se_nw = math.sqrt(var_nw / n)
    n_eff = max(1.0, min(float(n), n * g0 / var_nw))
    out.update(mean=m, se_iid=se_iid, se_nw=se_nw,
               t_iid=(m / se_iid if se_iid > 0 else float("nan")),
               t_nw=(m / se_nw if se_nw > 0 else float("nan")),
               n_eff=n_eff, lag=L, overlapping=(L > 0))
    return out
#
def days_positive(series):
    """Fraction of days with IC > 0, plus whether it is worth printing."""
    xs = _clean(series)
    if not xs:
        return {"pct": float("nan"), "n": 0}
    return {"pct": 100.0 * sum(1 for v in xs if v > 0) / len(xs), "n": len(xs)}
#
def days_positive_label(series, fwd=1):
    """%days+ is structurally saturated under overlap - flag it rather than
    print a bare 100%."""
    d = days_positive(series)
    if d["n"] == 0:
        return "-"
    txt = "%d%%" % round(d["pct"])
    return (txt + "*") if nw_lag(fwd) > 0 else txt
#
def tstat_label(series, fwd=1, lag=None):
    """Newey-West t, marked when the iid t materially overstates it."""
    s = nw_stats(series, fwd=fwd, lag=lag)
    if math.isnan(s["t_nw"]):
        return "-"
    txt = "%+.2f" % s["t_nw"]
    if s["overlapping"] and abs(s["t_iid"]) > 1.5 * abs(s["t_nw"]):
        txt += "*"
    return txt
#
def effective_n_label(series, fwd=1, lag=None):
    s = nw_stats(series, fwd=fwd, lag=lag)
    if s["n"] == 0:
        return "-"
    return "%.1f/%d" % (s["n_eff"], s["n"])
#
def overlap_caveat(series, fwd=1, lag=None):
    """One-line footnote for a report block. Empty string when fwd=1."""
    if nw_lag(fwd) <= 0:
        return ""
    s = nw_stats(series, fwd=fwd, lag=lag)
    if math.isnan(s["t_nw"]):
        return ("* fwd=%d windows overlap on %d of %d days; %%days+ and t-stat "
                "are not independent observations." % (fwd, fwd - 1, fwd))
    return ("* fwd=%d windows overlap: %d raw sessions are worth ~%.1f "
            "independent observations. iid t would read %+.2f; "
            "overlap-corrected t is %+.2f. %%days+ saturates under overlap "
            "and should not be read as consistency."
            % (fwd, s["n"], s["n_eff"], s["t_iid"], s["t_nw"]))
#
def confidence_gate(series, fwd=1, lag=None, min_eff=8.0, min_t=2.0):
    """Whether a result is worth acting on. narrate() should call this instead
    of thresholding a raw t-stat - otherwise it grows more confident purely
    because more overlapping days accumulate."""
    s = nw_stats(series, fwd=fwd, lag=lag)
    if s["n_eff"] < min_eff:
        return (False, "insufficient independent data (n_eff %.1f < %.0f)"
                % (s["n_eff"], min_eff))
    if math.isnan(s["t_nw"]) or abs(s["t_nw"]) < min_t:
        return (False, "overlap-corrected t %.2f below %.1f" % (s["t_nw"], min_t))
    return (True, "n_eff %.1f, corrected t %+.2f" % (s["n_eff"], s["t_nw"]))
#
if __name__ == "__main__":
    import random
    random.seed(7)
    base = [random.gauss(0.02, 0.05) for _ in range(24)]
    smooth = [sum(base[max(0, i - 9):i + 1]) / len(base[max(0, i - 9):i + 1])
              for i in range(len(base))]
    s = nw_stats(smooth, fwd=10)
    print("n=%d  n_eff=%.2f  t_iid=%+.2f  t_nw=%+.2f  lag=%d"
          % (s["n"], s["n_eff"], s["t_iid"], s["t_nw"], s["lag"]))
    print("days+ :", days_positive_label(smooth, fwd=10))
    print("gate  :", confidence_gate(smooth, fwd=10))
    print(overlap_caveat(smooth, fwd=10))
    assert s["n_eff"] < s["n"], "overlap correction did not reduce effective N"
    assert abs(s["t_nw"]) < abs(s["t_iid"]), "NW t should be smaller than iid t"
    assert nw_stats([0.1] * 5, fwd=1)["lag"] == 0
    assert days_positive_label([], fwd=5) == "-"
    print("OK")
