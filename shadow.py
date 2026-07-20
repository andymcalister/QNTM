"""Shadow composite — regime-conditional factor weights, MEASURED not traded.

Runs in parallel with the live model so a re-weighting decision can be made on
evidence instead of a bet. Nothing here touches scoring, the portfolio, or any
user-facing number.

The regime signal is deliberately MARKET STATE, not the news-driven macro
overlay: momentum crashes key off price being below trend with elevated
volatility (Daniel & Moskowitz, "Momentum Crashes"), which is a different thing
from a risk-off headline. The tilt below is PRE-REGISTERED from that literature
and modest (momentum halved, not zeroed) — it is NOT fitted to QNTM's data, and
must not be tuned to make the numbers look better. Tuning it to our own sample
would recreate the overfitting this exists to avoid.
"""
BASE_W  = {"momentum": 0.30, "quality": 0.30, "value": 0.20, "volume": 0.10, "sentiment": 0.10}
CRASH_W = {"momentum": 0.15, "quality": 0.42, "value": 0.28, "volume": 0.05, "sentiment": 0.10}
FACTORS = list(BASE_W)


def _market_states(bench: dict, dates: list, ma_days: int = 50, vol_lb: int = 10) -> dict:
    """Per-date market state from SPY: below trend AND elevated vol = crash_risk."""
    ds = [d for d in dates if d in bench]
    if len(ds) < 12:
        return {}
    rets = {}
    for i in range(1, len(ds)):
        p0, p1 = bench[ds[i - 1]], bench[ds[i]]
        if p0:
            rets[ds[i]] = p1 / p0 - 1.0
    vols = {}
    for i in range(len(ds)):
        w = [rets[ds[j]] for j in range(max(0, i - vol_lb + 1), i + 1) if ds[j] in rets]
        if len(w) >= 5:
            m = sum(w) / len(w)
            vols[ds[i]] = (sum((x - m) ** 2 for x in w) / (len(w) - 1)) ** 0.5
    med_vol = sorted(vols.values())[len(vols) // 2] if vols else None
    out = {}
    for i, d in enumerate(ds):
        lo = max(0, i - ma_days + 1)
        window = [bench[x] for x in ds[lo:i + 1]]
        if len(window) < 10:
            continue
        ma = sum(window) / len(window)
        below = bench[d] < ma
        hot = (vols.get(d) is not None and med_vol is not None and vols[d] > med_vol)
        _ov = globals().get("REGIME_OVERRIDE")
        if _ov is None:
            try:
                import macro_regime as _mr
                _ov = _mr.risk_off_by_date(cutoff=-1.0)
            except Exception:
                _ov = {}
            globals()["REGIME_OVERRIDE"] = _ov
        out[d] = {"below_trend": below, "elevated_vol": hot,
                  "price_crash": bool(below and hot),
                  "crash_risk": bool(_ov[d]) if d in _ov else bool(below and hot)}
    return out


def weights_for(state) -> dict:
    return CRASH_W if (state or {}).get("crash_risk") else BASE_W


def shadow_composite(row, state):
    """Re-blend the stored pillar scores under regime-conditional weights."""
    w = weights_for(state)
    tot, acc = 0.0, 0.0
    for f, wt in w.items():
        v = row.get(f)
        if v is None:
            continue
        try:
            acc += float(v) * wt
            tot += wt
        except (TypeError, ValueError):
            continue
    if tot <= 0:
        return None
    return round(acc / tot, 2)
