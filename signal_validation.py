"""QNTM signal validation - how the model's calls have played out.
Reads dated signal_log history (canonical `signal` column) and surfaces
grounded, verifiable calls on both sides, plus population hit-rates vs SPY.
Observational only. Four kinds per ticker:
    entered_high   - recent HIGH entry, rose since        (spotted early)
    sustained_high - long HIGH run, rose over it          (winner)
    weakened       - dropped from HIGH, fell since         (downgrade before drop)
    sustained_low  - long LOW run, fell over it            (stayed bearish)
1-day label whipsaws are coalesced. Balanced slate = biggest winners + biggest
losers. For the full /signals archive: max_winners=None, max_losers=None,
require_confirmed=False.
Public:
    get_validated_signals(...) -> list[dict]
    format_wrap_block(sigs) -> str
    compute_hit_rates(as_of, window=10, history_days=90) -> dict
    format_hit_line(stats) -> str
Env: QNTM_CONVICTION_FIELD, QNTM_CONVICTION_HIGH_MIN, QNTM_SIGNALS_ARCHIVE_URL,
    QNTM_SIGNALS_HEADER.
"""
from __future__ import annotations
import os
from collections import defaultdict
from datetime import date, timedelta
#
_SCORE_FIELD = os.getenv("QNTM_CONVICTION_FIELD", "adj_composite")
_HIGH_MIN = float(os.getenv("QNTM_CONVICTION_HIGH_MIN", "60"))
_ARCHIVE_URL = os.getenv("QNTM_SIGNALS_ARCHIVE_URL", "https://qntm.live/signals")
_HEADER = os.getenv("QNTM_SIGNALS_HEADER", "How the model's calls have played out:")
_UP = "\u2191"
_DOWN = "\u2193"
_ARROW = "\u2192"
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
        return "?"
    try:
        return "HIGH" if float(sc) >= _HIGH_MIN else "MODERATE"
    except (TypeError, ValueError):
        return "?"
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
def _coalesce(vals: list, max_gap: int) -> list:
    out = vals[:]
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
    return out
#
def _classify(labels, dates, latest_i, date_index, min_days, recent_days, sustained_min_days):
    n = len(labels)
    if n < 2:
        return None
    cur = labels[-1]
    if cur not in ("HIGH", "MODERATE", "LOW"):
        return None
    i = n - 1
    while i > 0 and labels[i - 1] == cur:
        i -= 1
    if i == 0:
        return None
    start_date = dates[i]
    days_ago = latest_i - date_index.get(start_date, latest_i)
    prev = labels[i - 1]
    if cur == "HIGH":
        if days_ago < min_days:
            return None
        if days_ago <= recent_days:
            return ("entered_high", i)
        if days_ago >= sustained_min_days:
            return ("sustained_high", i)
        return None
    if prev == "HIGH":
        if days_ago < min_days:
            return None
        return ("weakened", i)
    if cur == "LOW" and days_ago >= sustained_min_days:
        return ("sustained_low", i)
    return None
#
def _confirmed(kind, move, min_move, min_sustained_move):
    if kind == "entered_high":
        return move >= min_move
    if kind == "sustained_high":
        return move >= min_sustained_move
    if kind == "weakened":
        return move <= -min_move
    if kind == "sustained_low":
        return move <= -min_sustained_move
    return False
#
def get_validated_signals(as_of=None, history_days=60, min_days=2, recent_days=10,
                          sustained_min_days=10, min_move_pct=4.0,
                          min_sustained_move_pct=10.0, smooth_gap=1,
                          max_winners=2, max_losers=2, require_confirmed=True,
                          top_n=None, sb=None):
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
        dates = [r["signal_date"] for r in trows]
        prices = [r.get("price") for r in trows]
        labels = _coalesce([_label(r) for r in trows], smooth_gap)
        ev = _classify(labels, dates, latest_i, date_index, min_days, recent_days, sustained_min_days)
        if not ev:
            continue
        kind, idx = ev
        price_then, price_now = prices[idx], prices[-1]
        if not price_then or not price_now:
            continue
        try:
            move = (float(price_now) - float(price_then)) / float(price_then) * 100.0
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if require_confirmed and not _confirmed(kind, move, min_move_pct, min_sustained_move_pct):
            continue
        out.append({
            "ticker": tk, "kind": kind, "event_date": dates[idx],
            "days_ago": latest_i - date_index.get(dates[idx], latest_i),
            "price_then": round(float(price_then), 2),
            "price_now": round(float(price_now), 2), "move_pct": round(move, 1),
        })
    winners = sorted([s for s in out if s["kind"] in ("entered_high", "sustained_high")],
                     key=lambda s: s["move_pct"], reverse=True)
    losers = sorted([s for s in out if s["kind"] in ("weakened", "sustained_low")],
                    key=lambda s: s["move_pct"])
    if max_winners is None and max_losers is None:
        allsigs = sorted(out, key=lambda s: abs(s["move_pct"]), reverse=True)
        return allsigs[:top_n] if top_n else allsigs
    picked = winners[:max_winners if max_winners is not None else len(winners)]
    picked += losers[:max_losers if max_losers is not None else len(losers)]
    return picked
#
def _line(s: dict) -> str:
    d = _short_date(s["event_date"])
    m = "%+.1f%%" % s["move_pct"]
    tk = s["ticker"]
    k = s["kind"]
    if k in ("entered_high", "sustained_high"):
        return _UP + " " + tk + " " + m + " (HIGH since " + d + ")"
    if k == "weakened":
        return _DOWN + " " + tk + " " + m + " (downgraded " + d + ")"
    return _DOWN + " " + tk + " " + m + " (LOW since " + d + ")"
#
def format_wrap_block(signals: list, archive_url: str = None, header: str = None) -> str:
    if not signals:
        return ""
    url = archive_url or _ARCHIVE_URL
    head = header or _HEADER
    tail = "full record " + _ARROW + " " + url
    lines = [_line(s) for s in signals]
    while lines:
        body = "\n".join([head] + lines + [tail])
        if len(body) <= 280:
            return body
        lines.pop()
    return ""
#
def _load_benchmark(sb, start_date: str) -> dict:
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
#
def compute_hit_rates(as_of=None, window=10, history_days=90, smooth_gap=1, sb=None):
    """Population hit-rates vs SPY, fixed forward window. Every HIGH entry and
    LOW entry (one per coalesced run, NO confirmed filter). HIGH hit = beat SPY
    over the next `window` sessions; LOW hit = lagged SPY. Incomplete-window
    episodes excluded. Returns rates + N + window + since + benchmark."""
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
        "window": window, "since": start, "benchmark": "SPY",
    }
#
def format_hit_line(stats: dict) -> str:
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
#
if __name__ == "__main__":
    import collections
    every = get_validated_signals(max_winners=None, max_losers=None)
    print(collections.Counter(s["kind"] for s in every))
    print("--- wrap slate ---")
    print(format_wrap_block(get_validated_signals()) or "(none)")
    print("--- hit rates ---")
    hr = compute_hit_rates()
    print(hr)
    print(format_hit_line(hr) or "(insufficient)")
