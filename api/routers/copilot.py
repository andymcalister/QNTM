"""FastAPI router for the comment copilot — admin-session gated.

Reply posting happens MANUALLY via an X web-intent link on the client (X's API
blocks programmatic replies). /approve likes the post server-side, then records
the choice so the item clears the queue. No daily cap.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import current_user
from .admin import _is_admin
from ..copilot import store, xclient
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
        "posted_today": store.posted_today_count(),
        "items": store.list_pending(),
    }


@router.post("/harvest")
def run_harvest(user: dict = Depends(current_user)):
    _guard(user)
    return harvest_mod.harvest()


@router.post("/{cid}/approve")
def approve(cid: str, body: Approve, user: dict = Depends(current_user)):
    """Like the post, then record the reply (posting happens on X via intent link)."""
    _guard(user)
    item = store.get(cid)
    if not item or item.get("status") != "pending":
        raise HTTPException(status_code=404, detail="Not found or already handled.")
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty reply.")
    if len(text) > 280:
        raise HTTPException(status_code=400, detail="Reply exceeds 280 chars.")

    liked = False
    try:
        xclient.like(item["tweet_id"])
        liked = True
    except Exception as e:
        print(f"[warn] like {item['tweet_id']}: {e}")

    store.update(cid, {"status": "posted", "final_text": text,
                       "posted_at": store.now_iso()})
    return {"ok": True, "liked": liked}


@router.post("/{cid}/skip")
def skip(cid: str, user: dict = Depends(current_user)):
    _guard(user)
    store.update(cid, {"status": "skipped"})
    return {"ok": True}
