"""FastAPI router for the comment copilot. Mount in your main app.

    from api.routers import copilot as copilot_router
    app.include_router(copilot_router.router)

All JSON endpoints require:  Authorization: Bearer <COPILOT_SECRET>
The review page itself (GET /api/copilot/review) is an unauthenticated shell;
it asks for the secret in-browser and uses it for the data calls.
"""
import os
import pathlib
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..copilot import config, store, xclient
from ..copilot import harvest as harvest_mod

router = APIRouter(prefix="/api/copilot", tags=["copilot"])
_SECRET = os.environ.get("COPILOT_SECRET")
_HTML = pathlib.Path(__file__).resolve().parent.parent / "copilot" / "review.html"


def _auth(authorization):
    if not _SECRET or authorization != f"Bearer {_SECRET}":
        raise HTTPException(status_code=401, detail="unauthorized")


class Approve(BaseModel):
    text: str


@router.get("/review", response_class=HTMLResponse)
def review_page():
    return _HTML.read_text()


@router.get("/queue")
def queue(authorization: str = Header(None)):
    _auth(authorization)
    return {
        "cap": config.DAILY_POST_CAP,
        "posted_today": store.posted_today_count(),
        "items": store.list_pending(),
    }


@router.post("/harvest")
def run_harvest(authorization: str = Header(None)):
    _auth(authorization)
    return harvest_mod.harvest()


@router.post("/{cid}/approve")
def approve(cid: str, body: Approve, authorization: str = Header(None)):
    _auth(authorization)
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
        xclient.like(item["tweet_id"])          # like failure must not block reply
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
def skip(cid: str, authorization: str = Header(None)):
    _auth(authorization)
    store.update(cid, {"status": "skipped"})
    return {"ok": True}
