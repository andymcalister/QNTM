"""
QNTM API — portfolio (holdings, authed read-write).

Same auth model as the watchlist: user_id always from the verified token, never
client input. Free plan is capped at 10 holdings (Pro unlimited); the cap is
enforced here on add and surfaced as HTTP 402 so the client can upsell.

GET    /api/portfolio           holdings + conviction/P&L summary
POST   /api/portfolio           body {ticker, shares, avg_cost} — add/update
DELETE /api/portfolio/{ticker}  remove
"""

from fastapi import APIRouter, Depends, HTTPException

from ..schemas import (PortfolioResponse, HoldingItem, PortfolioSummary,
                       AddHoldingRequest, Regime)
from ..data import (load_portfolio, upsert_holding, delete_holding,
                    portfolio_holdings, load_universe)
from .auth import current_user

router = APIRouter(prefix="/api", tags=["portfolio"])

FREE_MAX_HOLDINGS = 10


def _regime() -> Regime:
    _rows, regime, _as_of = load_universe()
    return Regime(label=regime.get("label", "NEUTRAL"), vix=regime.get("vix"),
                  event=regime.get("event"), summary=regime.get("summary"))


@router.get("/portfolio", response_model=PortfolioResponse)
def get_portfolio(user: dict = Depends(current_user)):
    data = load_portfolio(user.get("sub"))
    return PortfolioResponse(
        regime=_regime(),
        summary=PortfolioSummary(**data["summary"]),
        holdings=[HoldingItem(**h) for h in data["holdings"]],
    )


@router.post("/portfolio")
def post_portfolio(req: AddHoldingRequest, user: dict = Depends(current_user)):
    uid = user.get("sub")
    plan = (user.get("plan") or "free").lower()
    tk = req.ticker.strip().upper()
    if plan == "free":
        held = {h["ticker"] for h in portfolio_holdings(uid)}
        if tk not in held and len(held) >= FREE_MAX_HOLDINGS:
            raise HTTPException(status_code=402, detail="holdings_limit_reached")
    if not upsert_holding(uid, tk, req.shares, req.avg_cost):
        raise HTTPException(status_code=400, detail="could_not_add_holding")
    return {"ok": True, "ticker": tk}


@router.delete("/portfolio/{ticker}")
def delete_portfolio(ticker: str, user: dict = Depends(current_user)):
    if not delete_holding(user.get("sub"), ticker):
        raise HTTPException(status_code=400, detail="could_not_remove_holding")
    return {"ok": True, "ticker": ticker.strip().upper()}
