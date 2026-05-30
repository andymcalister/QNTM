"""
QNTM — California Automatic Renewal Law (AB 2863) compliance helpers.
=====================================================================
Centralizes the recordkeeping + notice logic required by Bus. & Prof.
Code §§17601–17602. Kept in one module so the compliance surface is
auditable in a single place.

FLAG FOR ATTORNEY REVIEW: all user-facing copy and the notice/consent
logic below must be reviewed by fintech counsel before taking paying users.

Email sending is STUBBED: templates are built and every send is logged to
notices_sent (delivered=False) so the audit trail exists now; wire a real
provider (e.g. SendGrid) in `_send_email` when the API key is available.
"""

import os
import logging
from datetime import datetime, date, timedelta

log = logging.getLogger("qntm.arl")

# Bump when the disclosure/checkbox/notice copy changes — recorded with each
# consent + notice so we can prove exactly what a user saw.
TERMS_VERSION   = "2026-05-30"
CONTENT_VERSION = "2026-05-30"

RENEWAL_PRICE = "$29.00/month"
TRIAL_TERMS   = "7-day free trial"
SUPPORT_EMAIL = "hello@qntm.app"


def _sb():
    """Service-role Supabase client (writes/cron). Reuses data_refresh's client."""
    try:
        from data_refresh import _get_supabase
        return _get_supabase()
    except Exception as e:
        log.warning(f"ARL: no supabase client: {e}")
        return None


# ── §17602(a)(8) INITIAL NOTICE (exact copy, rendered before Confirm) ─────────
def initial_notice_html(account_settings_url: str = "?legal=billing") -> str:
    """The six-element auto-renewal disclosure block. Rendered ON the checkout
    page immediately before the Confirm button (not behind a link/tooltip)."""
    return (
        '<div style="background:rgba(255,255,255,.03);border:1px solid rgba(212,168,67,.25);'
        'border-radius:8px;padding:18px 20px;margin:18px 0;text-align:left;">'
        '<div style="font-family:Syne,sans-serif;font-size:14px;font-weight:800;'
        'color:#e2e8f0;margin-bottom:10px;">Your subscription</div>'
        '<ul style="margin:0;padding-left:18px;font-size:13px;color:#94a3b8;line-height:1.8;">'
        '<li>Your 7-day free trial starts today. You won\u2019t be charged during the trial.</li>'
        '<li>After the trial, QNTM Pro automatically renews at $29.00/month until you cancel.</li>'
        '<li>You\u2019ll be charged $29.00 on the same date each month.</li>'
        '<li>Cancel anytime in Account Settings \u2192 Subscription. Cancelling stops your next '
        'charge immediately; you keep Pro access until the end of your current period.</li>'
        f'<li>Manage or cancel your subscription: '
        f'<a href="{account_settings_url}" target="_self" style="color:#d4a843;">'
        'Account Settings \u2192 Subscription</a></li>'
        f'<li>Questions? {SUPPORT_EMAIL}</li>'
        '</ul></div>'
    )


# Plain-text version of the disclosure — stored verbatim in the consent log.
def initial_notice_text() -> str:
    return (
        "Your subscription\n"
        "- Your 7-day free trial starts today. You won't be charged during the trial.\n"
        "- After the trial, QNTM Pro automatically renews at $29.00/month until you cancel.\n"
        "- You'll be charged $29.00 on the same date each month.\n"
        "- Cancel anytime in Account Settings -> Subscription. Cancelling stops your next "
        "charge immediately; you keep Pro access until the end of your current period.\n"
        "- Manage or cancel your subscription: Account Settings -> Subscription\n"
        f"- Questions? {SUPPORT_EMAIL}"
    )


# ── §17602(a)(8) AFFIRMATIVE-CONSENT CHECKBOX LABEL (exact copy) ──────────────
CHECKBOX_TEXT = (
    "I understand my QNTM Pro subscription will automatically renew at $29/month "
    "after my 7-day free trial unless I cancel before the trial ends."
)


