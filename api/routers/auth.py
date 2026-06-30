"""
QNTM auth bridge — signed-token mint & verify.

This module is the SINGLE source of truth for the cross-app token. It is used by
*both* sides of the bridge:

  * Streamlit (app.py) imports `create_token` to mint a short-lived token for a
    logged-in user when it hands them off to the new Next.js screener.
  * FastAPI (this API) imports `verify_token` / `get_current_user` to validate
    that token.

Because mint and verify share one implementation and one secret, they can never
drift. The secret (QNTM_BRIDGE_SECRET) must be set identically on the Streamlit
service and this API service.

Token = JWT (HS256). Claims: sub (user id), email (optional), plan (optional),
iat, exp, iss, aud. Short TTL — it only needs to live long enough to bridge a
logged-in user from Streamlit into the Next.js app, which then holds its own
session cookie.
"""

from __future__ import annotations

import time
import logging
from typing import Optional

import jwt  # PyJWT

from .config import settings

log = logging.getLogger("qntm.api.auth")

_ALGO = "HS256"
_ISS = "qntm-streamlit"
_AUD = "qntm-api"


class TokenError(Exception):
    """Raised on any mint/verify failure. The message is for logs only — never
    surface the reason to the caller (don't leak expired-vs-tampered)."""


def create_token(
    user_id: str,
    email: Optional[str] = None,
    plan: Optional[str] = None,
    ttl: Optional[int] = None,
) -> str:
    """Mint a signed bridge token for a logged-in user. Called by Streamlit."""
    if not settings.BRIDGE_SECRET:
        raise TokenError("QNTM_BRIDGE_SECRET not configured")
    now = int(time.time())
    ttl = int(ttl if ttl is not None else settings.BRIDGE_TOKEN_TTL)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + ttl,
        "iss": _ISS,
        "aud": _AUD,
    }
    if email:
        payload["email"] = email
    if plan:
        payload["plan"] = plan
    return jwt.encode(payload, settings.BRIDGE_SECRET, algorithm=_ALGO)


def verify_token(token: str) -> dict:
    """Validate a bridge token. Returns the claims dict or raises TokenError.

    Verifies signature, expiry, issued-at, audience, and that the required
    claims are present. Any failure → TokenError (caller maps to 401)."""
    if not settings.BRIDGE_SECRET:
        raise TokenError("QNTM_BRIDGE_SECRET not configured")
    try:
        payload = jwt.decode(
            token,
            settings.BRIDGE_SECRET,
            algorithms=[_ALGO],
            audience=_AUD,
            options={"require": ["exp", "iat", "sub"]},
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise TokenError("expired")
    except jwt.InvalidTokenError as e:
        raise TokenError(f"invalid: {e}")


# ── FastAPI dependency for protecting endpoints ───────────────────────────────
# Screener stays public (data isn't user-specific), but user-specific endpoints
# added later (watchlist, portfolio) declare `user = Depends(get_current_user)`
# and get the verified claims, or a 401 if the Bearer token is missing/bad.
def get_current_user(authorization: Optional[str] = None) -> dict:
    """Resolve the caller from an `Authorization: Bearer <token>` header.

    Imported and wired as a FastAPI dependency in routers that need auth (see
    routers/auth.py for the Header-bound wrapper). Kept header-agnostic here so
    it's unit-testable without FastAPI."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise TokenError("missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    return verify_token(token)
