"""
QNTM API — portfolio simulator (Pro-gated).

GET /api/simulator?profile=HIGH|MEDIUM|LOW   (auth required)
    A top-20 sample portfolio for the risk profile (HIGH=momentum, MEDIUM=
    conviction, LOW=quality+value), diversified with a per-sector cap. Faithful
    port of page_simulator's profile_tickers. The client handles the investment
    amount, weighting, and add/remove over these picks.

    HARD PAYWALL (live plan lookup): plan in ("pro","institutional") — founding
    members are comped to pro. Free plans get only a sector/tier teaser; no
    tickers or row data cross the wire.
"""

from fastapi import APIRouter, Depends, Query

from ..schemas import SimulatorResponse, ScreenerRow, SimTeaser
from ..data import load_simulator, get_user_plan
from .auth import current_user

router = APIRouter(prefix="/api", tags=["simulator"])

_SIM_ENTITLED = {"pro", "institutional"}


@router.get("/simulator", response_model=SimulatorResponse)
def simulator(profile: str = Query("MEDIUM"), user: dict = Depends(current_user)):
    d = load_simulator(profile)
    picks = d.get("picks") or []
    plan = get_user_plan(user.get("sub"))   # live — immediate on promotion
    base = dict(profile=d.get("profile") or "MEDIUM", as_of=d.get("as_of"), count=d.get("count") or 0)

    if plan in _SIM_ENTITLED:
        return SimulatorResponse(locked=False, picks=[ScreenerRow(**r) for r in picks], teaser=[], **base)

    # Locked: one blurred row per sector (sector + conviction tier), no tickers.
    teaser: list = []
    seen: set = set()
    for r in picks:
        sec = r.get("sector") or "Unknown"
        if sec in seen:
            continue
        seen.add(sec)
        sc = float(r.get("score") or 50)
        tier = "High" if sc >= 60 else ("Low" if sc < 45 else "Moderate")
        teaser.append(SimTeaser(sector=sec, tier=tier))
        if len(teaser) >= 5:
            break
    return SimulatorResponse(locked=True, picks=[], teaser=teaser, **base)
