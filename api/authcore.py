"""Self-contained auth core for the API — mirrors db.py's crypto scheme EXACTLY
so tokens/hashes/secrets interoperate with the classic app, but without importing
db.py (which pulls in Streamlit). Scheme, verbatim from db.py:

  - email_hash : SHA-256 of the lowercased/stripped email (O(1) lookup)
  - password   : bcrypt (checkpw against the stored password_hash)
  - fields     : Fernet (ENCRYPTION_KEY), values prefixed "enc:"
  - TOTP       : pyotp, valid_window=1

Requires on the API service: bcrypt, pyotp, cryptography, and env ENCRYPTION_KEY
(same value as the classic app) + the Supabase service creds data.py already uses.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from .data import _get_supabase_admin  # service-role client (writes + full reads)


# ── crypto (identical to db.py) ───────────────────────────────────────────────
def _get_fernet():
    try:
        from cryptography.fernet import Fernet
        import base64
        key = os.getenv("ENCRYPTION_KEY", "")
        if not key:
            return None
        if isinstance(key, str):
            key = key.encode()
        if len(key) == 32:  # accept a raw 32-byte key
            key = base64.urlsafe_b64encode(key)
        return Fernet(key)
    except Exception:
        return None


def decrypt_field(value: str) -> str:
    if not value or not str(value).startswith("enc:"):
        return value or ""
    f = _get_fernet()
    if not f:
        return value
    try:
        return f.decrypt(value[4:].encode()).decode()
    except Exception:
        return value


def encrypt_field(value: str) -> str:
    if not value:
        return value
    f = _get_fernet()
    if not f:
        return value
    try:
        return "enc:" + f.encrypt(value.encode()).decode()
    except Exception:
        return value


def email_hash(email: str) -> str:
    return hashlib.sha256(email.lower().strip().encode()).hexdigest()


def hash_password(password: str) -> str:
    import bcrypt
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        import bcrypt
        return bcrypt.checkpw(password.encode(), (hashed or "").encode())
    except Exception:
        return False


def verify_totp(secret: str, code: str) -> bool:
    try:
        import pyotp
        return bool(secret) and pyotp.TOTP(secret).verify((code or "").strip(), valid_window=1)
    except Exception:
        return False


# ── data access (service-role) ────────────────────────────────────────────────
def login(email: str, password: str) -> dict:
    """Mirror db.login_user: {success, user{...}} | {success:False, error}."""
    sb = _get_supabase_admin()
    if not sb:
        return {"success": False, "error": "Auth unavailable"}
    try:
        res = sb.table("users").select("*").eq("email_hash", email_hash(email)).execute()
        if not res.data:
            return {"success": False, "error": "Invalid email or password"}
        row = res.data[0]
        if not verify_password(password, row.get("password_hash", "")):
            return {"success": False, "error": "Invalid email or password"}
        try:
            sb.table("users").update({"last_login": datetime.now(timezone.utc).isoformat()}).eq("id", row["id"]).execute()
        except Exception:
            pass
        notif_raw = row.get("notifications") or "{}"
        user = {
            "id": row["id"],
            "email": decrypt_field(row.get("email_encrypted", "")),
            "full_name": decrypt_field(row.get("full_name_encrypted", "")),
            "plan": row.get("plan", "free"),
            "mfa_enabled": bool(row.get("mfa_enabled", False)),
            "totp_secret": decrypt_field(row.get("totp_secret_encrypted") or "") or None,
            "email_verified": bool(row.get("email_verified", True)),
            "notifications": json.loads(notif_raw) if isinstance(notif_raw, str) else notif_raw,
        }
        return {"success": True, "user": user}
    except Exception:
        return {"success": False, "error": "Login failed. Please try again."}


def get_user_mfa(user_id: str) -> dict:
    sb = _get_supabase_admin()
    if not sb:
        return {"mfa_enabled": False, "totp_secret": None}
    try:
        res = sb.table("users").select("mfa_enabled,totp_secret_encrypted").eq("id", user_id).execute()
        if res.data:
            r = res.data[0]
            return {"mfa_enabled": bool(r.get("mfa_enabled", False)),
                    "totp_secret": decrypt_field(r.get("totp_secret_encrypted") or "") or None}
    except Exception:
        pass
    return {"mfa_enabled": False, "totp_secret": None}


import re as _re
import unicodedata as _ud

def _is_latin(c: str) -> bool:
    if not c.isalpha():
        return False
    try:
        return "LATIN" in _ud.name(c)
    except ValueError:
        return False

def _word_is_gibberish(w: str) -> bool:
    """True if a single token looks like a random-character blob (Latin only)."""
    if len(w) < 3:
        return False
    letters = [c for c in w if c.isalpha()]
    if not letters:
        return True
    if not all(_is_latin(c) for c in letters):
        return False  # non-Latin script: Latin heuristics don't apply, accept
    low = w.lower()
    vowels = sum(1 for c in low if c in "aeiouy")
    if len(letters) >= 6 and vowels == 0:
        return True
    if len(letters) >= 10 and vowels / len(letters) < 0.12:
        return True
    core = "".join(c for c in w if c.isalpha())
    trans = sum(1 for i in range(1, len(core)) if core[i].isupper() != core[i-1].isupper())
    if len(core) >= 7 and trans >= 4:
        return True
    run = 0
    for c in low:
        if c.isalpha() and c not in "aeiouy":
            run += 1
            if run >= 7:
                return True
        else:
            run = 0
    return False

def looks_like_real_name(name: str) -> bool:
    """Accept plausibly-real names of any script/shape; reject gibberish blobs."""
    n = (name or "").strip()
    if len(n) < 2 or len(n) > 60:
        return False
    if not any(c.isalpha() for c in n):
        return False
    if any(c.isdigit() for c in n):
        return False
    if _re.search(r"[^\w\s\.\-'\u2019,]", n, _re.UNICODE):
        return False
    letters = [c.lower() for c in n if c.isalpha()]
    if len(letters) >= 4 and max(letters.count(c) for c in set(letters)) / len(letters) > 0.6:
        return False
    tokens = [t for t in _re.split(r"[\s\-'\u2019]+", n) if t]
    return not any(_word_is_gibberish(t) for t in tokens)

def canonical_email(email: str) -> str:
    """Normalize an email for duplicate detection (login still uses exact hash)."""
    e = (email or "").lower().strip()
    if "@" not in e:
        return e
    local, _, domain = e.partition("@")
    local = local.split("+", 1)[0]
    if domain in ("gmail.com", "googlemail.com"):
        local = local.replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"

def canonical_email_hash(email: str) -> str:
    return hashlib.sha256(canonical_email(email).encode()).hexdigest()


def register(email: str, password: str, full_name: str) -> dict:
    """Mirror db.register_user: {success, user_id} | {success:False, error}."""
    import secrets as _secrets
    sb = _get_supabase_admin()
    if not sb:
        return {"success": False, "error": "Registration unavailable"}
    if not looks_like_real_name(full_name):
        return {"success": False, "error": "Please enter your real name."}
    eh = email_hash(email)
    ceh = canonical_email_hash(email)
    try:
        existing = sb.table("users").select("id").eq("email_hash", eh).execute()
        if existing.data:
            return {"success": False, "error": "An account with this email already exists"}
        try:
            dup = sb.table("users").select("id").eq("email_canonical_hash", ceh).execute()
            if dup.data:
                return {"success": False, "error": "An account with this email already exists"}
        except Exception:
            pass
        uid = _secrets.token_hex(16)
        sb.table("users").insert({
            "id": uid,
            "email_hash": eh,
            "email_canonical_hash": ceh,
            "email_encrypted": encrypt_field(email.lower().strip()),
            "full_name_encrypted": encrypt_field(full_name.strip()),
            "password_hash": hash_password(password),
            "plan": "free",
            "mfa_enabled": False,
            "totp_secret_encrypted": None,
            "email_verified": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return {"success": True, "user_id": uid}
    except Exception as e:
        err = str(e).lower()
        if "duplicate" in err or "unique" in err:
            return {"success": False, "error": "An account with this email already exists"}
        return {"success": False, "error": "Registration failed. Please try again."}

# ══════════════════════════════════════════════════════════════════════════════
# PASSWORD RESET + EMAIL-VERIFY TOKEN INFRA — mirrors db.py's auth_tokens scheme
# EXACTLY ({token, user_id, kind, expires_at, used}) but service-role only (the
# API has no Supabase auth.uid(), so RLS would block anon writes). Native reset
# links point at the Next app, not classic.
# ══════════════════════════════════════════════════════════════════════════════
import logging as _logging
import secrets as _secrets
from datetime import timedelta as _timedelta

_log = _logging.getLogger("qntm.api.authcore")
_PUBLIC_WEB_URL = os.getenv("PUBLIC_WEB_URL", "https://qntm.live").rstrip("/")


def _user_id_by_email(email: str):
    email = (email or "").lower().strip()
    if not email:
        return None
    sb = _get_supabase_admin()
    if not sb:
        return None
    try:
        r = sb.table("users").select("id").eq("email_hash", email_hash(email)).execute()
        return r.data[0]["id"] if r.data else None
    except Exception:
        return None


def create_auth_token(user_id: str, kind: str = "reset", ttl_minutes: int = 30) -> str:
    sb = _get_supabase_admin()
    if not sb:
        return ""
    token = _secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + _timedelta(minutes=ttl_minutes)).isoformat()
    try:
        sb.table("auth_tokens").insert({
            "token": token, "user_id": user_id, "kind": kind,
            "expires_at": expires, "used": False,
        }).execute()
    except Exception:
        return ""
    return token


def _token_row(token: str):
    sb = _get_supabase_admin()
    if not sb:
        return None
    try:
        r = sb.table("auth_tokens").select("*").eq("token", token).execute()
        return r.data[0] if r.data else None
    except Exception:
        return None


def _token_valid(row, kind) -> bool:
    if not row or row.get("used") or row.get("kind") != kind:
        return False
    try:
        exp = datetime.fromisoformat(str(row.get("expires_at")).replace("Z", "+00:00"))
    except Exception:
        return False
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp >= datetime.now(timezone.utc)


def peek_auth_token(token: str, kind: str = "reset") -> bool:
    """Validate a token WITHOUT consuming it (used to render the reset form)."""
    if not token:
        return False
    return _token_valid(_token_row(token), kind)


def consume_auth_token(token: str, kind: str = "reset"):
    """Validate and mark used (one-time). Returns user_id, or None if invalid."""
    if not token:
        return None
    row = _token_row(token)
    if not _token_valid(row, kind):
        return None
    sb = _get_supabase_admin()
    try:
        sb.table("auth_tokens").update({"used": True}).eq("token", token).execute()
    except Exception:
        return None
    return row["user_id"]


def set_password(user_id: str, new_password: str) -> dict:
    if not new_password or len(new_password) < 8:
        return {"success": False, "error": "Password must be at least 8 characters"}
    sb = _get_supabase_admin()
    if not sb:
        return {"success": False, "error": "Unavailable"}
    try:
        sb.table("users").update({"password_hash": hash_password(new_password)}).eq("id", user_id).execute()
        return {"success": True}
    except Exception:
        return {"success": False, "error": "Couldn't update password"}


def _send_email(to_email: str, subject: str, html: str, text: str = None) -> dict:
    """Minimal SendGrid send (os.getenv only — no Streamlit). Fails soft."""
    api_key = os.getenv("SENDGRID_API_KEY")
    from_email = os.getenv("SENDGRID_FROM")
    if not api_key or not from_email:
        _log.warning("send_email: SendGrid not configured — %r not sent", subject)
        return {"success": False, "error": "Email not configured"}
    if not to_email:
        return {"success": False, "error": "No recipient"}
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
        kwargs = dict(from_email=from_email, to_emails=to_email, subject=subject, html_content=html)
        if text:
            kwargs["plain_text_content"] = text
        resp = SendGridAPIClient(api_key).send(Mail(**kwargs))
        return {"success": 200 <= resp.status_code < 300, "status": resp.status_code}
    except ImportError:
        return {"success": False, "error": "sendgrid package not installed"}
    except Exception as e:
        return {"success": False, "error": f"Send failed: {str(e)[:120]}"}


def _reset_email_html(link: str) -> str:
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:0 auto;padding:24px;">'
        '<div style="font-size:22px;font-weight:800;letter-spacing:.04em;color:#0a0b14;">'
        'Q<span style="color:#15a97a;">NTM</span></div>'
        '<p style="font-size:15px;color:#333;line-height:1.5;">We received a request to reset your '
        'QNTM password. Click the button below to choose a new one:</p>'
        f'<p style="margin:22px 0;"><a href="{link}" style="display:inline-block;background:#15a97a;'
        'color:#ffffff;text-decoration:none;padding:12px 26px;border-radius:8px;font-weight:700;'
        'font-size:15px;">Reset password</a></p>'
        '<p style="font-size:13px;color:#777;line-height:1.5;">This link expires in 30 minutes. '
        "If you didn't request this, you can safely ignore this email — your password won't change.</p>"
        '<p style="font-size:12px;color:#aaa;margin-top:24px;">QNTM · Quantitative stock conviction</p>'
        '</div>'
    )


def request_password_reset(email: str) -> dict:
    """Mint a reset token and email a native (qntm.live) reset link. ALWAYS
    returns success — never reveals whether an account exists."""
    uid_ = _user_id_by_email(email)
    if uid_:
        token = create_auth_token(uid_, kind="reset", ttl_minutes=30)
        if token:
            link = f"{_PUBLIC_WEB_URL}/reset-password?token={token}"
            _send_email(
                (email or "").lower().strip(),
                "Reset your QNTM password",
                _reset_email_html(link),
                text=f"Reset your QNTM password: {link}\n\n"
                     "This link expires in 30 minutes. If you didn't request this, ignore this email.",
            )
    return {"success": True}


def reset_password(token: str, new_password: str) -> dict:
    """Consume a reset token (one-time) and set the new password."""
    if not new_password or len(new_password) < 8:
        return {"success": False, "error": "Password must be at least 8 characters"}
    uid = consume_auth_token(token, kind="reset")
    if not uid:
        return {"success": False, "error": "This link is invalid or has expired"}
    return set_password(uid, new_password)

# ══════════════════════════════════════════════════════════════════════════════
# EMAIL VERIFICATION — same auth_tokens infra, kind="verify" (24h). Native links
# point at qntm.live/verify-email. Soft gate: users can use the app; this just
# flips users.email_verified so the alert-email path will send to them.
# ══════════════════════════════════════════════════════════════════════════════
def is_email_verified(user_id: str) -> bool:
    """Fails CLOSED (False) on a read error so alert-email never goes to an
    unconfirmed address."""
    if not user_id:
        return False
    sb = _get_supabase_admin()
    if not sb:
        return False
    try:
        r = sb.table("users").select("email_verified").eq("id", user_id).execute()
        return bool(r.data[0].get("email_verified")) if r.data else False
    except Exception:
        return False


def _verify_email_html(link: str) -> str:
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:0 auto;padding:24px;">'
        '<div style="font-size:22px;font-weight:800;letter-spacing:.04em;color:#0a0b14;">'
        'Q<span style="color:#15a97a;">NTM</span></div>'
        '<p style="font-size:15px;color:#333;line-height:1.5;">Welcome to QNTM. Please confirm your '
        'email address so we can keep your account secure and deliver your alerts:</p>'
        f'<p style="margin:22px 0;"><a href="{link}" style="display:inline-block;background:#15a97a;'
        'color:#ffffff;text-decoration:none;padding:12px 26px;border-radius:8px;font-weight:700;'
        'font-size:15px;">Confirm my email</a></p>'
        '<p style="font-size:13px;color:#777;line-height:1.5;">This link expires in 24 hours. '
        "If you didn't create a QNTM account, you can safely ignore this email.</p>"
        '<p style="font-size:12px;color:#aaa;margin-top:24px;">QNTM · Quantitative stock conviction</p>'
        '</div>'
    )


def request_email_verification(email: str) -> dict:
    """Mint a verify token and email a native confirmation link. Always returns
    success (no enumeration); `delivered` carries the real SendGrid result for
    authenticated callers (the in-app resend button) to surface honestly."""
    uid_ = _user_id_by_email(email)
    delivered, err = False, None
    if uid_:
        token = create_auth_token(uid_, kind="verify", ttl_minutes=60 * 24)  # 24h
        if token:
            link = f"{_PUBLIC_WEB_URL}/verify-email?token={token}"
            _send = _send_email(
                (email or "").lower().strip(),
                "Confirm your QNTM email",
                _verify_email_html(link),
                text=f"Welcome to QNTM. Confirm your email: {link}\n\n"
                     "This link expires in 24 hours. If you didn't create an account, ignore this email.",
            )
            delivered = bool(_send.get("success"))
            err = _send.get("error")
    return {"success": True, "delivered": delivered, "error": err}


def consume_verify_token(token: str) -> dict:
    """Validate a verify token (one-time), mark the user's email confirmed."""
    if not token:
        return {"success": False, "error": "Missing verification token"}
    uid_ = consume_auth_token(token, kind="verify")
    if not uid_:
        return {"success": False, "error": "This link is invalid or has expired"}
    sb = _get_supabase_admin()
    if not sb:
        return {"success": False, "error": "Couldn't confirm your email — please try again"}
    try:
        sb.table("users").update({"email_verified": True}).eq("id", uid_).execute()
        return {"success": True, "user_id": uid_}
    except Exception:
        return {"success": False, "error": "Couldn't confirm your email — please try again"}