# ── §17602(a)(6) CONSENT ARTIFACT (append-only) ───────────────────────────────
def log_consent(user_id: str, plan: str = "pro", ip_address: str = None) -> bool:
    """Write the append-only consent record. Call on Confirm, after the user
    has checked the affirmative-consent box."""
    sb = _sb()
    if not sb or not user_id:
        return False
    try:
        sb.table("arl_consent_log").insert({
            "user_id":         user_id,
            "plan":            plan,
            "trial_terms":     TRIAL_TERMS,
            "renewal_price":   RENEWAL_PRICE,
            "disclosure_text": initial_notice_text(),
            "checkbox_text":   CHECKBOX_TEXT,
            "terms_version":   TERMS_VERSION,
            "ip_address":      ip_address,
        }).execute()
        log.info(f"ARL consent logged for {user_id}")
        return True
    except Exception as e:
        log.error(f"ARL consent log failed: {e}")
        return False


# ── EMAIL: stubbed sender + notice log (§17602 retainable-notice evidence) ────
def _send_email(to_email: str, subject: str, body: str) -> bool:
    """STUB. No provider wired yet. Logs intent and returns False (not delivered).
    Replace the body of this function with a real SendGrid/Resend call and return
    True on success; log_notice() records `delivered` from this return value."""
    log.info(f"[EMAIL STUB] to={to_email} subject={subject!r} (not sent — no provider)")
    # TODO: wire SendGrid. Example shape:
    #   import sendgrid; sg = sendgrid.SendGridAPIClient(os.getenv("SENDGRID_API_KEY"))
    #   ... return True on 2xx
    return False


def log_notice(user_id: str, notice_type: str, delivered: bool) -> bool:
    """Append-only record that a compliance notice was issued."""
    sb = _sb()
    if not sb or not user_id:
        return False
    try:
        sb.table("notices_sent").insert({
            "user_id":         user_id,
            "notice_type":     notice_type,
            "content_version": CONTENT_VERSION,
            "delivered":       bool(delivered),
        }).execute()
        return True
    except Exception as e:
        log.error(f"notices_sent log failed: {e}")
        return False


def _send_and_log(user_id: str, to_email: str, notice_type: str,
                  subject: str, body: str) -> bool:
    delivered = _send_email(to_email, subject, body)
    log_notice(user_id, notice_type, delivered)
    return delivered


# ── NOTICE TEMPLATES (exact copy) ─────────────────────────────────────────────
def acknowledgment_email() -> tuple:
    """1D — post-signup acknowledgment."""
    subject = "Your QNTM Pro free trial has started"
    body = (
        "Welcome to QNTM Pro.\n\n"
        "Your 7-day free trial has started. Here are your subscription terms:\n\n"
        "- After your 7-day free trial, QNTM Pro automatically renews at $29.00/month "
        "until you cancel.\n"
        "- You can cancel anytime in Account Settings -> Subscription. Cancelling stops "
        "your next charge immediately; you keep Pro access until the end of your current period.\n"
        "- To cancel: open QNTM, go to Account Settings -> Subscription -> Cancel.\n\n"
        f"Questions? {SUPPORT_EMAIL}"
    )
    return subject, body


def annual_reminder_email() -> tuple:
    """3A — §17602(h) annual reminder."""
    subject = "Your QNTM Pro subscription — annual reminder"
    body = (
        "Your QNTM Pro subscription — annual reminder\n\n"
        "- Service: QNTM Pro\n"
        "- Charge: $29.00 per month\n"
        "- To cancel: Account Settings -> Subscription -> Cancel. Cancelling stops your "
        "next charge; you keep access until the end of your current billing period."
    )
    return subject, body


def price_change_email(new_price: str, effective_date: str) -> tuple:
    """3B — §17602(g)(2). Send 7–30 days before the change (default ~14)."""
    subject = "Important: a change to your QNTM Pro price"
    body = (
        "We're letting you know about an upcoming change to your QNTM Pro subscription.\n\n"
        f"- New price: {new_price}\n"
        f"- Effective date: {effective_date}\n\n"
        "If you do nothing, your subscription continues at the new price on the effective "
        "date. To cancel before then: Account Settings -> Subscription -> Cancel. Cancelling "
        "stops your next charge; you keep access until the end of your current billing period."
    )
    return subject, body


