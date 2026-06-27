"""
QNTM SMS sender (Twilio)
========================
Shared by alerts_engine.py (cron fan-out) and app.py (phone verification).

Fails soft: returns {"success": False, ...} and never raises when Twilio
isn't configured or the package isn't installed, so callers degrade
gracefully — exactly like db.send_email.

Configure in secrets.toml / env:
    TWILIO_ACCOUNT_SID
    TWILIO_AUTH_TOKEN
    TWILIO_FROM                    (an SMS-capable Twilio number, E.164)
  OR
    TWILIO_MESSAGING_SERVICE_SID   (preferred for A2P 10DLC; use instead of FROM)

Requires the `twilio` package (add to requirements.txt).
"""
import os
import logging

log = logging.getLogger("qntm.sms")


def _cfg(key: str):
    """Read a setting from Streamlit secrets first, then env. Never raises."""
    try:
        import streamlit as st
        return st.secrets.get(key) or os.getenv(key)
    except Exception:
        return os.getenv(key)


def sms_configured() -> bool:
    sid = _cfg("TWILIO_ACCOUNT_SID")
    tok = _cfg("TWILIO_AUTH_TOKEN")
    src = _cfg("TWILIO_MESSAGING_SERVICE_SID") or _cfg("TWILIO_FROM")
    return bool(sid and tok and src)


def send_sms(to_phone: str, body: str) -> dict:
    """Send an SMS. Returns {"success": bool, ...}. Never raises."""
    if not to_phone:
        return {"success": False, "error": "No recipient"}
    sid = _cfg("TWILIO_ACCOUNT_SID")
    tok = _cfg("TWILIO_AUTH_TOKEN")
    frm = _cfg("TWILIO_FROM")
    msvc = _cfg("TWILIO_MESSAGING_SERVICE_SID")
    _masked = (to_phone[:-4].replace(to_phone[:-4], "***") + to_phone[-4:]) if len(to_phone) >= 4 else "***"
    if not sid or not tok or not (frm or msvc):
        log.warning("send_sms: Twilio not configured (SID/TOKEN/FROM or MESSAGING_SERVICE_SID missing) — not sent")
        return {"success": False, "error": "SMS not configured"}
    try:
        from twilio.rest import Client
        client = Client(sid, tok)
        kwargs = dict(to=to_phone, body=body[:1500])
        if msvc:
            kwargs["messaging_service_sid"] = msvc
        else:
            kwargs["from_"] = frm
        msg = client.messages.create(**kwargs)
        log.info("send_sms: sent to %s sid=%s", _masked, getattr(msg, "sid", "?"))
        return {"success": True, "sid": getattr(msg, "sid", None)}
    except Exception as e:
        log.warning("send_sms: failed for %s — %s", _masked, e)
        return {"success": False, "error": str(e)}
