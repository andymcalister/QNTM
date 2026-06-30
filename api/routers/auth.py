"""
QNTM API — auth bridge endpoints.

POST /api/auth/verify
    Validate a bridge token minted by Streamlit. The Next.js app calls this from
    its server-side handoff route: it receives the token in the URL fragment,
    POSTs it here, and on `valid: true` sets its own httpOnly session cookie and
    drops the user on the screener. Invalid/expired → bounce back to login.

Keeping verification on the API (not in the Next app) means the shared secret
lives only on the Streamlit + API services, never in the Vercel/Next env.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from ..auth import verify_token, get_current_user as _resolve_user, TokenError

router = APIRouter(prefix="/api/auth", tags=["auth"])


class VerifyRequest(BaseModel):
    token: str


class VerifyResponse(BaseModel):
    valid: bool
    user_id: Optional[str] = None
    email: Optional[str] = None
    plan: Optional[str] = None
    exp: Optional[int] = None


@router.post("/verify", response_model=VerifyResponse)
def verify(req: VerifyRequest):
    try:
        claims = verify_token(req.token)
    except TokenError:
        # Uniform 401 — never reveal expired-vs-tampered to the caller.
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    return VerifyResponse(
        valid=True,
        user_id=claims.get("sub"),
        email=claims.get("email"),
        plan=claims.get("plan"),
        exp=claims.get("exp"),
    )


# ── Reusable dependency for protected routers (watchlist/portfolio later) ──────
def current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    """FastAPI dependency: returns verified claims or raises 401. Use as
    `user: dict = Depends(current_user)` on any endpoint that needs the caller."""
    try:
        return _resolve_user(authorization)
    except TokenError:
        raise HTTPException(status_code=401, detail="not_authenticated")


@router.get("/me", response_model=VerifyResponse)
def me(user: dict = Depends(current_user)):
    """Echo the authenticated caller — handy for the Next app to confirm a
    session cookie is still valid (it forwards the token as a Bearer header)."""
    return VerifyResponse(
        valid=True,
        user_id=user.get("sub"),
        email=user.get("email"),
        plan=user.get("plan"),
        exp=user.get("exp"),
    )
