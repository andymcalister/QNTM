"""QNTM signal validation - "what the model flagged before the move".
Reads dated signal_log history and surfaces grounded, verifiable signals:
tickers whose conviction crossed into HIGH (or weakened out of it), with the
price move since the SUSTAINED transition. Observational only.
Label source: the canonical signal_log `signal` column (HIGH/MODERATE/LOW),
falling back to adj_composite >= _HIGH_MIN. Single-day label whipsaws are
coalesced (smooth_gap) so a one-day noise dip does not read as a new entry.
Public:
    get_validated_signals(...) -> list[dict]
    format_wrap_block(signals) -> str
Balanced by default (max_up bullish + max_down bearish, bullish first). For the
full /signals archive: max_up=None, max_down=None, max_days=None,
require_confirmed=False.
Env: QNTM_CONVICTION_FIELD, QNTM_CONVICTION_HIGH_MIN, QNTM_SIGNALS_ARCHIVE_URL.
"""
from __future__ import annotations
import os
from collections import defaultdict
from datetime import date, timedelta
#
_SCORE_FIELD = os.getenv("QNTM_CONVICTION_FIELD", "adj_composite")
_HIGH_MIN = float(os.getenv("QNTM_CONVICTION_HIGH_MIN", "60"))
_ARCHIVE_URL = os.getenv("QNTM_SIGNALS_ARCHIVE_URL", "https://qntm.live/signals")
_BULLET = "\u2022"
_ARROW = "\u2192"
_DASH = "\u2014"
_MON = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
#
def _resolve_sb(sb=None):
    if sb is not None:
        return sb
    try:
        from data_refresh import _get_supabase
        return _get_supabase()
    except Exception as e:
        print("[warn] signal_validation: no supabase client: " + repr(e))
        return None
#
def _label(row) -> str:
    sig = row.get("signal")
    if isinstance(sig, str) and sig.strip().upper() in ("HIGH", "MODERATE", "LOW"):
        return sig.strip().upper()
    sc = row.get(_SCORE_FIELD)
    if sc is None:
        return None
    try:
        return "HIGH" if float(sc) >= _HIGH_MIN else "MODERATE"
    except (TypeError, ValueError):
        return None
#
def _short_date(iso: str) -> str:
    try:
        y, m, d = str(iso).split("-")
        return _MON[int(m)] + " " + str(int(d))
    except Exception:
        return str(iso)
#
def _fetch_window(sb, start_date: str) -> list:
    cols = "ticker,signal_date,signal," + _SCORE_FIELD + ",price"
    rows = []
    page = 0
    size = 1000
    while page < 120:
        res = (sb.table("signal_log").select(cols)
               .gte("signal_date", start_date)
               .order("signal_date")
               .range(page * size, page * size + size - 1)
               .execute())
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < size:
            break
        page += 1
    return rows
#
def _coalesce(flags: list, max_gap: int) -> list:
    """Merge interior runs of length <= max_gap that are flanked by the same
    value on both sides (kills one-day label whipsaws). The current/edge run is
    never merged, so genuine recent transitions survive."""
    out = flags[:]
    n = len(out)
    changed = True
    while changed:
        changed = False
        runs = []
        i = 0
        while i < n:
            j = i
            while j + 1 < n and out[j + 1] == out[i]:
                j += 1
            runs.append((out[i], i, j))
            i = j + 1
        for k in range(1, len(runs) - 1):
            val, a, b = runs[k]
            if (b - a + 1) <= max_gap and runs[k - 1][0] == runs[k + 1][0] and runs[k - 1][0] != val:
                for t in range(a, b + 1):
                    out[t] = runs[k - 1][0]
                changed = True
        if changed:
            continue
    return out
#
def _detect(seq: list, smooth_gap: int):
    """seq = [(date, label, price), ...] asc. Returns (kind, event_idx) for the
    current sustained regime, or None (never HIGH in window, or HIGH from the
    very first row = entry predates our history)."""
    if len(seq) < 2:
        return None
    flags = [1 if s[1] == "HIGH" else 0 for s in seq]
    flags = _coalesce(flags, smooth_gap)
    if flags[-1] == 1:
        i = len(flags) - 1
        while i > 0 and flags[i - 1] == 1:
            i -= 1
        if i == 0:
            return None
        return ("entered_high", i)
    j = None
    for k in range(len(flags) - 1, -1, -1):
        if flags[k] == 1:
            j = k
            break
    if j is None or j == len(flags) - 1:
        return None
    return ("weakened", j + 1)
