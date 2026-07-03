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

from ..auth import verify_token, create_token, get_current_user as _resolve_user, TokenError
from .. import authcore
from .. import data as _data

DISCLAIMER_VERSION = "2026-07-03"

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Session tokens live much longer than the 15-min bridge token — this is the
# actual login duration. The Next app stores it in the httpOnly cookie.
SESSION_TTL = 7 * 24 * 3600      # 7 days
MFA_CHALLENGE_TTL = 5 * 60       # 5 min to enter the TOTP code


class VerifyRequest(BaseModel):
    token: str


class VerifyResponse(BaseModel):
    valid: bool
    user_id: Optional[str] = None
    email: Optional[str] = None
    plan: Optional[str] = None
    exp: Optional[int] = None
    founding_member: bool = False
    billing_active: bool = False


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
    """Authenticated caller + live plan/founding/billing for the nav pill."""
    stt = _data.get_account_status(user.get("sub"))
    return VerifyResponse(
        valid=True,
        user_id=user.get("sub"),
        email=user.get("email"),
        plan=stt.get("plan", "free"),
        exp=user.get("exp"),
        founding_member=bool(stt.get("founding_member")),
        billing_active=bool(stt.get("billing_active")),
    )


# ══════════════════════════════════════════════════════════════════════════════
# NATIVE AUTH — login / MFA / register directly against the users table, so the
# new app no longer depends on the Streamlit app for authentication. Reuses the
# exact db.py crypto scheme via authcore. The Next server routes call these and
# set the httpOnly session cookie on qntm.live.
# ══════════════════════════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    email: str
    password: str


class MfaRequest(BaseModel):
    challenge: str
    code: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str = ""
    claim_founding: bool = False
    disclaimer_ack: bool = False


def _session_user(u: dict) -> dict:
    return {"id": u.get("id") or u.get("sub"), "email": u.get("email"),
            "plan": u.get("plan", "free"), "full_name": u.get("full_name", "")}


@router.post("/login")
def login(req: LoginRequest):
    res = authcore.login(req.email, req.password)
    if not res.get("success"):
        raise HTTPException(status_code=401, detail=res.get("error", "Invalid email or password"))
    u = res["user"]
    # 2FA gate intentionally dropped: mint the session on valid password alone.
    # (/mfa + authcore.verify_totp are left in place, dormant, so 2FA can be
    # re-enabled later without a rebuild.)
    session = create_token(u["id"], email=u.get("email"), plan=u.get("plan", "free"), ttl=SESSION_TTL)
    return {"ok": True, "mfa_required": False, "session": session, "user": _session_user(u)}


@router.post("/mfa")
def mfa(req: MfaRequest):
    try:
        claims = verify_token(req.challenge)
    except TokenError:
        raise HTTPException(status_code=401, detail="challenge_expired")
    uid = claims.get("sub")
    info = authcore.get_user_mfa(uid)
    if not authcore.verify_totp(info.get("totp_secret") or "", req.code):
        raise HTTPException(status_code=401, detail="invalid_code")
    email, plan = claims.get("email"), claims.get("plan", "free")
    session = create_token(uid, email=email, plan=plan, ttl=SESSION_TTL)
    return {"ok": True, "session": session, "user": {"id": uid, "email": email, "plan": plan}}


@router.post("/register")
def register(req: RegisterRequest):
    if not req.email or not req.password:
        raise HTTPException(status_code=400, detail="Email and password are required")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if not req.disclaimer_ack:
        raise HTTPException(status_code=400, detail="You must acknowledge the research-tool disclaimer to create an account")
    res = authcore.register(req.email, req.password, req.full_name or "")
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Registration failed"))
    uid = res["user_id"]
    _data.set_disclaimer_ack(uid, DISCLAIMER_VERSION)
    plan, founding = "free", False
    if req.claim_founding and _data.claim_founding_member(uid):
        plan, founding = "pro", True
    try:
        authcore.request_email_verification(req.email)
    except Exception:
        pass
    session = create_token(uid, email=req.email.lower().strip(), plan=plan, ttl=SESSION_TTL)
    return {"ok": True, "session": session, "founding": founding,
            "user": {"id": uid, "email": req.email.lower().strip(), "plan": plan}}

# ══════════════════════════════════════════════════════════════════════════════
# PASSWORD RESET — public, token-gated. Request emails a native reset link;
# validate peeks (renders the form); reset consumes the one-time token and sets
# the new password. Uniform "ok" on request so accounts can't be enumerated.
# ══════════════════════════════════════════════════════════════════════════════

class ForgotRequest(BaseModel):
    email: str


class ResetValidateRequest(BaseModel):
    token: str


class ResetRequest(BaseModel):
    token: str
    password: str


@router.post("/request-reset")
def request_reset(req: ForgotRequest):
    authcore.request_password_reset(req.email or "")
    return {"ok": True}


@router.post("/reset-validate")
def reset_validate(req: ResetValidateRequest):
    return {"ok": True, "valid": authcore.peek_auth_token(req.token or "", "reset")}


@router.post("/reset")
def reset(req: ResetRequest):
    res = authcore.reset_password(req.token or "", req.password or "")
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Could not reset password"))
    return {"ok": True}

# ══════════════════════════════════════════════════════════════════════════════
# EMAIL VERIFICATION — request emails a native confirm link; verify-email
# consumes the one-time token and flips users.email_verified. Distinct from the
# bridge /verify endpoint (that validates cross-app tokens). Uniform "ok" on
# request so accounts can't be enumerated.
# ══════════════════════════════════════════════════════════════════════════════

class RequestVerifyRequest(BaseModel):
    email: str


class VerifyEmailRequest(BaseModel):
    token: str


@router.post("/request-verify")
def request_verify(req: RequestVerifyRequest):
    authcore.request_email_verification(req.email or "")
    return {"ok": True}


@router.post("/verify-email")
def verify_email(req: VerifyEmailRequest):
    res = authcore.consume_verify_token(req.token or "")
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Could not verify email"))
    return {"ok": True}


@router.get("/founding-spots")
def founding_spots():
    """Public: how many free founding spots remain (drives the signup claim)."""
    return {"remaining": _data.founding_spots_remaining(), "limit": _data.FOUNDING_LIMIT}
