"""
QNTM API — hidden gems (Pro-gated).

GET /api/hidden-gems   (auth required)
    Curated shortlist (max 12) of under-followed mid/small-caps clearing the
    high-conviction bar, each with a reason string. Faithful port of the
    Streamlit detect_hidden_gems (regime-set thresholds, mega/large-cap
    exclusion, size gate).

    HARD PAYWALL: entitlement mirrors Streamlit's is_pro() / PLAN_LIMITS["gems"]
    — plan in ("pro", "institutional"). Founding members are comped to "pro", so
    they unlock automatically. Free plans get ONLY the count + reason strings for
    the teaser; ticker names and row data never leave the server.
"""

from fastapi import APIRouter, Depends

from ..schemas import HiddenGemsResponse, GemRow
from ..data import load_hidden_gems
from .auth import current_user

router = APIRouter(prefix="/api", tags=["gems"])

_GEMS_ENTITLED = {"pro", "institutional"}


@router.get("/hidden-gems", response_model=HiddenGemsResponse)
def hidden_gems(user: dict = Depends(current_user)):
    d = load_hidden_gems()
    gems = d.get("gems") or []
    plan = (user.get("plan") or "free").lower()
    base = dict(regime=d.get("regime") or "NEUTRAL", threshold=d.get("threshold") or 62,
                as_of=d.get("as_of"), count=d.get("count") or 0)

    if plan in _GEMS_ENTITLED:
        return HiddenGemsResponse(locked=False, gems=[GemRow(**g) for g in gems],
                                  teaser_reasons=[], **base)

    # Locked: strip everything identifying — no tickers, no scores, no row data.
    # Only the count and one reason per gem cross the wire, for the teaser.
    teaser = [g["gem_reasons"][0] for g in gems if g.get("gem_reasons")][:6]
    return HiddenGemsResponse(locked=True, gems=[], teaser_reasons=teaser, **base)
