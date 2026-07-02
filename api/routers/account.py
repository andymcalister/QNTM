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

from fastapi import APIRouter, Depends, HTTPException

from ..schemas import (NotificationPrefsResponse, NotificationPrefs,
                       SavePrefsRequest, PhoneSendRequest, PhoneVerifyRequest, SimpleOk)
from ..data import (get_notification_prefs, save_notification_prefs,
                    send_phone_verify_code, verify_phone_code, get_user_plan)
from .auth import current_user

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
