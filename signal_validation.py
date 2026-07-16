"""QNTM signal validation - "what the model flagged before the move".
Reads the dated signal_log history and surfaces grounded, verifiable signals:
tickers whose conviction crossed into HIGH (or weakened out of it) N sessions
ago, with the price move since. Observational only - no prediction claims.
Feeds the Day Wrap tail and the /signals archive.
Public:
    get_validated_signals(...) -> list[dict]
    format_wrap_block(signals) -> str
Selection: balanced by default - max_up bullish + max_down bearish, bullish
    first. Pass max_up=None, max_down=None (and require_confirmed=False) for
    the full, non-cherry-picked /signals archive.
Signal dict keys: ticker, kind (entered_high|weakened), event_date,
    sessions_ago, price_then, price_now, move_pct, conviction_then,
    conviction_now.
NOTE (confirm with Andy): label is derived from `adj_composite` at ≥60 / ≥45.
    If your site's bands differ, or signal_log `signal` already holds the text
    label, tell me and I swap _label()/_SCORE_FIELD.
Env overrides: QNTM_CONVICTION_FIELD, QNTM_CONVICTION_HIGH_MIN,
    QNTM_CONVICTION_MOD_MIN, QNTM_SIGNALS_ARCHIVE_URL.
"""
from __future__ import annotations
import os
from collections import defaultdict
from datetime import date, timedelta
#
_SCORE_FIELD = os.getenv("QNTM_CONVICTION_FIELD", "adj_composite")
_HIGH_MIN = float(os.getenv("QNTM_CONVICTION_HIGH_MIN", "60"))
_MOD_MIN = float(os.getenv("QNTM_CONVICTION_MOD_MIN", "45"))
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
def _label(score):
    if score is None:
        return None
    try:
        score = float(score)
    except (TypeError, ValueError):
        return None
    if score >= _HIGH_MIN:
        return "HIGH"
    if score >= _MOD_MIN:
        return "MODERATE"
    return "LOW"
#
def _short_date(iso: str) -> str:
    try:
        y, m, d = str(iso).split("-")
        return _MON[int(m)] + " " + str(int(d))
    except Exception:
        return str(iso)
#
def _fetch_window(sb, start_date: str) -> list:
    cols = "ticker,signal_date," + _SCORE_FIELD + ",price"
    rows = []
    page = 0
    size = 1000
    while page < 50:
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
def _detect(seq: list):
    if len(seq) < 2:
        return None
    cur = seq[-1][1]
    if cur == "HIGH":
        i = len(seq) - 1
        while i > 0 and seq[i - 1][1] == "HIGH":
            i -= 1
        if i == 0:
            return None
        e = seq[i]
        return {"kind": "entered_high", "event_date": e[0], "event_price": e[2], "conviction_then": e[3]}
    j = None
    for k in range(len(seq) - 1, -1, -1):
        if seq[k][1] == "HIGH":
            j = k
            break
    if j is None or j == len(seq) - 1:
        return None
    e = seq[j + 1]
    return {"kind": "weakened", "event_date": e[0], "event_price": e[2], "conviction_then": e[3]}
#
def get_validated_signals(as_of=None, lookback_days=21, min_sessions=2,
                          min_move_pct=4.0, max_up=2, max_down=1,
                          require_confirmed=True, top_n=None, sb=None):
    """Balanced by default: up to max_up bullish + max_down bearish, bullish
    first. For the full /signals archive call max_up=None, max_down=None,
    require_confirmed=False."""
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
    start = (ref - timedelta(days=lookback_days)).isoformat()
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
        seq = [(r["signal_date"], _label(r.get(_SCORE_FIELD)), r.get("price"), r.get(_SCORE_FIELD)) for r in trows]
        ev = _detect(seq)
        if not ev:
            continue
        sess = latest_i - date_index.get(ev["event_date"], latest_i)
        if sess < min_sessions:
            continue
        price_then = ev["event_price"]
        price_now = seq[-1][2]
        if not price_then or not price_now:
            continue
        try:
            move = (float(price_now) - float(price_then)) / float(price_then) * 100.0
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if require_confirmed:
            if ev["kind"] == "entered_high" and move < min_move_pct:
                continue
            if ev["kind"] == "weakened" and move > -min_move_pct:
                continue
        out.append({
            "ticker": tk,
            "kind": ev["kind"],
            "event_date": ev["event_date"],
            "sessions_ago": sess,
            "price_then": round(float(price_then), 2),
            "price_now": round(float(price_now), 2),
            "move_pct": round(move, 1),
            "conviction_then": ev["conviction_then"],
            "conviction_now": seq[-1][3],
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
    sess = str(s["sessions_ago"]) + " sessions"
    mv = ("%+.1f%%" % s["move_pct"]) + " since"
    if s["kind"] == "entered_high":
        return _BULLET + " " + s["ticker"] + " " + _DASH + " HIGH conviction since " + d + " (" + sess + "), " + mv
    return _BULLET + " " + s["ticker"] + " " + _DASH + " conviction slipped " + d + " (" + sess + "), " + mv
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
