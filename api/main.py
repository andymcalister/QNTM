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
from .routers import screener

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
    allow_methods=["GET"],          # screener is read-only; widen per-endpoint later
    allow_headers=["*"],
)

app.include_router(screener.router)


@app.get("/health", tags=["meta"])
def health():
    """Liveness probe for Render. Cheap — does not touch the DB."""
    return {"ok": True, "service": "qntm-api", "version": app.version}


# TODO (Phase 1, later pages): add a `get_current_user` dependency that verifies
# the caller's QNTM session token, then mount authed routers (watchlist,
# portfolio) that depend on it. Screener stays public — its data isn't
# user-specific.
