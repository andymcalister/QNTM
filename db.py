"""
QNTM — Database & Auth Layer
=============================
Security model:
  - Passwords: bcrypt cost=12 — never stored plain text
  - Sensitive fields (email, name, TOTP secret): AES-256-GCM via Fernet
    Key stored in st.secrets / env — NOT in the database
  - email_hash (SHA-256) stored for O(1) lookup without decryption
  - Row Level Security on all Supabase tables
  - Demo mode: in-memory only, bcrypt still enforced, nothing persisted to disk

Plans:
  free          10 holdings, no notifications, no hidden gems
  pro           unlimited holdings, hidden gems, signal alerts, email notifications
  institutional everything in pro + API access
"""

import os, json, secrets, hashlib
from datetime import datetime, date
from typing import Optional
import streamlit as st
import bcrypt
import pyotp
import qrcode
from io import BytesIO

# ─────────────────────────────────────────────────────────────────────────────
# ENCRYPTION  (AES-256 via Fernet)
# ─────────────────────────────────────────────────────────────────────────────

def _get_fernet():
    try:
        from cryptography.fernet import Fernet
        import base64
        key = (st.secrets.get("ENCRYPTION_KEY") or os.getenv("ENCRYPTION_KEY", ""))
        if not key:
            return None
        if isinstance(key, str):
            key = key.encode()
        # Accept raw 32-byte keys by converting to Fernet format
        if len(key) == 32:
            import base64 as b64
            key = b64.urlsafe_b64encode(key)
        return Fernet(key)
    except Exception:
        return None


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


# ─────────────────────────────────────────────────────────────────────────────
# PASSWORD HASHING
# ─────────────────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# SUPABASE
# ─────────────────────────────────────────────────────────────────────────────

def get_supabase():
    try:
        from supabase import create_client
        url = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL", "")
        key = st.secrets.get("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_ANON_KEY", "")
        if url and key and url.startswith("https://") and "supabase" in url:
            return create_client(url, key)
    except Exception:
        pass
    return None


def _is_demo():
    return get_supabase() is None


# ─────────────────────────────────────────────────────────────────────────────
# DEMO IN-MEMORY STORES
# ─────────────────────────────────────────────────────────────────────────────

def _demo_users() -> dict:
    if "qntm_demo_users" not in st.session_state:
        st.session_state.qntm_demo_users = {}
    return st.session_state.qntm_demo_users


def _demo_holdings() -> dict:
    if "qntm_demo_holdings" not in st.session_state:
        st.session_state.qntm_demo_holdings = {}
    return st.session_state.qntm_demo_holdings


def _demo_notifs() -> dict:
    if "qntm_demo_notifs" not in st.session_state:
        st.session_state.qntm_demo_notifs = {}
    return st.session_state.qntm_demo_notifs


def _demo_find_user(user_id: str) -> Optional[dict]:
    for u in _demo_users().values():
        if u["id"] == user_id:
            return u
    return None


# ─────────────────────────────────────────────────────────────────────────────
# PLAN CONFIG
# ─────────────────────────────────────────────────────────────────────────────

PLAN_LIMITS = {
    "free":          {"max_holdings": 10,  "gems": False, "notifications": False, "alerts": False},
    "pro":           {"max_holdings": 9999,"gems": True,  "notifications": True,  "alerts": True},
    "institutional": {"max_holdings": 9999,"gems": True,  "notifications": True,  "alerts": True},
}


def plan_limit(plan: str, feature: str):
    return PLAN_LIMITS.get(plan or "free", PLAN_LIMITS["free"]).get(feature)


# ─────────────────────────────────────────────────────────────────────────────
# REGISTRATION
# ─────────────────────────────────────────────────────────────────────────────

def register_user(email: str, password: str, full_name: str) -> dict:
    email = email.lower().strip()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return {"success": False, "error": "Invalid email address"}
    if len(password) < 8:
        return {"success": False, "error": "Password must be at least 8 characters"}
    if not full_name or not full_name.strip():
        return {"success": False, "error": "Full name is required"}

    email_hash = hashlib.sha256(email.encode()).hexdigest()
    pw_hash    = hash_password(password)
    enc_email  = encrypt_field(email)
    enc_name   = encrypt_field(full_name.strip())

    sb = get_supabase()
    if sb:
        try:
            existing = sb.table("users").select("id").eq("email_hash", email_hash).execute()
            if existing.data:
                return {"success": False, "error": "An account with this email already exists"}
            uid = secrets.token_hex(16)
            sb.table("users").insert({
                "id":                    uid,
                "email_hash":            email_hash,
                "email_encrypted":       enc_email,
                "full_name_encrypted":   enc_name,
                "password_hash":         pw_hash,
                "plan":                  "free",
                "mfa_enabled":           False,
                "totp_secret_encrypted": None,
                "notifications":         {"email": False, "signals": False, "alerts": False},
                "email_verified":        False,
                "created_at":            datetime.now().isoformat(),
            }).execute()
            return {"success": True, "user_id": uid}
        except Exception as e:
            err = str(e).lower()
            if "duplicate" in err or "unique" in err:
                return {"success": False, "error": "An account with this email already exists"}
            return {"success": False, "error": "Registration failed. Please try again."}
    else:
        users = _demo_users()
        if email_hash in users:
            return {"success": False, "error": "An account with this email already exists"}
        uid = secrets.token_hex(16)
        users[email_hash] = {
            "id": uid, "email": email, "full_name": full_name.strip(),
            "email_hash": email_hash, "password_hash": pw_hash,
            "plan": "free", "mfa_enabled": False, "totp_secret": None,
            "notifications": {"email": False, "signals": False, "alerts": False},
            "email_verified": False,
            "created_at": datetime.now().isoformat(), "last_login": None,
        }
        return {"success": True, "user_id": uid}


