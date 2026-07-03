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


def register(email: str, password: str, full_name: str) -> dict:
    """Mirror db.register_user: {success, user_id} | {success:False, error}."""
    import secrets as _secrets
    sb = _get_supabase_admin()
    if not sb:
        return {"success": False, "error": "Registration unavailable"}
    eh = email_hash(email)
    try:
        existing = sb.table("users").select("id").eq("email_hash", eh).execute()
        if existing.data:
            return {"success": False, "error": "An account with this email already exists"}
        uid = _secrets.token_hex(16)
        sb.table("users").insert({
            "id": uid,
            "email_hash": eh,
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
