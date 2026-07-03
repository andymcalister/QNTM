"""Public: Market Outlook / Day Wrap / Week Wrap — read the ledger + manage email
subscriptions (double opt-in, one-click unsubscribe). No auth."""
import logging
import os
import secrets

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/api/outlook", tags=["outlook"])

WEB = os.getenv("PUBLIC_WEB_URL", "https://qntm.live")
API = os.getenv("PUBLIC_API_URL", "https://qntm-api.onrender.com")
VALID_KINDS = ("outlook", "wrap", "week")
ADDR = "QNTM LLC · 35 Laguna Woods Drive, Laguna Niguel, CA 92677"


def _sb():
    from ..data import _get_supabase_admin
    return _get_supabase_admin()


# ── Read ──────────────────────────────────────────────────────────────────────
@router.get("")
def outlook(kind: str = Query(None), limit: int = Query(20, le=90)):
    sb = _sb()
    if not sb:
        return {"items": []}
    try:
        q = (sb.table("daily_outlook")
             .select("outlook_date,kind,regime,conviction,model_return,spy_return,narrative,created_at")
             .order("outlook_date", desc=True).order("created_at", desc=True).limit(limit))
        if kind:
            q = q.eq("kind", kind)
        return {"items": q.execute().data or []}
    except Exception as e:
        logging.warning("outlook read failed: %s", e)
        return {"items": []}


# ── Subscribe (double opt-in) ─────────────────────────────────────────────────
@router.post("/subscribe")
def subscribe(payload: dict = Body(...)):
    email = (payload.get("email") or "").strip().lower()
    kinds = [k for k in (payload.get("kinds") or ["wrap"]) if k in VALID_KINDS] or ["wrap"]
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Please enter a valid email.")
    sb = _sb()
    if not sb:
        raise HTTPException(status_code=503, detail="Temporarily unavailable.")
    vtoken = secrets.token_urlsafe(24)
    try:
        existing = (sb.table("outlook_subscribers").select("id,verified")
                    .eq("email", email).limit(1).execute().data or [])
        if existing:
            sb.table("outlook_subscribers").update({"kinds": kinds, "verify_token": vtoken}).eq("email", email).execute()
            if existing[0].get("verified"):
                # already confirmed — just updated their prefs, no re-confirm needed
                return {"ok": True, "status": "updated"}
        else:
            sb.table("outlook_subscribers").insert(
                {"email": email, "kinds": kinds, "verify_token": vtoken, "verified": False}).execute()
    except Exception as e:
        logging.warning("subscribe write failed: %s", e)
        raise HTTPException(status_code=500, detail="Could not subscribe. Try again.")
    _send_confirm(email, vtoken)
    return {"ok": True, "status": "pending"}


def _send_confirm(email, vtoken):
    try:
        from db import send_email
    except Exception:
        return
    link = f"{API}/api/outlook/confirm?token={vtoken}"
    html = (
        '<div style="font-family:sans-serif;max-width:520px;margin:0 auto;color:#111;">'
        '<h2>Confirm your QNTM briefs</h2>'
        '<p>Tap below to start receiving the QNTM Market Outlook / Day Wrap / Week Wrap by email. '
        'If you didn\u2019t request this, ignore this message and you won\u2019t be subscribed.</p>'
        f'<p><a href="{link}" style="display:inline-block;background:#0a7;color:#fff;padding:11px 20px;'
        'border-radius:8px;text-decoration:none;font-weight:700;">Confirm subscription</a></p>'
        f'<p style="font-size:12px;color:#888;">{ADDR}</p></div>'
    )
    try:
        send_email(email, "Confirm your QNTM Market Outlook subscription", html, text=f"Confirm your subscription: {link}")
    except Exception as e:
        logging.warning("confirm email failed: %s", e)


def _page(title, body):
    return HTMLResponse(
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{title} — QNTM</title></head>'
        '<body style="font-family:sans-serif;background:#08090c;color:#e2e8f0;'
        'display:flex;min-height:100vh;align-items:center;justify-content:center;text-align:center;margin:0;">'
        f'<div style="max-width:440px;padding:24px;"><h1 style="color:#fff;">{title}</h1>'
        f'<p style="color:#9fabc0;line-height:1.6;">{body}</p>'
        f'<p style="margin-top:24px;"><a href="{WEB}/market-outlook" style="color:#34d399;">Back to QNTM</a></p></div>'
        '</body></html>'
    )


@router.get("/confirm", response_class=HTMLResponse)
def confirm(token: str = Query(...)):
    sb = _sb()
    if not sb:
        return _page("Something went wrong", "Please try again in a moment.")
    try:
        row = (sb.table("outlook_subscribers").select("id").eq("verify_token", token).limit(1).execute().data or [])
        if not row:
            return _page("Link expired", "That confirmation link is invalid or already used.")
        from datetime import datetime, timezone
        sb.table("outlook_subscribers").update(
            {"verified": True, "verify_token": None, "verified_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", row[0]["id"]).execute()
    except Exception as e:
        logging.warning("confirm failed: %s", e)
        return _page("Something went wrong", "Please try again in a moment.")
    return _page("You\u2019re subscribed", "You\u2019ll get QNTM briefs by email. You can unsubscribe from any message.")


@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(token: str = Query(...)):
    sb = _sb()
    if not sb:
        return _page("Something went wrong", "Please try again in a moment.")
    try:
        sb.table("outlook_subscribers").delete().eq("unsub_token", token).execute()
    except Exception as e:
        logging.warning("unsubscribe failed: %s", e)
    return _page("Unsubscribed", "You won\u2019t receive any more QNTM briefs. You can resubscribe anytime.")