# ─────────────────────────────────────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────────────────────────────────────

def login_user(email: str, password: str) -> dict:
    email = email.lower().strip()
    email_hash = hashlib.sha256(email.encode()).hexdigest()

    sb = get_supabase()
    if sb:
        try:
            res = sb.table("users").select("*").eq("email_hash", email_hash).execute()
            if not res.data:
                return {"success": False, "error": "Invalid email or password"}
            row = res.data[0]
            if not verify_password(password, row["password_hash"]):
                return {"success": False, "error": "Invalid email or password"}
            sb.table("users").update({"last_login": datetime.now().isoformat()}).eq("id", row["id"]).execute()
            notif_raw = row.get("notifications") or "{}"
            user = {
                "id":          row["id"],
                "email":       decrypt_field(row.get("email_encrypted", "")),
                "full_name":   decrypt_field(row.get("full_name_encrypted", "")),
                "plan":        row.get("plan", "free"),
                "mfa_enabled": row.get("mfa_enabled", False),
                "totp_secret": decrypt_field(row.get("totp_secret_encrypted") or "") or None,
                "notifications": json.loads(notif_raw) if isinstance(notif_raw, str) else notif_raw,
                "email_verified": bool(row.get("email_verified", True)),
                "created_at":  row.get("created_at"),
            }
            return {"success": True, "user": user}
        except Exception:
            return {"success": False, "error": "Login failed. Please try again."}
    else:
        users = _demo_users()
        if email_hash not in users:
            return {"success": False, "error": "Invalid email or password"}
        u = users[email_hash]
        if not verify_password(password, u["password_hash"]):
            return {"success": False, "error": "Invalid email or password"}
        u["last_login"] = datetime.now().isoformat()
        return {"success": True, "user": {k: v for k, v in u.items() if k != "password_hash"}}


# ─────────────────────────────────────────────────────────────────────────────
# MFA / TOTP
# ─────────────────────────────────────────────────────────────────────────────

def generate_totp_secret(user_email: str) -> dict:
    secret = pyotp.random_base32()
    uri    = pyotp.TOTP(secret).provisioning_uri(name=user_email, issuer_name="QNTM")
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#000000", back_color="#ffffff")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return {"secret": secret, "uri": uri, "qr_bytes": buf.getvalue()}


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    try:
        return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)
    except Exception:
        return False


def enable_mfa(user_id: str, secret: str) -> bool:
    enc = encrypt_field(secret)
    sb = get_supabase()
    if sb:
        try:
            sb.table("users").update({"totp_secret_encrypted": enc, "mfa_enabled": True}).eq("id", user_id).execute()
            return True
        except Exception:
            return False
    u = _demo_find_user(user_id)
    if u:
        u["totp_secret"] = secret
        u["mfa_enabled"] = True
        return True
    return False


def disable_mfa(user_id: str) -> bool:
    sb = get_supabase()
    if sb:
        try:
            sb.table("users").update({"totp_secret_encrypted": None, "mfa_enabled": False}).eq("id", user_id).execute()
            return True
        except Exception:
            return False
    u = _demo_find_user(user_id)
    if u:
        u["totp_secret"] = None
        u["mfa_enabled"] = False
        return True
    return False


def get_user_mfa(user_id: str) -> dict:
    sb = get_supabase()
    if sb:
        try:
            res = sb.table("users").select("mfa_enabled,totp_secret_encrypted").eq("id", user_id).execute()
            if res.data:
                r = res.data[0]
                return {"mfa_enabled": r.get("mfa_enabled", False),
                        "totp_secret": decrypt_field(r.get("totp_secret_encrypted") or "") or None}
        except Exception:
            pass
        return {"mfa_enabled": False, "totp_secret": None}
    u = _demo_find_user(user_id)
    if u:
        return {"mfa_enabled": u.get("mfa_enabled", False), "totp_secret": u.get("totp_secret")}
    return {"mfa_enabled": False, "totp_secret": None}


# ─────────────────────────────────────────────────────────────────────────────
# HOLDINGS
# ─────────────────────────────────────────────────────────────────────────────

def get_holdings(user_id: str) -> list:
    sb = get_supabase()
    if sb:
        try:
            return sb.table("holdings").select("*").eq("user_id", user_id).order("ticker").execute().data or []
        except Exception:
            return []
    return sorted(_demo_holdings().get(user_id, []), key=lambda x: x["ticker"])


def upsert_holding(user_id: str, ticker: str, shares: float,
                   avg_cost: float, entry_date=None, notes: str = "") -> bool:
    ticker = ticker.upper().strip()
    if not ticker:
        return False
    record = {
        "user_id":    user_id,
        "ticker":     ticker,
        "shares":     round(float(shares), 4),
        "avg_cost":   round(float(avg_cost), 4),
        "entry_date": str(entry_date or date.today()),
        "notes":      (notes or "")[:200],
        "updated_at": datetime.now().isoformat(),
    }
    sb = get_supabase()
    if sb:
        try:
            sb.table("holdings").upsert(record, on_conflict="user_id,ticker").execute()
            return True
        except Exception:
            return False
    h = _demo_holdings()
    if user_id not in h:
        h[user_id] = []
    idx = next((i for i, x in enumerate(h[user_id]) if x["ticker"] == ticker), None)
    if idx is not None:
        h[user_id][idx].update(record)
    else:
        record["id"] = secrets.token_hex(8)
        h[user_id].append(record)
    return True