#
def get_validated_signals(as_of=None, history_days=45, min_days=2, max_days=21,
                          min_move_pct=4.0, smooth_gap=1, max_up=2, max_down=1,
                          require_confirmed=True, top_n=None, sb=None):
    sb = _resolve_sb(sb)
    if sb is None:
        return []
    ref = as_of or date.today()
    if isinstance(ref, str):
        try:
            y, m, d = ref.split("-")
            ref = date(int(y), int(m), int(d))
        except Exception:
            ref = date.today()
    start = (ref - timedelta(days=history_days)).isoformat()
    rows = _fetch_window(sb, start)
    if not rows:
        return []
    all_dates = sorted({r["signal_date"] for r in rows if r.get("signal_date")})
    if not all_dates:
        return []
    latest_i = len(all_dates) - 1
    date_index = {d: i for i, d in enumerate(all_dates)}
    by_ticker = defaultdict(list)
    for r in rows:
        if r.get("signal_date"):
            by_ticker[r["ticker"]].append(r)
    out = []
    for tk, trows in by_ticker.items():
        trows.sort(key=lambda r: r["signal_date"])
        seq = [(r["signal_date"], _label(r), r.get("price")) for r in trows]
        ev = _detect(seq, smooth_gap)
        if not ev:
            continue
        kind, idx = ev
        event_date = seq[idx][0]
        days_ago = latest_i - date_index.get(event_date, latest_i)
        if days_ago < min_days:
            continue
        if max_days is not None and days_ago > max_days:
            continue
        price_then = seq[idx][2]
        price_now = seq[-1][2]
        if not price_then or not price_now:
            continue
        try:
            move = (float(price_now) - float(price_then)) / float(price_then) * 100.0
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if require_confirmed:
            if kind == "entered_high" and move < min_move_pct:
                continue
            if kind == "weakened" and move > -min_move_pct:
                continue
        out.append({
            "ticker": tk, "kind": kind, "event_date": event_date,
            "days_ago": days_ago, "price_then": round(float(price_then), 2),
            "price_now": round(float(price_now), 2), "move_pct": round(move, 1),
        })
    ups = sorted([s for s in out if s["kind"] == "entered_high"], key=lambda s: abs(s["move_pct"]), reverse=True)
    downs = sorted([s for s in out if s["kind"] == "weakened"], key=lambda s: abs(s["move_pct"]), reverse=True)
    if max_up is None and max_down is None:
        allsigs = sorted(out, key=lambda s: s["event_date"], reverse=True)
        return allsigs[:top_n] if top_n else allsigs
    picked = ups[:max_up if max_up is not None else len(ups)] + downs[:max_down if max_down is not None else len(downs)]
    return picked
#
def _line(s: dict) -> str:
    d = _short_date(s["event_date"])
    ago = str(s["days_ago"]) + " days"
    mv = ("%+.1f%%" % s["move_pct"]) + " since"
    if s["kind"] == "entered_high":
        return _BULLET + " " + s["ticker"] + " " + _DASH + " HIGH conviction since " + d + " (" + ago + "), " + mv
    return _BULLET + " " + s["ticker"] + " " + _DASH + " conviction slipped " + d + " (" + ago + "), " + mv
#
def format_wrap_block(signals: list, archive_url: str = None) -> str:
    if not signals:
        return ""
    url = archive_url or _ARCHIVE_URL
    lines = ["Flagged before today's moves"]
    for s in signals:
        lines.append(_line(s))
    lines.append("full record " + _ARROW + " " + url)
    return "\n".join(lines)
#
def _load_benchmark(sb, start_date: str) -> dict:
    """{date: close} for SPY from benchmark_price. Empty on failure."""
    out = {}
    try:
        r = (sb.table("benchmark_price").select("d,close")
             .gte("d", start_date).order("d").execute())
        for x in (r.data or []):
            d, c = x.get("d"), x.get("close")
            if d is not None and c is not None:
                out[str(d)] = float(c)
    except Exception as e:
        print("[warn] benchmark load failed: " + repr(e))
    return out