# ══════════════════════════════════════════════════════════════════════════════
# ACCOUNT PROFILE + SECURITY — authenticated self-service. Name/email edits and
# password change against the users table. Email change re-hashes + re-encrypts,
# enforces uniqueness, and resets email_verified (caller re-fires verification).
# ══════════════════════════════════════════════════════════════════════════════
def get_profile(user_id: str) -> dict:
    sb = _get_supabase_admin()
    if not sb:
        return {}
    try:
        r = sb.table("users").select(
            "full_name_encrypted,email_encrypted,email_verified").eq("id", user_id).execute()
        if not r.data:
            return {}
        row = r.data[0]
        return {
            "full_name": decrypt_field(row.get("full_name_encrypted") or ""),
            "email": decrypt_field(row.get("email_encrypted") or ""),
            "email_verified": bool(row.get("email_verified", False)),
        }
    except Exception:
        return {}


def update_full_name(user_id: str, full_name: str) -> dict:
    sb = _get_supabase_admin()
    if not sb:
        return {"success": False, "error": "Unavailable"}
    try:
        sb.table("users").update(
            {"full_name_encrypted": encrypt_field((full_name or "").strip())}
        ).eq("id", user_id).execute()
        return {"success": True}
    except Exception:
        return {"success": False, "error": "Couldn't update name"}