def delete_holding(user_id: str, ticker: str) -> bool:
    ticker = ticker.upper().strip()
    sb = get_supabase()
    if sb:
        try:
            sb.table("holdings").delete().eq("user_id", user_id).eq("ticker", ticker).execute()
            return True
        except Exception:
            return False
    h = _demo_holdings()
    if user_id in h:
        h[user_id] = [x for x in h[user_id] if x["ticker"] != ticker]
    return True


# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATIONS
# ─────────────────────────────────────────────────────────────────────────────

def get_notifications(user_id: str, unread_only: bool = False, limit: int = 50) -> list:
    sb = get_supabase()
    if sb:
        try:
            q = sb.table("notifications").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(limit)
            if unread_only:
                q = q.eq("is_read", False)
            return q.execute().data or []
        except Exception:
            return []
    n = _demo_notifs().get(user_id, [])
    if unread_only:
        n = [x for x in n if not x.get("is_read")]
    return n[:limit]


def create_notification(user_id: str, ticker: str, notif_type: str, title: str, body: str) -> bool:
    record = {
        "user_id": user_id, "ticker": ticker,
        "notification_type": notif_type,
        "title": title[:120], "body": body[:500],
        "is_read": False,
        "created_at": datetime.now().isoformat(),
    }
    sb = get_supabase()
    if sb:
        try:
            sb.table("notifications").insert(record).execute()
            return True
        except Exception:
            return False
    n = _demo_notifs()
    if user_id not in n:
        n[user_id] = []
    record["id"] = secrets.token_hex(8)
    n[user_id].insert(0, record)
    n[user_id] = n[user_id][:100]
    return True


def mark_notifications_read(user_id: str, notif_ids: list = None) -> bool:
    sb = get_supabase()
    if sb:
        try:
            q = sb.table("notifications").update({"is_read": True}).eq("user_id", user_id)
            if notif_ids:
                q = q.in_("id", notif_ids)
            q.execute()
            return True
        except Exception:
            return False
    for n in _demo_notifs().get(user_id, []):
        if notif_ids is None or n.get("id") in notif_ids:
            n["is_read"] = True
    return True


def get_unread_count(user_id: str) -> int:
    return len(get_notifications(user_id, unread_only=True, limit=99))


# ─────────────────────────────────────────────────────────────────────────────
# USER PREFERENCES & PLAN
# ─────────────────────────────────────────────────────────────────────────────

def update_preferences(user_id: str, prefs: dict) -> bool:
    prefs = dict(prefs)
    prefs.pop("password_hash", None)

    if "full_name" in prefs:
        prefs["full_name_encrypted"] = encrypt_field(prefs.pop("full_name"))
    # Supabase jsonb columns accept dicts directly — no json.dumps needed
    # Keep as dict for Supabase; only stringify for demo in-memory store

    sb = get_supabase()
    if sb:
        try:
            sb.table("users").update(prefs).eq("id", user_id).execute()
            return True
        except Exception:
            return False
    u = _demo_find_user(user_id)
    if u:
        for k, v in prefs.items():
            if k == "full_name_encrypted":
                u["full_name"] = decrypt_field(v)
            elif k == "notifications":
                u["notifications"] = json.loads(v) if isinstance(v, str) else v
            else:
                u[k] = v
        return True
    return False


def update_email(user_id: str, new_email: str) -> dict:
    """Change a user's email. Re-hashes (for lookup) and re-encrypts (for
    storage) and enforces uniqueness. NOTE: does not by itself prove the user
    owns the new address — pair with email verification before relying on it
    for account recovery."""
    new_email = (new_email or "").lower().strip()
    if not new_email or "@" not in new_email or "." not in new_email.split("@")[-1]:
        return {"success": False, "error": "Invalid email address"}
    new_hash = hashlib.sha256(new_email.encode()).hexdigest()
    enc = encrypt_field(new_email)
    sb = get_supabase()
    if sb:
        try:
            existing = sb.table("users").select("id").eq("email_hash", new_hash).execute()
            if existing.data and existing.data[0]["id"] != user_id:
                return {"success": False, "error": "That email is already in use"}
            sb.table("users").update({
                "email_hash":      new_hash,
                "email_encrypted": enc,
            }).eq("id", user_id).execute()
            return {"success": True}
        except Exception as e:
            err = str(e).lower()
            if "duplicate" in err or "unique" in err:
                return {"success": False, "error": "That email is already in use"}
            return {"success": False, "error": "Update failed. Please try again."}
    users = _demo_users()
    for h, u in list(users.items()):
        if u["id"] == user_id:
            if new_hash in users and users[new_hash]["id"] != user_id:
                return {"success": False, "error": "That email is already in use"}
            users.pop(h, None)
            u["email"] = new_email
            u["email_hash"] = new_hash
            users[new_hash] = u
            return {"success": True}
    return {"success": False, "error": "User not found"}


