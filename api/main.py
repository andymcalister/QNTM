"""
QNTM API — application entrypoint.

Run (from the repo root, so engine imports resolve):

    uvicorn api.main:app --host 0.0.0.0 --port $PORT

This is the thin HTTP layer over QNTM's existing Python engine. Phase 1 starts
with the screener (read-only); watchlist / stock-detail / portfolio endpoints
mount here later behind the same app, and authed endpoints will add a
dependency that verifies the caller's session token (TODO below).
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import screener, auth, macro, movers, watchlist, stock, portfolio, model, gems, simulator, alerts, account, admin, outlook

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI(
    title="QNTM API",
    version="0.1.0",
    description="Read layer over the QNTM conviction engine. Phase 1: screener.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],  # DELETE for watchlist removal
    allow_headers=["*"],
)

app.include_router(screener.router)
app.include_router(auth.router)
app.include_router(macro.router)
app.include_router(movers.router)
app.include_router(watchlist.router)
app.include_router(stock.router)
app.include_router(portfolio.router)
app.include_router(model.router)
app.include_router(gems.router)
app.include_router(simulator.router)
app.include_router(alerts.router)
app.include_router(account.router)
app.include_router(admin.router)
app.include_router(outlook.router)


@app.get("/health", tags=["meta"])
def health():
    """Liveness probe for Render. Cheap — does not touch the DB."""
    return {"ok": True, "service": "qntm-api", "version": app.version}


# Auth: the bridge verifies Streamlit-minted tokens (routers/auth.py). The
# screener stays public (its data isn't user-specific); user-specific routers
# added later (watchlist, portfolio) should declare
# `user: dict = Depends(current_user)` from routers.auth.
