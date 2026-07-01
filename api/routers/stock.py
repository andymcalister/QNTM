"""
QNTM API — single-stock detail.

GET /api/stock/{ticker}
    The full enriched screener row for one ticker + its universe percentile +
    the what's-changed deltas (per-pillar + macro overlay, vs the prior scored
    day). Public read, same as the screener. 404 if the ticker isn't scored.
"""

from fastapi import APIRouter, HTTPException

from ..schemas import StockResponse
from ..data import load_stock

router = APIRouter(prefix="/api", tags=["stock"])


@router.get("/stock/{ticker}", response_model=StockResponse)
def stock(ticker: str):
    data = load_stock(ticker)
    if data is None:
        raise HTTPException(status_code=404, detail="ticker_not_found")
    return StockResponse(**data)