def upgrade_plan(user_id: str, new_plan: str) -> bool:
    if new_plan not in PLAN_LIMITS:
        return False
    ok = update_preferences(user_id, {"plan": new_plan})
    if ok:
        if st.session_state.get("user"):
            st.session_state.user["plan"] = new_plan
        create_notification(
            user_id, "", "plan_change",
            f"Plan updated to {new_plan.upper()}",
            f"Your account is now on the {new_plan.title()} plan."
            + (" Unlimited holdings, Hidden Gems, and alerts are active." if new_plan != "free" else ""),
        )
    return ok


def schedule_cancellation(user_id: str, period_end_date: str) -> bool:
    """
    Mark a Pro/Founding Member account as scheduled to cancel at the end of
    the current billing period. Stored as `cancel_at` (ISO date) inside the
    user's notifications JSON blob so no schema migration is needed.
    Cancellation does not take effect immediately — the user keeps Pro access
    until period_end_date, at which point a separate downgrade step (Stripe
    webhook later, manual job today) flips plan to "free".
    """
    user = get_user_by_id(user_id) or {}
    prefs = user.get("notifications") or {}
    if not isinstance(prefs, dict):
        prefs = {}
    prefs["cancel_at"] = str(period_end_date)
    ok = update_preferences(user_id, {"notifications": prefs})
    if ok:
        if st.session_state.get("user"):
            cur = st.session_state.user.get("notifications") or {}
            cur["cancel_at"] = str(period_end_date)
            st.session_state.user["notifications"] = cur
        create_notification(
            user_id, "", "plan_change",
            "Cancellation scheduled",
            f"Your Pro subscription will end on {period_end_date}. "
            f"Pro access continues until then. No refunds for partial months.",
        )
    return ok


def set_stripe_billing(user_id: str, customer_id: str = None, subscription_id: str = None,
                       billing_active: bool = None, status: str = None) -> bool:
    """Store Stripe IDs + billing state in the user's notifications JSON blob
    (no schema migration). Any arg left None is preserved."""
    user = get_user_by_id(user_id) or {}
    prefs = user.get("notifications") or {}
    if not isinstance(prefs, dict):
        prefs = {}
    if customer_id is not None:
        prefs["stripe_customer_id"] = customer_id
    if subscription_id is not None:
        prefs["stripe_subscription_id"] = subscription_id
    if billing_active is not None:
        prefs["billing_active"] = bool(billing_active)
    if status is not None:
        prefs["stripe_status"] = status
    ok = update_preferences(user_id, {"notifications": prefs})
    if ok and st.session_state.get("user"):
        st.session_state.user["notifications"] = prefs
    return ok


def get_stripe_billing(user_id: str) -> dict:
    """Return {stripe_customer_id, stripe_subscription_id, billing_active, stripe_status}."""
    user = get_user_by_id(user_id) or {}
    prefs = user.get("notifications") or {}
    if not isinstance(prefs, dict):
        prefs = {}
    return {
        "stripe_customer_id":     prefs.get("stripe_customer_id"),
        "stripe_subscription_id": prefs.get("stripe_subscription_id"),
        "billing_active":         bool(prefs.get("billing_active", False)),
        "stripe_status":          prefs.get("stripe_status"),
    }


def undo_cancellation(user_id: str) -> bool:
    """Remove a pending cancellation so the subscription continues."""
    user = get_user_by_id(user_id) or {}
    prefs = user.get("notifications") or {}
    if not isinstance(prefs, dict):
        prefs = {}
    if "cancel_at" not in prefs:
        return True  # nothing to undo
    prefs.pop("cancel_at", None)
    ok = update_preferences(user_id, {"notifications": prefs})
    if ok:
        if st.session_state.get("user"):
            cur = st.session_state.user.get("notifications") or {}
            cur.pop("cancel_at", None)
            st.session_state.user["notifications"] = cur
        create_notification(
            user_id, "", "plan_change",
            "Cancellation undone",
            "Your Pro subscription will continue. Billing resumes on your normal anniversary.",
        )
    return ok


def get_user_by_id(user_id: str) -> Optional[dict]:
    sb = get_supabase()
    if sb:
        try:
            res = sb.table("users").select("*").eq("id", user_id).execute()
            if res.data:
                r = res.data[0]
                notif_raw = r.get("notifications") or "{}"
                return {
                    "id":          r["id"],
                    "email":       decrypt_field(r.get("email_encrypted", "")),
                    "full_name":   decrypt_field(r.get("full_name_encrypted", "")),
                    "plan":        r.get("plan", "free"),
                    "mfa_enabled": r.get("mfa_enabled", False),
                    "totp_secret": decrypt_field(r.get("totp_secret_encrypted") or "") or None,
                    "notifications": json.loads(notif_raw) if isinstance(notif_raw, str) else notif_raw,
                    "created_at":  r.get("created_at"),
                }
        except Exception:
            pass
        return None
    return _demo_find_user(user_id)


# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL CHANGE DETECTION  (pro/institutional only)
# ─────────────────────────────────────────────────────────────────────────────

def _sig_label(action: str) -> str:
    """Convert internal BUY/HOLD/SELL to display HIGH/MODERATE/LOW."""
    return {"BUY": "HIGH", "HOLD": "MODERATE", "SELL": "LOW"}.get(action, action)


