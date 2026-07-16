"""QNTM signal validation - how the model's calls have played out.
Reads dated signal_log history (canonical `signal` column) + SPY from
benchmark_price. Observational only. Four kinds for the wrap slate, plus:
  compute_hit_rates    - naive fixed forward window (horizon-agnostic; reference)
  compute_trade_stats  - the model's rule: enter at enter_at, hold, exit when
                         adj_composite < exit_below; per-trade return vs SPY over
                         each trade's own holding window.
  sweep_exit_thresholds- same, swept over several exit_below values (one fetch)
                         so the exit choice is evidence-based, not reactive.
For the full /signals archive: max_winners=None, max_losers=None,
require_confirmed=False.
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
def _parse_ref(as_of):
    ref = as_of or date.today()
    if isinstance(ref, str):
        try:
            y, m, d = ref.split("-")
            return date(int(y), int(m), int(d))
        except Exception:
            return date.today()
    return ref
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
    while page < 200:
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
    ref = _parse_ref(as_of)
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
    """Naive fixed-forward-window hit-rate vs SPY (horizon-agnostic). Kept for
    reference; compute_trade_stats / sweep are the fair test for this model."""
    sb = _resolve_sb(sb)
    empty = {"high_beat_rate": None, "high_n": 0, "low_lag_rate": None,
             "low_n": 0, "window": window, "since": None, "benchmark": "SPY"}
    if sb is None:
        return empty
    start = (_parse_ref(as_of) - timedelta(days=history_days)).isoformat()
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
def _trade_excess(prices, dates, bench, di, ei, xi):
    p0, p1 = prices[ei], prices[xi]
    d0, d1 = dates[ei], dates[xi]
    b0, b1 = bench.get(d0), bench.get(d1)
    if not p0 or not p1 or not b0 or not b1:
        return None
    try:
        sr = (float(p1) - float(p0)) / float(p0)
        br = (float(b1) - float(b0)) / float(b0)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    hold = di.get(d1, 0) - di.get(d0, 0)
    return ((sr - br) * 100.0, hold)
#
def _num_state(adj, enter_at, exit_below):
    if adj is None:
        return "?"
    try:
        a = float(adj)
    except (TypeError, ValueError):
        return "?"
    if a >= enter_at:
        return "IN"
    if a < exit_below:
        return "OUT"
    return "MID"
#
def _trades_from_data(by_ticker, bench, di, enter_at, exit_below, smooth_gap):
    """Model's rule as a state machine on adj_composite: enter when >=enter_at,
    hold through MID, exit when <exit_below. One trade per entry (open trades
    marked to latest price). Left-censored positions (IN from first row) skipped."""
    trades = []
    for tk, trows in by_ticker.items():
        trows.sort(key=lambda r: r["signal_date"])
        dates = [r["signal_date"] for r in trows]
        prices = [r.get("price") for r in trows]
        states = _coalesce([_num_state(r.get(_SCORE_FIELD), enter_at, exit_below) for r in trows], smooth_gap)
        n = len(states)
        if n < 2:
            continue
        in_pos = states[0] == "IN"
        censored = in_pos
        entry_i = 0 if in_pos else None
        for i in range(1, n):
            s = states[i]
            if not in_pos:
                if s == "IN":
                    in_pos = True; entry_i = i; censored = False
            else:
                if s == "OUT":
                    if not censored:
                        rr = _trade_excess(prices, dates, bench, di, entry_i, i)
                        if rr is not None:
                            trades.append((rr[0], True, rr[1]))
                    in_pos = False; entry_i = None; censored = False
        if in_pos and not censored:
            rr = _trade_excess(prices, dates, bench, di, entry_i, n - 1)
            if rr is not None:
                trades.append((rr[0], False, rr[1]))
    return trades
#
def _summarize_trades(trades, enter_at, exit_below, since):
    base = {"enter_at": enter_at, "exit_below": exit_below, "n_trades": 0,
            "n_closed": 0, "n_open": 0, "win_rate_all": None,
            "win_rate_closed": None, "avg_excess_all": None,
            "avg_excess_closed": None, "median_hold_sessions": None,
            "since": since, "benchmark": "SPY"}
    if not trades:
        return base
    import statistics
    all_ex = [t[0] for t in trades]
    closed_ex = [t[0] for t in trades if t[1]]
    holds = [t[2] for t in trades]
    def _wr(xs):
        return round(100.0 * sum(1 for x in xs if x > 0) / len(xs), 1) if xs else None
    base.update({
        "n_trades": len(trades), "n_closed": len(closed_ex),
        "n_open": len(trades) - len(closed_ex),
        "win_rate_all": _wr(all_ex), "win_rate_closed": _wr(closed_ex),
        "avg_excess_all": round(sum(all_ex) / len(all_ex), 2),
        "avg_excess_closed": round(sum(closed_ex) / len(closed_ex), 2) if closed_ex else None,
        "median_hold_sessions": int(statistics.median(holds)) if holds else None,
    })
    return base
#
def _load_for_trades(sb, start):
    rows = _fetch_window(sb, start)
    bench = _load_benchmark(sb, start)
    if not rows or not bench:
        return None, None, None
    all_dates = sorted({r["signal_date"] for r in rows if r.get("signal_date")})
    di = {d: i for i, d in enumerate(all_dates)}
    by_ticker = defaultdict(list)
    for r in rows:
        if r.get("signal_date"):
            by_ticker[r["ticker"]].append(r)
    return by_ticker, bench, di
#
def compute_trade_stats(as_of=None, history_days=90, enter_at=60, exit_below=45, smooth_gap=1, sb=None):
    """Per-trade return vs SPY under the model's enter/exit rule. See module doc."""
    sb = _resolve_sb(sb)
    start = (_parse_ref(as_of) - timedelta(days=history_days)).isoformat()
    if sb is None:
        return _summarize_trades([], enter_at, exit_below, start)
    by_ticker, bench, di = _load_for_trades(sb, start)
    if by_ticker is None:
        return _summarize_trades([], enter_at, exit_below, start)
    trades = _trades_from_data(by_ticker, bench, di, enter_at, exit_below, smooth_gap)
    return _summarize_trades(trades, enter_at, exit_below, start)
