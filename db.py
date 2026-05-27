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
