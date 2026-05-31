"""
QNTM — Stripe billing (Checkout + polling).
============================================
Hosted Stripe Checkout for the 7-day-trial → $29/mo Pro subscription.
No webhook server (Streamlit can't receive POSTs); subscription state is
POLLED from Stripe on app load and synced into Supabase via db.set_stripe_billing.

TEST MODE: uses whatever keys are in secrets. Use sk_test_... + a test
price ID first; swap to live keys only after the full trial→charge→cancel
cycle is verified. Card 4242 4242 4242 4242, any future expiry, any CVC.

FLAG FOR ATTORNEY REVIEW: the trial terms, price, and cancellation behavior
here must match the ARL disclosure (arl.py) exactly before taking live payments.
"""

import os
import logging

log = logging.getLogger("qntm.stripe")

TRIAL_DAYS = 7


def _secret(key: str, default: str = "") -> str:
    try:
        import streamlit as st
        return st.secrets.get(key) or os.getenv(key, default)
    except Exception:
        return os.getenv(key, default)


def _client():
    """Configured stripe module, or None if not set up."""
    sk = _secret("STRIPE_SECRET_KEY")
    if not sk:
        log.warning("STRIPE_SECRET_KEY not set")
        return None
    try:
        import stripe
        stripe.api_key = sk
        return stripe
    except Exception as e:
        log.error(f"stripe import failed: {e}")
        return None


def is_test_mode() -> bool:
    return _secret("STRIPE_SECRET_KEY", "").startswith("sk_test_")


def billing_configured() -> bool:
    return bool(_secret("STRIPE_SECRET_KEY") and _secret("STRIPE_PRICE_ID_PRO"))


# ── CHECKOUT ──────────────────────────────────────────────────────────────────
_last_error = None  # last failure reason, for surfacing in the UI during testing


def last_error() -> str:
    return _last_error or ""


def create_checkout_url(user_id: str, user_email: str, base_url: str,
                        existing_customer_id: str = None) -> str | None:
    """Create a subscription Checkout Session with a 7-day trial and return the
    hosted URL to redirect the user to. Card is collected but NOT charged during
    the trial; Stripe auto-charges $29 when the trial ends.

    base_url: e.g. "https://qntmmvp.streamlit.app"
    """
    global _last_error
    _last_error = None
    stripe = _client()
    price_id = _secret("STRIPE_PRICE_ID_PRO")
    if not stripe:
        _last_error = "Stripe library not available or STRIPE_SECRET_KEY missing."
        return None
    if not price_id:
        _last_error = "STRIPE_PRICE_ID_PRO is not set in secrets."
        return None
    try:
        kwargs = dict(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            subscription_data={"trial_period_days": TRIAL_DAYS},
            client_reference_id=user_id,
            success_url=f"{base_url}/?checkout=success&uid={user_id}&plan=pro&ck=1&_n=screener",
            cancel_url=f"{base_url}/?checkout=cancel&uid={user_id}&plan=free&ck=1&_n=account",
            allow_promotion_codes=True,
        )
        if existing_customer_id:
            kwargs["customer"] = existing_customer_id
        else:
            kwargs["customer_email"] = user_email
        session = stripe.checkout.Session.create(**kwargs)
        return session.url
    except Exception as e:
        _last_error = str(e)
        log.error(f"checkout session create failed: {e}")
        return None