#
def sweep_exit_thresholds(as_of=None, history_days=120, enter_at=60,
                          exits=(45, 50, 55, 60), smooth_gap=1, sb=None):
    """Same trade test, swept over exit_below values (single fetch). Use to
    UNDERSTAND exit sensitivity; choose on principle, not the max backtest."""
    sb = _resolve_sb(sb)
    start = (_parse_ref(as_of) - timedelta(days=history_days)).isoformat()
    if sb is None:
        return []
    by_ticker, bench, di = _load_for_trades(sb, start)
    if by_ticker is None:
        return []
    out = []
    for xb in exits:
        trades = _trades_from_data(by_ticker, bench, di, enter_at, xb, smooth_gap)
        out.append(_summarize_trades(trades, enter_at, xb, start))
    return out
#
def format_trade_line(stats: dict) -> str:
    if not stats or not stats.get("n_trades"):
        return ""
    wr = stats.get("win_rate_all")
    if wr is None:
        return ""
    s = "Held to the model's exit rule: " + str(wr) + "% of " + str(stats["n_trades"]) + " HIGH-conviction trades beat SPY"
    ax = stats.get("avg_excess_all")
    if ax is not None:
        s += " (avg " + ("%+.1f" % ax) + " pts vs SPY"
        if stats.get("median_hold_sessions") is not None:
            s += ", ~" + str(stats["median_hold_sessions"]) + "-session hold"
        s += ")"
    return s + "."
#
if __name__ == "__main__":
    import collections
    every = get_validated_signals(max_winners=None, max_losers=None)
    print(collections.Counter(s["kind"] for s in every))
    print("--- wrap slate ---")
    print(format_wrap_block(get_validated_signals()) or "(none)")
    print("--- naive 10-session hit rates ---")
    print(compute_hit_rates())
    print("--- exit-threshold sweep (enter>=60, full history) ---")
    for r in sweep_exit_thresholds(history_days=120):
        print("exit<" + str(r["exit_below"]) + ": win " + str(r["win_rate_all"])
              + "% | avg excess " + str(r["avg_excess_all"]) + " pts | "
              + str(r["n_trades"]) + " trades | ~" + str(r["median_hold_sessions"]) + "-session hold")