def update_email(user_id: str, new_email: str) -> dict:
    """Re-hash + re-encrypt, enforce uniqueness, reset email_verified so the new
    address must be confirmed. Caller fires request_email_verification."""
    new_email = (new_email or "").lower().strip()
    if not new_email or "@" not in new_email or "." not in new_email.split("@")[-1]:
        return {"success": False, "error": "Invalid email address"}
    sb = _get_supabase_admin()
    if not sb:
        return {"success": False, "error": "Unavailable"}
    new_hash = email_hash(new_email)
    try:
        existing = sb.table("users").select("id").eq("email_hash", new_hash).execute()
        if existing.data and existing.data[0]["id"] != user_id:
            return {"success": False, "error": "That email is already in use"}
        sb.table("users").update({
            "email_hash": new_hash,
            "email_encrypted": encrypt_field(new_email),
            "email_verified": False,
        }).eq("id", user_id).execute()
        return {"success": True, "email": new_email}
    except Exception as e:
        err = str(e).lower()
        if "duplicate" in err or "unique" in err:
            return {"success": False, "error": "That email is already in use"}
        return {"success": False, "error": "Update failed. Please try again."}


def change_password(user_id: str, current_password: str, new_password: str) -> dict:
    """Verify the current password before setting the new one."""
    if not new_password or len(new_password) < 8:
        return {"success": False, "error": "New password must be at least 8 characters"}
    sb = _get_supabase_admin()
    if not sb:
        return {"success": False, "error": "Unavailable"}
    try:
        r = sb.table("users").select("password_hash").eq("id", user_id).execute()
        if not r.data:
            return {"success": False, "error": "User not found"}
        current_hash = r.data[0].get("password_hash")
    except Exception:
        return {"success": False, "error": "Couldn't verify current password"}
    if not verify_password(current_password or "", current_hash or ""):
        return {"success": False, "error": "Current password is incorrect"}
    return set_password(user_id, new_password)