def material_change_email(summary: str) -> tuple:
    """3C — §17602(g)(1) material change. Must include how to cancel."""
    subject = "An update to your QNTM Pro subscription"
    body = (
        "We're making a material change to your QNTM Pro subscription:\n\n"
        f"{summary}\n\n"
        "If you don't want to continue, you can cancel anytime: Account Settings -> "
        "Subscription -> Cancel. Cancelling stops your next charge; you keep access until "
        "the end of your current billing period."
    )
    return subject, body


def cancellation_confirmation_email(period_end: str) -> tuple:
    """2D — cancellation confirmation."""
    subject = "Your QNTM Pro subscription has been cancelled"
    body = (
        "Your QNTM Pro subscription has been cancelled.\n\n"
        f"- You will not be charged again.\n"
        f"- You keep Pro access until the end of your current paid period"
        + (f" ({period_end})" if period_end else "") + ".\n"
        "- After that, your account converts to Free and your data is preserved.\n\n"
        "Changed your mind? You can resubscribe anytime in Account Settings."
    )
    return subject, body


# ── PUBLIC SEND HELPERS (call from app / cron) ────────────────────────────────
def send_acknowledgment(user_id, email):
    s, b = acknowledgment_email();             return _send_and_log(user_id, email, "acknowledgment", s, b)

def send_cancellation_confirmation(user_id, email, period_end):
    s, b = cancellation_confirmation_email(period_end); return _send_and_log(user_id, email, "cancellation_confirmation", s, b)

def send_annual_reminder(user_id, email):
    s, b = annual_reminder_email();            return _send_and_log(user_id, email, "annual_reminder", s, b)

def send_price_change(user_id, email, new_price, effective_date):
    s, b = price_change_email(new_price, effective_date); return _send_and_log(user_id, email, "price_change", s, b)

def send_material_change(user_id, email, summary):
    s, b = material_change_email(summary);     return _send_and_log(user_id, email, "material_change", s, b)


# ── CRON: annual reminders (§17602(h)) ────────────────────────────────────────
def run_annual_reminders() -> dict:
    """Find paid subscribers whose last annual reminder is >= 365 days ago (or who
    never got one and signed up >= 365 days ago) and send the reminder.

    Run from a scheduled job, e.g.:  python arl.py annual_reminders
    Only targets accounts with billing_active=True — Founding $0 accounts have
    nothing to remind.
    """
    sb = _sb()
    if not sb:
        return {"error": "no supabase client"}
    sent = 0
    checked = 0
    try:
        # Pull paid subscribers. `notifications` JSON carries billing_active +
        # signup/period info in the current schema.
        users = sb.table("users").select("id,email,plan,notifications,created_at").execute()
        cutoff = datetime.utcnow() - timedelta(days=365)
        for u in (users.data or []):
            notif = u.get("notifications") or {}
            if not isinstance(notif, dict) or not notif.get("billing_active"):
                continue  # skip Founding/free — nothing to remind
            checked += 1
            # When was the last annual reminder?
            last = sb.table("notices_sent").select("created_at") \
                .eq("user_id", u["id"]).eq("notice_type", "annual_reminder") \
                .order("created_at", desc=True).limit(1).execute()
            if last.data:
                last_dt = datetime.fromisoformat(str(last.data[0]["created_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
                if last_dt > cutoff:
                    continue  # reminded within the last year
            else:
                # Never reminded — only due if signed up >= 365 days ago
                created = u.get("created_at")
                if created:
                    created_dt = datetime.fromisoformat(str(created).replace("Z", "+00:00")).replace(tzinfo=None)
                    if created_dt > cutoff:
                        continue
            if u.get("email"):
                send_annual_reminder(u["id"], u["email"])
                sent += 1
    except Exception as e:
        log.error(f"annual reminders failed: {e}")
        return {"error": str(e), "sent": sent, "checked": checked}
    log.info(f"Annual reminders: checked {checked} paid subs, sent {sent}")
    return {"sent": sent, "checked": checked}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "annual_reminders"
    if cmd == "annual_reminders":
        print(run_annual_reminders())
    else:
        print(f"Unknown command: {cmd}")
