"""
QNTM API — watchlist (authed read-write).

All endpoints require a valid session (Bearer token, verified). The user_id is
taken from the token's `sub` — never from the request body or path — so a caller
can only ever read or mutate their OWN watchlist, even though writes use the
service-role key that bypasses RLS.

GET    /api/watchlist            list the user's watched tickers (enriched)
POST   /api/watchlist            body {ticker}  — add (validated against universe)
DELETE /api/watchlist/{ticker}   remove
"""

from fastapi import APIRouter, Depends, HTTPException

from ..schemas import WatchlistResponse, WatchlistItem, TickerRequest, Regime
from ..data import load_watchlist, add_watchlist, remove_watchlist, load_universe
from .auth import current_user

router = APIRouter(prefix="/api", tags=["watchlist"])


def _regime() -> Regime:
    _rows, regime, _as_of = load_universe()
    return Regime(
        label=regime.get("label", "NEUTRAL"),
        vix=regime.get("vix"),
        event=regime.get("event"),
        summary=regime.get("summary"),
    )


@router.get("/watchlist", response_model=WatchlistResponse)
def get_watchlist(user: dict = Depends(current_user)):
    uid = user.get("sub")
    items = load_watchlist(uid)
    return WatchlistResponse(
        regime=_regime(),
        count=len(items),
        items=[WatchlistItem(**it) for it in items],
    )


@router.post("/watchlist")
def post_watchlist(req: TickerRequest, user: dict = Depends(current_user)):
    uid = user.get("sub")
    if not add_watchlist(uid, req.ticker):
        raise HTTPException(status_code=400, detail="could_not_add_ticker")
    return {"ok": True, "ticker": req.ticker.strip().upper()}


@router.delete("/watchlist/{ticker}")
def delete_watchlist(ticker: str, user: dict = Depends(current_user)):
    uid = user.get("sub")
    if not remove_watchlist(uid, ticker):
        raise HTTPException(status_code=400, detail="could_not_remove_ticker")
    return {"ok": True, "ticker": ticker.strip().upper()}