def finalize_checkout(user_id: str, user_email: str = None) -> dict:
    """Called on return from Checkout (?checkout=success). Finds the user's
    subscription and returns its state. No webhooks, so we look it up directly.

    Tries, in order: (1) recent checkout session matching client_reference_id
    or customer email, (2) newest subscription on the matching customer.
    Returns {ok, status, customer_id, subscription_id, trial_end, current_period_end}
    or {ok:False, error}.
    """
    global _last_error
    _last_error = None
    stripe = _client()
    if not stripe:
        _last_error = "stripe client unavailable"
        return {"ok": False, "error": _last_error}
    try:
        sessions = stripe.checkout.Session.list(limit=20)
        match = None
        for s in sessions.data:
            if s.get("subscription") and (
                s.get("client_reference_id") == user_id
                or (user_email and s.get("customer_email") == user_email)
                or (user_email and (s.get("customer_details") or {}).get("email") == user_email)
            ):
                match = s
                break
        if match:
            sub_id = match["subscription"]
            cust_id = match.get("customer")
            sub = stripe.Subscription.retrieve(sub_id)
            return {
                "ok": True,
                "status": sub.get("status"),
                "customer_id": cust_id,
                "subscription_id": sub_id,
                "trial_end": sub.get("trial_end"),
                "current_period_end": sub.get("current_period_end"),
            }
        if user_email:
            custs = stripe.Customer.list(email=user_email, limit=1)
            if custs.data:
                cust_id = custs.data[0]["id"]
                subs = stripe.Subscription.list(customer=cust_id, limit=1, status="all")
                if subs.data:
                    sub = subs.data[0]
                    return {
                        "ok": True,
                        "status": sub.get("status"),
                        "customer_id": cust_id,
                        "subscription_id": sub.get("id"),
                        "trial_end": sub.get("trial_end"),
                        "current_period_end": sub.get("current_period_end"),
                    }
        _last_error = "no matching checkout session or subscription found yet"
        return {"ok": False, "error": _last_error}
    except Exception as e:
        _last_error = str(e)
        log.error(f"finalize_checkout failed: {e}")
        return {"ok": False, "error": _last_error}


# ── POLLING (no webhooks) ─────────────────────────────────────────────────────
def poll_subscription_status(subscription_id: str) -> dict:
    """Read live subscription status from Stripe. Call on app load for users
    with a stored subscription_id to keep plan/billing_active in sync.

    Stripe statuses: trialing, active, past_due, canceled, unpaid, incomplete.
    'trialing' and 'active' → Pro access. Others → revoke.
    Returns {ok, status, current_period_end, cancel_at_period_end}.
    """
    stripe = _client()
    if not stripe or not subscription_id:
        return {"ok": False}
    try:
        sub = stripe.Subscription.retrieve(subscription_id)
        return {
            "ok": True,
            "status": sub.get("status"),
            "current_period_end": sub.get("current_period_end"),
            "cancel_at_period_end": sub.get("cancel_at_period_end", False),
            "trial_end": sub.get("trial_end"),
        }
    except Exception as e:
        log.error(f"poll_subscription_status failed: {e}")
        return {"ok": False}


def status_grants_access(status: str) -> bool:
    return status in ("trialing", "active")


# ── CANCEL ────────────────────────────────────────────────────────────────────
def cancel_subscription(subscription_id: str) -> dict:
    """Cancel at period end. During the trial, period end == trial end, so no
    charge ever fires (the user's "cancel free in the first 7 days"). After the
    trial, this stops the next renewal while access continues to period end —
    matching the ARL cancellation copy.

    Returns {ok, current_period_end, status}.
    """
    stripe = _client()
    if not stripe or not subscription_id:
        return {"ok": False}
    try:
        sub = stripe.Subscription.modify(subscription_id, cancel_at_period_end=True)
        return {
            "ok": True,
            "current_period_end": sub.get("current_period_end"),
            "status": sub.get("status"),
        }
    except Exception as e:
        log.error(f"cancel_subscription failed: {e}")
        return {"ok": False}


def reactivate_subscription(subscription_id: str) -> dict:
    """Undo a scheduled cancellation (clear cancel_at_period_end)."""
    stripe = _client()
    if not stripe or not subscription_id:
        return {"ok": False}
    try:
        sub = stripe.Subscription.modify(subscription_id, cancel_at_period_end=False)
        return {"ok": True, "status": sub.get("status")}
    except Exception as e:
        log.error(f"reactivate_subscription failed: {e}")
        return {"ok": False}