def check_and_notify_signal_changes(user_id: str, plan: str,
                                     current_scores: dict,
                                     prev_signals: dict = None) -> list:
    """
    Detect signal changes and score deterioration on held positions.
    Fires notifications for:
      - BUY/HOLD/SELL action changes on held stocks
      - Score deterioration ≥10 points within HOLD (early warning)
      - Score recovery ≥10 points (re-entry signal)
      - Hidden gem detection on held stocks
    """
    if plan == "free" or not plan_limit(plan, "notifications"):
        return []
    if not prev_signals:
        return []

    holdings = get_holdings(user_id)
    held     = {h["ticker"] for h in holdings}
    changes  = []

    for ticker in held:
        curr = current_scores.get(ticker)
        if not curr:
            continue

        curr_action = curr.get("adj_action", curr.get("action", "HOLD"))
        curr_score  = float(curr.get("adj_composite", curr.get("composite", 0)) or 0)
        curr_mom    = float(curr.get("momentum", 0) or 0)
        curr_qual   = float(curr.get("quality",  0) or 0)

        prev        = prev_signals.get(ticker, {})
        prev_action = prev.get("action", "HOLD") if isinstance(prev, dict) else str(prev)
        prev_score  = float(prev.get("score", curr_score) if isinstance(prev, dict) else curr_score)

        score_delta = curr_score - prev_score

        # ── Action change alert ───────────────────────────────────────────────
        if prev_action and curr_action != prev_action:
            ntype = {"BUY": "buy_signal", "SELL": "sell_signal"}.get(curr_action, "system")
            arrow = "▲" if curr_action == "BUY" else "▼" if curr_action == "SELL" else "─"
            prev_lbl = _sig_label(prev_action)
            curr_lbl = _sig_label(curr_action)
            create_notification(
                user_id, ticker, ntype,
                f"{arrow} {ticker}: {prev_lbl} → {curr_lbl} conviction",
                f"Score {curr_score:.0f} (was {prev_score:.0f}) · "
                f"Momentum {curr_mom:.0f} · Quality {curr_qual:.0f}. "
                f"Model conviction changed from {prev_lbl} to {curr_lbl}."
            )
            changes.append({"ticker": ticker, "from": prev_action, "to": curr_action, "type": "action_change"})

        # ── Score deterioration alert (≥10pt drop, still MODERATE) ───────────
        elif curr_action == "HOLD" and score_delta <= -10:
            create_notification(
                user_id, ticker, "sell_signal",
                f"⚠ {ticker}: Score deteriorating ({prev_score:.0f} → {curr_score:.0f})",
                f"Score dropped {abs(score_delta):.0f} points. Still MODERATE but approaching LOW threshold. "
                f"Momentum {curr_mom:.0f} · Quality {curr_qual:.0f}. Monitor closely."
            )
            changes.append({"ticker": ticker, "from": prev_action, "to": curr_action,
                           "type": "deterioration", "delta": score_delta})

        # ── Score recovery alert (≥10pt gain back into HIGH territory) ────────
        elif curr_action == "BUY" and prev_action == "HOLD" and score_delta >= 10:
            create_notification(
                user_id, ticker, "buy_signal",
                f"▲ {ticker}: Conviction strengthening ({prev_score:.0f} → {curr_score:.0f})",
                f"Score recovered {score_delta:.0f} points. HIGH conviction reinforced. "
                f"Momentum {curr_mom:.0f} · Quality {curr_qual:.0f}."
            )
            changes.append({"ticker": ticker, "from": prev_action, "to": curr_action,
                           "type": "recovery", "delta": score_delta})

        # ── Hidden gem detection on held stocks ───────────────────────────────
        if curr.get("is_hidden_gem") and not prev.get("was_gem"):
            create_notification(
                user_id, ticker, "hidden_gem",
                f"💎 {ticker}: Now a Hidden Gem",
                f"Score {curr_score:.0f} · {', '.join(curr.get('gem_reasons', [])[:2])}"
            )
            changes.append({"ticker": ticker, "type": "gem_detected"})

    return changes


def save_signal_snapshot(user_id: str, scores: list):
    """
    Persist signal snapshot to Supabase so deterioration is detected
    across sessions — not just within a single session.
    Falls back to session state if Supabase unavailable.
    """
    snapshot = {}
    for s in scores:
        snapshot[s["ticker"]] = {
            "action":  s.get("adj_action", s.get("action", "HOLD")),
            "score":   float(s.get("adj_composite", s.get("composite", 0)) or 0),
            "was_gem": bool(s.get("is_hidden_gem", False)),
        }

    # Try to persist to Supabase signal_snapshot table
    sb = get_supabase()
    if sb:
        try:
            sb.table("signal_snapshots").upsert({
                "user_id":    user_id,
                "snapshot":   json.dumps(snapshot),
                "updated_at": datetime.now().isoformat(),
            }, on_conflict="user_id").execute()
        except Exception:
            pass  # fall through to session state

    # Always keep in session state as fast cache
    if "qntm_signal_snapshots" not in st.session_state:
        st.session_state.qntm_signal_snapshots = {}
    st.session_state.qntm_signal_snapshots[user_id] = snapshot


