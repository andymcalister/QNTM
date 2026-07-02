"""
QNTM API — alerts (Pro-gated).

GET    /api/alerts            notifications feed + unread count + user alerts
POST   /api/alerts            create a price/value/conviction/gem alert
DELETE /api/alerts/{id}       delete an alert (user-scoped)
PATCH  /api/alerts/{id}       pause/resume an alert (user-scoped)
POST   /api/alerts/read       mark notifications read (all, or a list of ids)

All auth-required. Entitlement mirrors PLAN_LIMITS["notifications"] — plan in
("pro","institutional"), read live so promotion unlocks immediately. Free plans
get locked:true with an empty feed.
"""

from fastapi import APIRouter, Depends, HTTPException

from ..schemas import (AlertsResponse, Notification, PriceAlert,
                       CreateAlertRequest, ToggleAlertRequest, MarkReadRequest)
from ..data import (load_alerts, create_alert, delete_alert, toggle_alert,
                    mark_alerts_read, get_user_plan)
from .auth import current_user

router = APIRouter(prefix="/api", tags=["alerts"])

_ALERTS_ENTITLED = {"pro", "institutional"}


def _require_pro(user: dict) -> str:
    uid = user.get("sub")
    if get_user_plan(uid) not in _ALERTS_ENTITLED:
        raise HTTPException(status_code=403, detail="pro_required")
    return uid


@router.get("/alerts", response_model=AlertsResponse)
def get_alerts(user: dict = Depends(current_user)):
    uid = user.get("sub")
    if get_user_plan(uid) not in _ALERTS_ENTITLED:
        return AlertsResponse(locked=True, unread=0, notifications=[], alerts=[])
    d = load_alerts(uid)
    return AlertsResponse(
        locked=False, unread=d["unread"],
        notifications=[Notification(**n) for n in d["notifications"]],
        alerts=[PriceAlert(**a) for a in d["alerts"]],
    )


@router.post("/alerts")
def post_alert(req: CreateAlertRequest, user: dict = Depends(current_user)):
    uid = _require_pro(user)
    ok, err = create_alert(uid, req.ticker, req.kind, req.threshold, req.scope)
    if not ok:
        raise HTTPException(status_code=400, detail=err or "could_not_create")
    return {"ok": True}


@router.delete("/alerts/{alert_id}")
def remove_alert(alert_id: str, user: dict = Depends(current_user)):
    if not delete_alert(user.get("sub"), alert_id):
        raise HTTPException(status_code=400, detail="could_not_delete")
    return {"ok": True}


@router.patch("/alerts/{alert_id}")
def patch_alert(alert_id: str, req: ToggleAlertRequest, user: dict = Depends(current_user)):
    if not toggle_alert(user.get("sub"), alert_id, req.active):
        raise HTTPException(status_code=400, detail="could_not_toggle")
    return {"ok": True}


@router.post("/alerts/read")
def read_alerts(req: MarkReadRequest, user: dict = Depends(current_user)):
    _require_pro(user)
    mark_alerts_read(user.get("sub"), req.ids or None)
    return {"ok": True}
