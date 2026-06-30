"""
QNTM API — conviction movers.

GET /api/movers
    Day-over-day conviction movers across the universe for the screener hero's
    "today's conviction moves" feed. Mirrors the Streamlit _conviction_movers
    output (prev→now adj_composite, driver attribution, tier crossings), with the
    macro-driven band collapsed into one summary entry.
"""

from fastapi import APIRouter

from ..schemas import MoversResponse, Mover
from ..data import compute_movers, load_macro_detail

router = APIRouter(prefix="/api", tags=["movers"])


@router.get("/movers", response_model=MoversResponse)
def movers():
    regime = (load_macro_detail() or {}).get("regime") or "NEUTRAL"
    rows = compute_movers()
    return MoversResponse(regime=regime, movers=[Mover(**m) for m in rows])
