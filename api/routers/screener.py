"""
QNTM API — screener endpoint.

GET /api/screener

The screener is the highest-traffic, read-only page, which makes it the right
first port off Streamlit. Data is precomputed in signal_log by the crons; this
endpoint loads the latest scored universe (cached), then filters / sorts /
paginates in Python. No scoring happens here — that all lives in the engine.
"""

from typing import Optional
from fastapi import APIRouter, Query

from ..data import load_universe
from ..schemas import ScreenerResponse, ScreenerRow, Regime

router = APIRouter(prefix="/api", tags=["screener"])

# Fields the client is allowed to sort by → guards against arbitrary keys.
_SORTABLE = {
    "score", "composite", "momentum", "quality",
    "volume", "value", "sentiment", "price", "ticker",
}


@router.get("/screener", response_model=ScreenerResponse)
def get_screener(
    conviction: str = Query("all", description="all | HIGH | MODERATE | LOW"),
    sector: Optional[str] = Query(None, description="exact sector name, e.g. 'Technology'"),
    search: Optional[str] = Query(None, description="ticker contains (case-insensitive)"),
    gems_only: bool = Query(False, description="restrict to hidden gems"),
    sort: str = Query("score", description="sort field"),
    order: str = Query("desc", description="asc | desc"),
    limit: int = Query(50, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    rows, regime, as_of = load_universe()

    # ── filter ────────────────────────────────────────────────────────────────
    conv = conviction.upper()
    if conv in {"HIGH", "MODERATE", "LOW"}:
        rows = [r for r in rows if r["conviction"] == conv]
    if sector:
        rows = [r for r in rows if r["sector"] == sector]
    if gems_only:
        rows = [r for r in rows if r["is_hidden_gem"]]
    if search:
        q = search.strip().upper()
        rows = [r for r in rows if q in r["ticker"].upper()]

    # ── sort ──────────────────────────────────────────────────────────────────
    key = sort if sort in _SORTABLE else "score"
    reverse = order.lower() != "asc"
    if key == "ticker":
        rows = sorted(rows, key=lambda r: r["ticker"], reverse=reverse)
    else:
        # numeric; None prices sort to the bottom regardless of direction
        rows = sorted(
            rows,
            key=lambda r: (r.get(key) is not None, r.get(key) or 0.0),
            reverse=reverse,
        )

    # ── paginate ──────────────────────────────────────────────────────────────
    total = len(rows)
    page = rows[offset: offset + limit]

    return ScreenerResponse(
        as_of=as_of,
        regime=Regime(**regime),
        total=total,
        count=len(page),
        offset=offset,
        limit=limit,
        rows=[ScreenerRow(**r) for r in page],
    )