def compute_hit_rates(as_of=None, window=10, history_days=90, smooth_gap=1, sb=None):
    """Population hit-rates, benchmark-relative, fixed forward window.
    For every HIGH entry and LOW entry (one per coalesced run), compare the
    stock's `window`-session forward return to SPY over the SAME dates. HIGH
    hit = beat SPY; LOW hit = lagged SPY. Episodes without a full forward
    window are excluded. Returns dict with rates, N, window, since, benchmark."""
    sb = _resolve_sb(sb)
    empty = {"high_beat_rate": None, "high_n": 0, "low_lag_rate": None,
             "low_n": 0, "window": window, "since": None, "benchmark": "SPY"}
    if sb is None:
        return empty
    ref = as_of or date.today()
    if isinstance(ref, str):
        try:
            y, m, d = ref.split("-"); ref = date(int(y), int(m), int(d))
        except Exception:
            ref = date.today()
    start = (ref - timedelta(days=history_days)).isoformat()
    rows = _fetch_window(sb, start)
    bench = _load_benchmark(sb, start)
    if not rows or not bench:
        return empty
    all_dates = sorted({r["signal_date"] for r in rows if r.get("signal_date")})
    if not all_dates:
        return empty
    di = {d: i for i, d in enumerate(all_dates)}
    n_dates = len(all_dates)
    by_ticker = defaultdict(list)
    for r in rows:
        if r.get("signal_date"):
            by_ticker[r["ticker"]].append(r)
    high_hits = high_n = low_hits = low_n = 0

    def _fwd(price_map, i0):
        """(ret over window) or None if incomplete / bad prices."""
        if i0 + window >= n_dates:
            return None
        d0, d1 = all_dates[i0], all_dates[i0 + window]
        p0, p1 = price_map.get(d0), price_map.get(d1)
        if not p0 or not p1:
            return None
        try:
            return (float(p1) - float(p0)) / float(p0)
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    for tk, trows in by_ticker.items():
        trows.sort(key=lambda r: r["signal_date"])
        dates = [r["signal_date"] for r in trows]
        pmap = {r["signal_date"]: r.get("price") for r in trows}
        labels = _coalesce([_label(r) for r in trows], smooth_gap)
        # find each run start (one episode per run)
        idx = 0
        m = len(labels)
        while idx < m:
            j = idx
            while j + 1 < m and labels[j + 1] == labels[idx]:
                j += 1
            lab = labels[idx]
            gi = di.get(dates[idx])
            if lab in ("HIGH", "LOW") and gi is not None:
                sr = _fwd(pmap, gi)
                br = _fwd(bench, gi)
                if sr is not None and br is not None:
                    rel = sr - br
                    if lab == "HIGH":
                        high_n += 1
                        if rel > 0:
                            high_hits += 1
                    else:
                        low_n += 1
                        if rel < 0:
                            low_hits += 1
            idx = j + 1
    return {
        "high_beat_rate": round(100.0 * high_hits / high_n, 1) if high_n else None,
        "high_n": high_n,
        "low_lag_rate": round(100.0 * low_hits / low_n, 1) if low_n else None,
        "low_n": low_n,
        "window": window,
        "since": start,
        "benchmark": "SPY",
    }


def format_hit_line(stats: dict) -> str:
    """One-line summary for the wrap, or '' if not enough data."""
    if not stats or not stats.get("high_n"):
        return ""
    w = stats["window"]
    parts = []
    if stats.get("high_beat_rate") is not None:
        parts.append("HIGH beat SPY " + str(stats["high_beat_rate"]) + "% (" + str(stats["high_n"]) + " calls)")
    if stats.get("low_lag_rate") is not None and stats.get("low_n"):
        parts.append("LOW lagged " + str(stats["low_lag_rate"]) + "% (" + str(stats["low_n"]) + ")")
    if not parts:
        return ""
    return "Over the next " + str(w) + " sessions: " + "; ".join(parts) + "."


if __name__ == "__main__":
    sigs = get_validated_signals()
    print("[" + str(len(sigs)) + " selected]")
    print(format_wrap_block(sigs) or "(none today)")
