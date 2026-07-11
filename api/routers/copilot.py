"""FastAPI router for the comment copilot — admin-session gated.

    from api.routers import copilot as copilot_router
    app.include_router(copilot_router.router)

Auth reuses the same session dependency + admin allowlist as the admin router:
any signed-in admin (email in ADMIN_EMAILS) is authorized. No separate secret.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import current_user
from .admin import _is_admin
from ..copilot import config, store, xclient
from ..copilot import harvest as harvest_mod

router = APIRouter(prefix="/api/copilot", tags=["copilot"])


def _guard(user: dict):
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Not authorized")


class Approve(BaseModel):
    text: str


@router.get("/queue")
def queue(user: dict = Depends(current_user)):
    _guard(user)
    return {
        "cap": config.DAILY_POST_CAP,
        "posted_today": store.posted_today_count(),
        "items": store.list_pending(),
    }


@router.post("/harvest")
def run_harvest(user: dict = Depends(current_user)):
    _guard(user)
    return harvest_mod.harvest()


@router.post("/{cid}/approve")
def approve(cid: str, body: Approve, user: dict = Depends(current_user)):
    _guard(user)
    if store.posted_today_count() >= config.DAILY_POST_CAP:
        raise HTTPException(status_code=429, detail="daily cap reached")
    item = store.get(cid)
    if not item or item.get("status") != "pending":
        raise HTTPException(status_code=404, detail="not found or already handled")
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty reply")
    if len(text) > 280:
        raise HTTPException(status_code=400, detail="reply exceeds 280 chars")
    try:
        xclient.like(item["tweet_id"])
    except Exception as e:
        print(f"[warn] like {item['tweet_id']}: {e}")
    resp = xclient.reply(item["tweet_id"], text)
    reply_id = None
    try:
        reply_id = str(resp.data["id"])
    except Exception:
        pass
    store.update(cid, {"status": "posted", "final_text": text,
                       "reply_id": reply_id, "posted_at": store.now_iso()})
    return {"ok": True, "reply_id": reply_id}


@router.post("/{cid}/skip")
def skip(cid: str, user: dict = Depends(current_user)):
    _guard(user)
    store.update(cid, {"status": "skipped"})
    return {"ok": True}
