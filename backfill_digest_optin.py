"""
QNTM — one-time weekly-digest opt-IN backfill
=============================================
Flips notifications.email = True for EVERY existing user, so the weekly digest
defaults ON for the current base (matching the new opt-OUT default for new
signups in db.register_user).

MERGE-SAFE — this is the whole point of the script:
  The `notifications` JSON blob is shared storage. Besides the three notification
  prefs (email / signals / alerts) it also carries Stripe + billing + cancellation
  state (stripe_customer_id, subscription_id, cancel_at, founding flags, …) written
  by set_stripe_billing / schedule_cancellation / etc. A blanket
  update({"notifications": {"email": True, ...}}) would WIPE all of that. So we
  read each user's existing blob, set ONLY email=True, and write the merged dict
  back. Every other key is preserved byte-for-byte.

Only `email` is touched. `signals` / `alerts` / `low_alert_email` / `alert_email`
/ `alert_sms` and all billing keys are left exactly as they are.

Who actually RECEIVES the digest after this runs is decided at SEND time by
weekly_digest.recipients(): email_verified AND notifications.email. The digest is
a FREE feature, so every plan is eligible — free and paid alike — and everyone can
opt out in Account -> Notifications. The breakdown below reports the real
post-backfill eligibility (verified & email-on) so you can see the adoption delta.

Usage (Render shell — stage secrets first:
       cd ~/project/src && mkdir -p .streamlit && cp /etc/secrets/secrets.toml .streamlit/secrets.toml):
    python backfill_digest_optin.py --dry-run   # report blast radius, write nothing
    python backfill_digest_optin.py             # actually flip email=True for all

Idempotent — safe to run more than once. Already-on users are skipped (no write).
"""
import sys
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("qntm.digest_backfill")

PAGE = 1000


def _all_users(sb):
    rows, off = [], 0
    while True:
        chunk = (sb.table("users")
                 .select("id,notifications,email_verified")
                 .range(off, off + PAGE - 1).execute().data or [])
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        off += PAGE
    return rows


def _as_dict(notifs):
    """notifications may come back as a dict (jsonb) or a JSON string."""
    if isinstance(notifs, dict):
        return dict(notifs)
    if isinstance(notifs, str):
        try:
            v = json.loads(notifs)
            return dict(v) if isinstance(v, dict) else {}
        except Exception:
            return {}
    return {}


def run(dry_run=False):
    try:
        from data_refresh import _get_supabase
    except Exception as e:
        log.error("cannot import _get_supabase: %s", e)
        return
    sb = _get_supabase()
    if not sb:
        log.error("no supabase service client — stage secrets first "
                  "(mkdir -p .streamlit && cp /etc/secrets/secrets.toml .streamlit/secrets.toml).")
        return

    users = _all_users(sb)
    log.info("users total: %d", len(users))
    if not users:
        log.warning("no users returned — check the SERVICE key (anon key + RLS reads 0 rows).")
        return

    to_flip = []          # (id, merged_notifications)
    already_on = 0
    for u in users:
        notifs = _as_dict(u.get("notifications"))
        if notifs.get("email") is True:
            already_on += 1
            continue
        notifs["email"] = True               # set ONLY this key; preserve the rest
        to_flip.append((u["id"], notifs))

    # ── Eligibility math (who the digest will actually email AFTER this) ─────────
    # Mirrors weekly_digest.recipients(): verified AND email-on. Any plan.
    def _verified(u):  return bool(u.get("email_verified"))
    flip_ids = {i for i, _ in to_flip}
    def _email_on_after(u):
        return u.get("id") in flip_ids or _as_dict(u.get("notifications")).get("email") is True

    verified = sum(1 for u in users if _verified(u))
    eligible_before = sum(1 for u in users
                          if _verified(u)
                          and _as_dict(u.get("notifications")).get("email") is True)
    eligible_after  = sum(1 for u in users
                          if _verified(u) and _email_on_after(u))

    log.info("notifications.email already True: %d", already_on)
    log.info("will flip to True:                %d", len(to_flip))
    log.info("— base —  email_verified: %d / %d", verified, len(users))
    log.info("digest-eligible (verified & email-on)  BEFORE: %d  ->  AFTER: %d",
             eligible_before, eligible_after)
    _unverified_flips = sum(1 for u in users
                            if u.get("id") in flip_ids and not _verified(u))
    if _unverified_flips:
        log.info("note: %d of the flips are UNVERIFIED users — opted in but not "
                 "emailed until they verify their address.", _unverified_flips)

    if dry_run:
        log.info("[DRY RUN] nothing written. Re-run without --dry-run to flip "
                 "email=True on %d user(s).", len(to_flip))
        return
    if not to_flip:
        log.info("nothing to do — every user already has the weekly digest on.")
        return

    flipped, failed = 0, 0
    for uid, merged in to_flip:
        try:
            # Service key bypasses RLS; .data empty => the row didn't update.
            resp = (sb.table("users")
                    .update({"notifications": merged}).eq("id", uid).execute())
            if getattr(resp, "data", None):
                flipped += 1
            else:
                failed += 1
                log.warning("0 rows updated for user %s (RLS / missing row?)", uid)
        except Exception as e:
            failed += 1
            log.error("update failed for user %s: %s", uid, e)

    log.info("DONE — flipped %d user(s) to weekly-digest ON%s.",
             flipped, (f", {failed} FAILED" if failed else ""))
    log.info("digest-eligible recipients now: %d (paid & verified & email-on).",
             eligible_after)


if __name__ == "__main__":
    run(dry_run=("--dry-run" in sys.argv))
