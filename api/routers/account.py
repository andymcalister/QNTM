"""
QNTM API — account: notification preferences + phone verification (Pro-gated).

GET  /api/account/notification-prefs      current delivery prefs + phone status
POST /api/account/notification-prefs      save the six delivery toggles
POST /api/account/phone/send-code         store phone + text a 6-digit code
POST /api/account/phone/verify            confirm the code → phone_verified

All auth-required and Pro-gated via LIVE plan lookup (immediate on promotion).
These write the exact users.notifications / phone columns the alerts cron
(alerts_engine.notify) reads, so configuring here closes the delivery loop.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..schemas import (NotificationPrefsResponse, NotificationPrefs,
                       SavePrefsRequest, PhoneSendRequest, PhoneVerifyRequest, SimpleOk)
from ..data import (get_notification_prefs, save_notification_prefs,
                    send_phone_verify_code, verify_phone_code, get_user_plan)
from .auth import current_user
from .. import authcore

router = APIRouter(prefix="/api/account", tags=["account"])

_PREFS_ENTITLED = {"pro", "institutional"}


def _require_pro(user: dict) -> str:
    uid = user.get("sub")
    if get_user_plan(uid) not in _PREFS_ENTITLED:
        raise HTTPException(status_code=403, detail="pro_required")
    return uid


@router.get("/notification-prefs", response_model=NotificationPrefsResponse)
def read_prefs(user: dict = Depends(current_user)):
    uid = user.get("sub")
    if get_user_plan(uid) not in _PREFS_ENTITLED:
        return NotificationPrefsResponse(locked=True)
    d = get_notification_prefs(uid)
    return NotificationPrefsResponse(
        locked=False, prefs=NotificationPrefs(**d["prefs"]),
        phone=d["phone"], phone_verified=d["phone_verified"],
    )


@router.post("/notification-prefs", response_model=SimpleOk)
def write_prefs(req: SavePrefsRequest, user: dict = Depends(current_user)):
    uid = _require_pro(user)
    prefs = {k: v for k, v in req.model_dump().items() if v is not None}
    if not save_notification_prefs(uid, prefs):
        raise HTTPException(status_code=400, detail="could_not_save")
    return SimpleOk(ok=True, message="Preferences saved")


@router.post("/phone/send-code", response_model=SimpleOk)
def phone_send(req: PhoneSendRequest, user: dict = Depends(current_user)):
    uid = _require_pro(user)
    ok, msg = send_phone_verify_code(uid, req.phone)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return SimpleOk(ok=True, message=msg)


@router.post("/phone/verify", response_model=SimpleOk)
def phone_verify(req: PhoneVerifyRequest, user: dict = Depends(current_user)):
    uid = _require_pro(user)
    ok, msg = verify_phone_code(uid, req.code)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return SimpleOk(ok=True, message=msg)

# ── Profile + security (authenticated; not Pro-gated) ─────────────────────────
class ProfileResponse(BaseModel):
    full_name: str = ""
    email: str = ""
    email_verified: bool = False


class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.get("/profile", response_model=ProfileResponse)
def read_profile(user: dict = Depends(current_user)):
    d = authcore.get_profile(user.get("sub"))
    return ProfileResponse(**d) if d else ProfileResponse()


@router.post("/profile")
def write_profile(req: UpdateProfileRequest, user: dict = Depends(current_user)):
    uid = user.get("sub")
    changed = {}
    if req.full_name is not None:
        r = authcore.update_full_name(uid, req.full_name)
        if not r.get("success"):
            raise HTTPException(status_code=400, detail=r.get("error", "Couldn't update name"))
        changed["full_name"] = True
    if req.email is not None:
        r = authcore.update_email(uid, req.email)
        if not r.get("success"):
            raise HTTPException(status_code=400, detail=r.get("error", "Couldn't update email"))
        try:
            authcore.request_email_verification(r.get("email") or req.email)
        except Exception:
            pass
        changed["email"] = True
    return {"ok": True, "changed": changed}


@router.post("/change-password")
def change_pw(req: ChangePasswordRequest, user: dict = Depends(current_user)):
    r = authcore.change_password(user.get("sub"), req.current_password or "", req.new_password or "")
    if not r.get("success"):
        raise HTTPException(status_code=400, detail=r.get("error", "Couldn't change password"))
    return {"ok": True}

# ── Billing / subscription (Stripe; authenticated) ────────────────────────────
import os as _os
from datetime import datetime as _dt, timezone as _tz
import stripe_billing as _billing
import arl as _arl
from ..data import (get_billing_state, set_billing_state, schedule_cancellation,
                    undo_cancellation, set_plan)

_WEB_URL = _os.getenv("PUBLIC_WEB_URL", "https://qntm.live").rstrip("/")


def _iso_from_ts(ts):
    try:
        return _dt.fromtimestamp(int(ts), _tz.utc).date().isoformat() if ts else None
    except Exception:
        return None


class BillingResponse(BaseModel):
    configured: bool = False
    plan: str = "free"
    billing_active: bool = False
    status: Optional[str] = None
    cancel_at: Optional[str] = None
    subscription_id: Optional[str] = None
    current_period_end: Optional[str] = None
    trial_end: Optional[str] = None
    is_test_mode: bool = False


@router.get("/billing", response_model=BillingResponse)
def billing(user: dict = Depends(current_user)):
    uid = user.get("sub")
    bs = get_billing_state(uid)
    plan = get_user_plan(uid)
    sub_id = bs.get("stripe_subscription_id")
    if sub_id and _billing.billing_configured():
        ps = _billing.poll_subscription_status(sub_id)
        if ps.get("ok"):
            grants = _billing.status_grants_access(ps.get("status"))
            set_billing_state(uid, billing_active=grants, stripe_status=ps.get("status"),
                              current_period_end=_iso_from_ts(ps.get("current_period_end")))
            new_plan = "pro" if grants else "free"
            if new_plan != plan:
                set_plan(uid, new_plan); plan = new_plan
            if ps.get("cancel_at_period_end"):
                schedule_cancellation(uid, _iso_from_ts(ps.get("current_period_end")) or "")
            else:
                undo_cancellation(uid)
            bs = get_billing_state(uid)
        elif ps.get("gone"):
            set_billing_state(uid, billing_active=False, stripe_status="canceled")
            if plan != "free":
                set_plan(uid, "free"); plan = "free"
            bs = get_billing_state(uid)
    return BillingResponse(
        configured=_billing.billing_configured(), plan=plan,
        billing_active=bool(bs.get("billing_active")), status=bs.get("stripe_status"),
        cancel_at=bs.get("cancel_at"), subscription_id=bs.get("stripe_subscription_id"),
        current_period_end=bs.get("current_period_end"), trial_end=bs.get("trial_end"),
        is_test_mode=_billing.is_test_mode(),
    )


@router.post("/checkout")
def checkout(user: dict = Depends(current_user)):
    uid = user.get("sub")
    if not _billing.billing_configured():
        raise HTTPException(status_code=400, detail="billing_not_configured")
    prof = authcore.get_profile(uid) or {}
    email = prof.get("email") or user.get("email") or ""
    # §17602: record affirmative consent BEFORE creating the transaction.
    _arl.log_consent(uid, plan="pro")
    existing = get_billing_state(uid).get("stripe_customer_id")
    url = _billing.create_checkout_url(
        uid, email, _WEB_URL, existing_customer_id=existing,
        success_url=f"{_WEB_URL}/account?checkout=success",
        cancel_url=f"{_WEB_URL}/account?checkout=cancel",
    )
    if not url:
        raise HTTPException(status_code=400, detail=_billing.last_error() or "checkout_failed")
    return {"ok": True, "url": url}


@router.post("/checkout/finalize")
def checkout_finalize(user: dict = Depends(current_user)):
    uid = user.get("sub")
    prof = authcore.get_profile(uid) or {}
    email = prof.get("email") or user.get("email") or ""
    res = _billing.finalize_checkout(uid, email)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "finalize_failed"))
    grants = _billing.status_grants_access(res.get("status"))
    set_billing_state(uid,
        stripe_customer_id=res.get("customer_id"),
        stripe_subscription_id=res.get("subscription_id"),
        billing_active=grants, stripe_status=res.get("status"),
        trial_end=_iso_from_ts(res.get("trial_end")),
        current_period_end=_iso_from_ts(res.get("current_period_end")))
    if grants:
        set_plan(uid, "pro")
        _arl.send_acknowledgment(uid, email)
    return {"ok": True, "plan": "pro" if grants else "free", "status": res.get("status")}


@router.post("/cancel")
def cancel(user: dict = Depends(current_user)):
    uid = user.get("sub")
    sub_id = get_billing_state(uid).get("stripe_subscription_id")
    if not sub_id:
        raise HTTPException(status_code=400, detail="no_subscription")
    res = _billing.cancel_subscription(sub_id)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "cancel_failed"))
    end_iso = _iso_from_ts(res.get("end_ts"))
    schedule_cancellation(uid, end_iso or "")
    prof = authcore.get_profile(uid) or {}
    _arl.send_cancellation_confirmation(uid, prof.get("email") or "", end_iso or "")
    return {"ok": True, "end_ts": end_iso, "was_trialing": res.get("was_trialing")}


@router.post("/undo-cancel")
def undo_cancel(user: dict = Depends(current_user)):
    uid = user.get("sub")
    sub_id = get_billing_state(uid).get("stripe_subscription_id")
    if not sub_id:
        raise HTTPException(status_code=400, detail="no_subscription")
    res = _billing.reactivate_subscription(sub_id)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "undo_failed"))
    undo_cancellation(uid)
    return {"ok": True}


@router.get("/arl-notice")
def arl_notice(user: dict = Depends(current_user)):
    # Single-sourced §17602 disclosure — the on-screen copy MUST equal what
    # log_consent() records in arl_consent_log, so it comes from arl.py.
    return {
        "html": _arl.initial_notice_html("/account"),
        "checkbox": _arl.CHECKBOX_TEXT,
        "terms_version": _arl.TERMS_VERSION,
    }
