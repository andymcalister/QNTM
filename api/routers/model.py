"""
QNTM API — model portfolio / track record.

GET /api/model-portfolio
    The live model cohort's equity curve vs SPY, track-record stats, current open
    positions (enriched with live conviction from signal_log), closed trades, and
    sector spread. Faithful port of the Streamlit `_track_record_data` ledger
    replay ($100K base, $2K/position, daily mark-to-market), computed DB-only from
    signal_log + benchmark_price. Cached briefly (MODEL_CACHE_TTL_SECONDS) so it
    reflects the intraday price cron without replaying on every request.
"""

from fastapi import APIRouter

from ..schemas import (
    ModelPortfolioResponse, ModelStats, EquityPoint, ModelPosition, ExitTrade, SectorCount, DayMove, TodayMoves,
)
from ..data import load_model_portfolio

router = APIRouter(prefix="/api", tags=["model"])


@router.get("/model-portfolio", response_model=ModelPortfolioResponse)
def model_portfolio():
    d = load_model_portfolio()
    return ModelPortfolioResponse(
        inception=d.get("inception"),
        curve=[EquityPoint(**p) for p in (d.get("curve") or [])],
        stats=ModelStats(**d["stats"]) if d.get("stats") else None,
        day=DayMove(**d["day"]) if d.get("day") else None,
        prices_as_of=d.get("prices_as_of"),
        positions=[ModelPosition(**p) for p in (d.get("positions") or [])],
        exits=[ExitTrade(**x) for x in (d.get("exits") or [])],
        today_moves=TodayMoves(**d["today_moves"]) if d.get("today_moves") else None,
        sector_counts=[SectorCount(**s) for s in (d.get("sector_counts") or [])],
    )