def get_signal_snapshot(user_id: str) -> dict:
    """
    Load signal snapshot — session state first (fast), then Supabase.
    Returns {ticker: {action, score, was_gem}} or {} if no snapshot.
    """
    # Session state cache
    cached = (st.session_state.get("qntm_signal_snapshots") or {}).get(user_id)
    if cached:
        return cached

    # Load from Supabase
    sb = get_supabase()
    if sb:
        try:
            res = sb.table("signal_snapshots").select("snapshot").eq("user_id", user_id).execute()
            if res.data:
                snapshot = json.loads(res.data[0]["snapshot"])
                # Cache in session state
                if "qntm_signal_snapshots" not in st.session_state:
                    st.session_state.qntm_signal_snapshots = {}
                st.session_state.qntm_signal_snapshots[user_id] = snapshot
                return snapshot
        except Exception:
            pass
    return {}


# ══════════════════════════════════════════════════════════════════════════════
# MULTI-WATCHLISTS  (watchlists + watchlist_items)
# ══════════════════════════════════════════════════════════════════════════════

def get_watchlists(user_id: str) -> list:
    """Return all named watchlists for a user, default first. Auto-creates a
    default list if none exist. Returns [{id, name, is_default, created_at}]."""
    sb = get_supabase()
    if not sb:
        return []
    try:
        resp = sb.table("watchlists").select("*").eq("user_id", user_id) \
            .order("is_default", desc=True).order("created_at", desc=False).execute()
        lists = resp.data or []
        if not lists:
            created = create_watchlist(user_id, "My Watchlist", is_default=True)
            return [created] if created else []
        return lists
    except Exception:
        return []


def create_watchlist(user_id: str, name: str, is_default: bool = False) -> Optional[dict]:
    """Create a new named watchlist. Returns the created row or None."""
    sb = get_supabase()
    if not sb:
        return None
    name = (name or "").strip()
    if not name:
        return None
    try:
        resp = sb.table("watchlists").insert({
            "user_id": user_id, "name": name, "is_default": is_default,
        }).execute()
        return (resp.data or [None])[0]
    except Exception:
        return None


def rename_watchlist(user_id: str, list_id: str, new_name: str) -> bool:
    sb = get_supabase()
    if not sb:
        return False
    new_name = (new_name or "").strip()
    if not new_name:
        return False
    try:
        sb.table("watchlists").update({"name": new_name}) \
            .eq("id", list_id).eq("user_id", user_id).execute()
        return True
    except Exception:
        return False


def delete_watchlist(user_id: str, list_id: str) -> bool:
    """Delete a watchlist and its items (cascade). Refuses to delete the
    user's last remaining list."""
    sb = get_supabase()
    if not sb:
        return False
    try:
        existing = sb.table("watchlists").select("id").eq("user_id", user_id).execute()
        if len((existing.data or [])) <= 1:
            return False
        sb.table("watchlists").delete().eq("id", list_id).eq("user_id", user_id).execute()
        return True
    except Exception:
        return False


def get_watchlist_items(user_id: str, list_id: str) -> list:
    """Return items in a specific watchlist, newest first.
    Each item: {id, ticker, price_at_add, added_at}."""
    sb = get_supabase()
    if not sb:
        return []
    try:
        resp = sb.table("watchlist_items").select("*") \
            .eq("user_id", user_id).eq("watchlist_id", list_id) \
            .order("added_at", desc=True).execute()
        return resp.data or []
    except Exception:
        return []


def add_watchlist_item(user_id: str, list_id: str, ticker: str,
                       price_at_add: float = None) -> bool:
    """Add a ticker to a specific watchlist (idempotent per list+ticker)."""
    sb = get_supabase()
    if not sb:
        return False
    try:
        payload = {
            "watchlist_id": list_id, "user_id": user_id,
            "ticker": ticker.strip().upper(),
        }
        if price_at_add:
            payload["price_at_add"] = round(float(price_at_add), 4)
        sb.table("watchlist_items").upsert(
            payload, on_conflict="watchlist_id,ticker"
        ).execute()
        return True
    except Exception:
        return False


def remove_watchlist_item(user_id: str, list_id: str, ticker: str) -> bool:
    sb = get_supabase()
    if not sb:
        return False
    try:
        sb.table("watchlist_items").delete() \
            .eq("user_id", user_id).eq("watchlist_id", list_id) \
            .eq("ticker", ticker.strip().upper()).execute()
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# PAPER TRADING  (paper_positions)
# ══════════════════════════════════════════════════════════════════════════════

def get_paper_positions(user_id: str, open_only: bool = False) -> list:
    """Return paper-trade positions for a user, newest entry first."""
    sb = get_supabase()
    if not sb:
        return []
    try:
        q = sb.table("paper_positions").select("*").eq("user_id", user_id)
        if open_only:
            q = q.eq("is_open", True)
        resp = q.order("entry_date", desc=True).execute()
        return resp.data or []
    except Exception:
        return []


def open_paper_position(user_id: str, ticker: str, entry_date: str,
                        entry_price: float, shares: float,
                        note: str = None) -> Optional[dict]:
    """Open a paper trade. position_size is denormalized (entry_price*shares)."""
    sb = get_supabase()
    if not sb:
        return None
    try:
        entry_price = round(float(entry_price), 4)
        shares = round(float(shares), 6)
        payload = {
            "user_id": user_id, "ticker": ticker.strip().upper(),
            "entry_date": entry_date, "entry_price": entry_price,
            "shares": shares, "position_size": round(entry_price * shares, 4),
            "is_open": True,
        }
        if note:
            payload["note"] = note
        resp = sb.table("paper_positions").insert(payload).execute()
        return (resp.data or [None])[0]
    except Exception:
        return None


