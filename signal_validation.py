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
if __name__ == "__main__":
    sigs = get_validated_signals()
    print("[" + str(len(sigs)) + " selected]")
    print(format_wrap_block(sigs) or "(none today)")
