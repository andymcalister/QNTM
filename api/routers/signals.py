"""
QNTM API - public signal archive.
GET /api/signals
    The complete forward-only record. Every episode is returned, but rows are
    tagged so the page can separate the model's actual CALLS (entered_high,
    sustained_high, weakened) from names it never rated (sustained_low - the
    residual bucket, heavy with sub-dollar and microcap names).
    Outcomes are reported benchmark-RELATIVE against SPY, never as absolute
    "% up". Hit direction depends on the call: a HIGH-side episode hits when it
    BEATS SPY; a weakened episode hits when it LAGS SPY.
"""
from typing import Optional

from fastapi import APIRouter, Header, Query
#
router = APIRouter(prefix="/api", tags=["signals"])
#
ARCHIVE_PARAMS = dict(require_confirmed=False, min_move_pct=0.0,
                      min_sustained_move_pct=0.0,
                      max_winners=100000, max_losers=100000)
HIGH_KINDS = ("entered_high", "sustained_high")
CALL_KINDS = ("entered_high", "sustained_high", "weakened")
# Public scope withholds recent rows by TIME ONLY - never by outcome - so the
# published claim "complete record, delayed N days" stays verifiable.
PUBLIC_DELAY_DAYS = 14
#
def _bench():
    from data_refresh import _get_supabase
    sb = _get_supabase()
    out, lo, page = {}, 0, 1000
    while True:
        r = (sb.table("benchmark_price").select("d,close")
             .order("d", desc=False).range(lo, lo + page - 1).execute())
        b = r.data or []
        for row in b:
            d, c = row.get("d"), row.get("close")
            if d is None or c is None:
                continue
            try:
                out[str(d)[:10]] = float(c)
            except (TypeError, ValueError):
                pass
        if len(b) < page:
            break
        lo += page
    return out
#
def _on_or_before(bench, ds, d):
    if d in bench:
        return bench[d]
    p = [x for x in ds if x <= d]
    return bench[p[-1]] if p else None
#
def _rate(rows):
    ok = [r for r in rows if r.get("hit") is not None]
    n_hit = sum(1 for r in ok if r["hit"])
    return {"n": len(ok), "n_hit": n_hit,
            "rate": round(100.0 * n_hit / len(ok), 1) if ok else None}
#
def _viewer(authorization):
    """Return the signed-in user, or None. Never raises."""
    if not authorization:
        return None
    try:
        from .auth import current_user
        return current_user(authorization) or None
    except Exception:
        return None


def _hit_rates():
    """Headline stat. Full population of HIGH/LOW entry runs, fixed forward
    window, benchmark-relative. This - not the episode rates below - is the
    number the page headlines; episode rates are truncated wherever
    benchmark_price does not reach back to the event date."""
    try:
        import signal_validation as sv
        return sv.compute_hit_rates()
    except Exception as e:
        return {"error": repr(e)[:200]}


@router.get("/signals")
def signals(history_days: int = Query(120, ge=1, le=720),
            scope: str = Query("public", pattern="^(full|public)$"),
            authorization: Optional[str] = Header(default=None)):
    import signal_validation as sv
    if not isinstance(history_days, int):
        history_days = 120
    # scope=full is members-only. Downgrade silently rather than 401 so the
    # public page never breaks on a stale or missing session.
    if scope == "full" and not _viewer(authorization):
        scope = "public"
    rows = sv.get_validated_signals(history_days=history_days, **ARCHIVE_PARAMS)
    bench = _bench()
    bd = sorted(bench)
    spy_now = bench[bd[-1]] if bd else None
    out = []
    for x in rows:
        ed = str(x.get("event_date"))[:10]
        st = _on_or_before(bench, bd, ed)
        spy_move = round(100.0 * (spy_now / st - 1.0), 2) if (st and spy_now) else None
        try:
            excess = round(float(x.get("move_pct")) - spy_move, 2) if spy_move is not None else None
        except (TypeError, ValueError):
            excess = None
        kind = x.get("kind")
        hit = None
        if excess is not None:
            if kind in HIGH_KINDS:
                hit = excess > 0
            elif kind == "weakened":
                hit = excess < 0
        r = dict(x)
        r.update(spy_move_pct=spy_move, excess_pct=excess, hit=hit,
                 is_call=kind in CALL_KINDS,
                 group="call" if kind in CALL_KINDS else "unrated")
        out.append(r)
    out.sort(key=lambda z: (str(z.get("event_date")), z.get("ticker") or ""), reverse=True)
    withheld = 0
    if scope == "public":
        import datetime as _dt
        cutoff = (_dt.date.today()
                  - _dt.timedelta(days=PUBLIC_DELAY_DAYS)).isoformat()
        keep = [r for r in out if str(r.get("event_date"))[:10] <= cutoff]
        withheld = len(out) - len(keep)
        out = keep
    calls = [r for r in out if r["is_call"]]
    dates = [str(x.get("event_date"))[:10] for x in rows if x.get("event_date")]
    kinds = {}
    for x in rows:
        kinds[x.get("kind")] = kinds.get(x.get("kind"), 0) + 1
    return {
        "scope": scope, "delay_days": PUBLIC_DELAY_DAYS,
        "withheld_count": withheld,
        "count": len(out), "n_calls": len(calls),
        "n_unrated": len(out) - len(calls),
        "since": min(dates) if dates else None,
        "as_of": bd[-1] if bd else None,
        "benchmark": "SPY", "kinds": kinds,
        "hit_rates": _hit_rates(),
        "episode_high_side": _rate([r for r in out if r.get("kind") in HIGH_KINDS]),
        "episode_weakened": _rate([r for r in out if r.get("kind") == "weakened"]),
        "notes": {
            "unrated": ("LOW indicates the absence of conviction, not a bearish "
                        "call. These names are shown for completeness and are "
                        "excluded from every rate above."),
            "thresholds": ("Conviction thresholds changed 2026-07-16 "
                           "(HIGH 60 to 65, LOW 45 to 55). Labels before that "
                           "date are preserved as published."),
            "universe": ("The scored universe was reconstituted 2026-06-22 "
                         "(834 to 1402 names)."),
        },
        "signals": out,
    }