def close_paper_position(user_id: str, position_id: str, exit_date: str,
                         exit_price: float) -> bool:
    sb = get_supabase()
    if not sb:
        return False
    try:
        sb.table("paper_positions").update({
            "is_open": False, "exit_date": exit_date,
            "exit_price": round(float(exit_price), 4),
        }).eq("id", position_id).eq("user_id", user_id).execute()
        return True
    except Exception:
        return False


def delete_paper_position(user_id: str, position_id: str) -> bool:
    sb = get_supabase()
    if not sb:
        return False
    try:
        sb.table("paper_positions").delete() \
            .eq("id", position_id).eq("user_id", user_id).execute()
        return True
    except Exception:
        return False


def get_signal_dates(limit: int = 60) -> list:
    """Return distinct signal_date values (newest first) so the paper-trade
    entry-date picker only offers dates that actually have prices."""
    sb = get_supabase()
    if not sb:
        return []
    try:
        resp = sb.table("signal_log").select("signal_date") \
            .order("signal_date", desc=True).limit(5000).execute()
        seen = []
        for r in (resp.data or []):
            d = r.get("signal_date")
            if d and d not in seen:
                seen.append(d)
            if len(seen) >= limit:
                break
        return seen
    except Exception:
        return []


def get_price_on_date(ticker: str, signal_date: str) -> Optional[float]:
    """Closing price for a ticker on a specific signal_date (for entry-price
    auto-fill). Returns None if no row exists."""
    sb = get_supabase()
    if not sb:
        return None
    try:
        resp = sb.table("signal_log").select("price") \
            .eq("ticker", ticker.strip().upper()).eq("signal_date", signal_date) \
            .limit(1).execute()
        if resp.data and resp.data[0].get("price"):
            return float(resp.data[0]["price"])
        return None
    except Exception:
        return None


def get_price_on_date_latest(ticker: str):
    """Most recent signal_log price for a ticker (for 'add now' baseline)."""
    sb = get_supabase()
    if not sb:
        return None
    try:
        resp = sb.table("signal_log").select("price") \
            .eq("ticker", ticker.strip().upper()).order("signal_date", desc=True) \
            .limit(1).execute()
        if resp.data and resp.data[0].get("price"):
            return float(resp.data[0]["price"])
        return None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# TRANSACTIONAL EMAIL (SendGrid)
# ─────────────────────────────────────────────────────────────────────────────

def send_email(to_email: str, subject: str, html: str, text: str = None) -> dict:
    """Send a transactional email via SendGrid.

    Fails soft: returns {"success": False, ...} (never raises) if SendGrid
    isn't configured or the package isn't installed, so callers degrade
    gracefully. Configure with SENDGRID_API_KEY and SENDGRID_FROM in secrets/env
    (SENDGRID_FROM must be a verified sender or on an authenticated domain)."""
    try:
        api_key   = st.secrets.get("SENDGRID_API_KEY") or os.getenv("SENDGRID_API_KEY")
        from_email = st.secrets.get("SENDGRID_FROM")   or os.getenv("SENDGRID_FROM")
    except Exception:
        api_key    = os.getenv("SENDGRID_API_KEY")
        from_email = os.getenv("SENDGRID_FROM")
    if not api_key or not from_email:
        return {"success": False, "error": "Email not configured"}
    if not to_email:
        return {"success": False, "error": "No recipient"}
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
        kwargs = dict(from_email=from_email, to_emails=to_email,
                      subject=subject, html_content=html)
        if text:
            kwargs["plain_text_content"] = text
        resp = SendGridAPIClient(api_key).send(Mail(**kwargs))
        return {"success": 200 <= resp.status_code < 300, "status": resp.status_code}
    except ImportError:
        return {"success": False, "error": "sendgrid package not installed"}
    except Exception as e:
        return {"success": False, "error": f"Send failed: {str(e)[:120]}"}


# ─────────────────────────────────────────────────────────────────────────────
# PASSWORD RESET  (token-based, emailed link)
# ─────────────────────────────────────────────────────────────────────────────

def _user_id_by_email(email: str):
    email = (email or "").lower().strip()
    if not email:
        return None
    eh = hashlib.sha256(email.encode()).hexdigest()
    sb = get_supabase()
    if sb:
        try:
            r = sb.table("users").select("id").eq("email_hash", eh).execute()
            return r.data[0]["id"] if r.data else None
        except Exception:
            return None
    for u in _demo_users().values():
        if u.get("email_hash") == eh:
            return u["id"]
    return None


def create_auth_token(user_id: str, kind: str = "reset", ttl_minutes: int = 30) -> str:
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    token = secrets.token_urlsafe(32)
    expires = (_dt.now(_tz.utc) + _td(minutes=ttl_minutes)).isoformat()
    sb = get_supabase()
    if sb:
        try:
            sb.table("auth_tokens").insert({
                "token": token, "user_id": user_id, "kind": kind,
                "expires_at": expires, "used": False,
            }).execute()
        except Exception:
            return ""
    else:
        store = st.session_state.setdefault("qntm_demo_tokens", {})
        store[token] = {"user_id": user_id, "kind": kind, "expires_at": expires, "used": False}
    return token


def _token_row(token: str):
    sb = get_supabase()
    if sb:
        try:
            r = sb.table("auth_tokens").select("*").eq("token", token).execute()
            return r.data[0] if r.data else None
        except Exception:
            return None
    return st.session_state.get("qntm_demo_tokens", {}).get(token)


def _token_valid(row, kind) -> bool:
    if not row or row.get("used") or row.get("kind") != kind:
        return False
    from datetime import datetime as _dt, timezone as _tz
    try:
        exp = _dt.fromisoformat(str(row.get("expires_at")).replace("Z", "+00:00"))
    except Exception:
        return False
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=_tz.utc)
    return exp >= _dt.now(_tz.utc)


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
    sb = get_supabase()
    if sb:
        try:
            sb.table("auth_tokens").update({"used": True}).eq("token", token).execute()
        except Exception:
            return None
    else:
        store = st.session_state.get("qntm_demo_tokens", {})
        if token in store:
            store[token]["used"] = True
    return row["user_id"]


def set_password(user_id: str, new_password: str) -> dict:
    if not new_password or len(new_password) < 8:
        return {"success": False, "error": "Password must be at least 8 characters"}
    pw_hash = hash_password(new_password)
    sb = get_supabase()
    if sb:
        try:
            sb.table("users").update({"password_hash": pw_hash}).eq("id", user_id).execute()
            return {"success": True}
        except Exception:
            return {"success": False, "error": "Couldn't update password"}
    u = _demo_find_user(user_id)
    if u:
        u["password_hash"] = pw_hash
        return {"success": True}
    return {"success": False, "error": "User not found"}


def request_password_reset(email: str) -> dict:
    """Generate a reset token and email a link. ALWAYS returns success — never
    reveals whether an account exists (prevents email enumeration)."""
    uid_ = _user_id_by_email(email)
    if uid_:
        token = create_auth_token(uid_, kind="reset", ttl_minutes=30)
        if token:
            try:
                base = st.secrets.get("APP_URL") or os.getenv("APP_URL") or "https://qntm.live"
            except Exception:
                base = os.getenv("APP_URL") or "https://qntm.live"
            link = f"{base.rstrip('/')}/?reset_token={token}"
            html = (
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
            send_email(
                (email or "").lower().strip(),
                "Reset your QNTM password",
                html,
                text=f"Reset your QNTM password: {link}\n\n"
                     "This link expires in 30 minutes. If you didn't request this, ignore this email.",
            )
    return {"success": True}


def change_password(user_id: str, current_password: str, new_password: str) -> dict:
    """Logged-in password change: verifies the current password before setting
    the new one."""
    if not new_password or len(new_password) < 8:
        return {"success": False, "error": "New password must be at least 8 characters"}
    sb = get_supabase()
    if sb:
        try:
            r = sb.table("users").select("password_hash").eq("id", user_id).execute()
            if not r.data:
                return {"success": False, "error": "User not found"}
            current_hash = r.data[0].get("password_hash")
        except Exception:
            return {"success": False, "error": "Couldn't verify current password"}
    else:
        u = _demo_find_user(user_id)
        if not u:
            return {"success": False, "error": "User not found"}
        current_hash = u.get("password_hash")
    if not verify_password(current_password or "", current_hash or ""):
        return {"success": False, "error": "Current password is incorrect"}
    return set_password(user_id, new_password)


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL VERIFICATION (soft gate — users can use the app, banner nags until done)
# ─────────────────────────────────────────────────────────────────────────────

def is_email_verified(user_id: str) -> bool:
    """Return True if the user's email is confirmed. Fails CLOSED (False) on a
    read error so the alert-email path never sends to an unconfirmed address."""
    if not user_id:
        return False
    sb = get_supabase()
    if sb:
        try:
            r = sb.table("users").select("email_verified").eq("id", user_id).execute()
            if r.data:
                return bool(r.data[0].get("email_verified"))
            return False
        except Exception:
            return False
    u = _demo_find_user(user_id)
    return bool(u.get("email_verified")) if u else False


def request_email_verification(email: str) -> dict:
    """Create a verify token and email a confirmation link. Always returns
    success (never reveals whether an account exists). Safe to call on signup
    and from a 'resend' button."""
    uid_ = _user_id_by_email(email)
    if uid_:
        token = create_auth_token(uid_, kind="verify", ttl_minutes=60 * 24)  # 24h
        if token:
            try:
                base = st.secrets.get("APP_URL") or os.getenv("APP_URL") or "https://qntm.live"
            except Exception:
                base = os.getenv("APP_URL") or "https://qntm.live"
            link = f"{base.rstrip('/')}/?verify_token={token}"
            html = (
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
            send_email(
                (email or "").lower().strip(),
                "Confirm your QNTM email",
                html,
                text=f"Welcome to QNTM. Confirm your email: {link}\n\n"
                     "This link expires in 24 hours. If you didn't create an account, ignore this email.",
            )
    return {"success": True}


def consume_verify_token(token: str) -> dict:
    """Validate a verify token (one-time), mark the user's email confirmed."""
    if not token:
        return {"success": False, "error": "Missing verification token"}
    uid_ = consume_auth_token(token, kind="verify")
    if not uid_:
        return {"success": False, "error": "This link is invalid or has expired"}
    sb = get_supabase()
    if sb:
        try:
            sb.table("users").update({"email_verified": True}).eq("id", uid_).execute()
            return {"success": True, "user_id": uid_}
        except Exception:
            return {"success": False, "error": "Couldn't confirm your email — please try again"}
    u = _demo_find_user(uid_)
    if u:
        u["email_verified"] = True
        return {"success": True, "user_id": uid_}
    return {"success": False, "error": "Account not found"}
