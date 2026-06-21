"""
QNTM — "What's New" changelog popup.
====================================
An in-code changelog (edit CHANGELOG and deploy — no DB write needed to publish
an entry) plus a per-user high-water mark stored in the user's `notifications`
JSON blob via db.update_preferences, so NO schema migration is required. Each
user sees each entry once: on login we show entries newer than their stored
mark, then advance the mark.

TO ANNOUNCE A NEW FEATURE
    Prepend one dict to CHANGELOG with a NEW, unique, stable `id` (a date-slug
    works well). Newest entry MUST be first. That's the whole workflow — commit
    and deploy; the popup shows it to everyone on their next visit, once.

Storage note: update_preferences REPLACES the whole notifications blob with what
you pass, so we always read-modify-write the full dict to avoid clobbering other
keys (billing_active, low_alert_email, stripe_* …).
"""

import json
import logging
import streamlit as st

log = logging.getLogger("qntm.changelog")

# ── THE CHANGELOG ─────────────────────────────────────────────────────────────
# Newest first. `id` is the per-user seen key (must be unique + stable).
# `tag` ∈ {"New","Improved","Fixed"} sets the chip colour. `items` are bullets.
CHANGELOG = [
    {
        "id":    "2026-06-21-cap-categories",
        "date":  "June 21, 2026",
        "tag":   "New",
        "title": "Market-cap category on every card",
        "items": [
            "Every stock now shows a Large / Mid / Small cap badge next to its ticker.",
            "Hidden Gems are now strictly mid- and small-cap — large names no longer slip in.",
        ],
    },
]

# On a user's FIRST-ever view (no mark yet) cap how many recent entries we show,
# so existing users get a bounded "recent" list rather than the whole history.
FIRST_VIEW_MAX = 4


# ── per-user seen mark (lives in the notifications JSON blob) ──────────────────
def _notifs(user: dict) -> dict:
    n = (user or {}).get("notifications") or {}
    if isinstance(n, str):
        try:
            n = json.loads(n)
        except Exception:
            n = {}
    return n if isinstance(n, dict) else {}


def latest_id() -> str:
    return CHANGELOG[0]["id"] if CHANGELOG else ""


def unseen_entries(user: dict) -> list:
    """Entries this user hasn't acknowledged yet, newest first."""
    if not CHANGELOG:
        return []
    seen = _notifs(user).get("changelog_seen")
    if not seen:
        return CHANGELOG[:FIRST_VIEW_MAX]
    out = []
    for e in CHANGELOG:
        if e["id"] == seen:
            break
        out.append(e)
    return out


def _mark_seen(user_id: str, entry_id: str, user: dict) -> None:
    """Advance the per-user mark, preserving every other key in the blob."""
    from db import update_preferences
    notifs = dict(_notifs(user))
    notifs["changelog_seen"] = entry_id
    try:
        update_preferences(user_id, {"notifications": notifs})
        if st.session_state.get("user"):       # keep this session in sync
            st.session_state.user["notifications"] = notifs
    except Exception as e:
        log.warning(f"could not persist changelog_seen: {e}")


# ── rendering ─────────────────────────────────────────────────────────────────
_TAG_COLORS = {
    "New":      ("#34d399", "rgba(52,211,153,.10)", "rgba(52,211,153,.30)"),
    "Improved": ("#d4a843", "rgba(212,168,67,.10)", "rgba(212,168,67,.30)"),
    "Fixed":    ("#8896ac", "rgba(136,150,172,.10)", "rgba(136,150,172,.28)"),
}


def _entry_html(e: dict) -> str:
    c, bg, bd = _TAG_COLORS.get(e.get("tag", "New"), _TAG_COLORS["New"])
    items = "".join(
        f'<li style="margin:5px 0;color:#b3bed0;font-size:14px;line-height:1.55;">{it}</li>'
        for it in e.get("items", [])
    )
    return (
        '<div style="padding:14px 0;border-top:1px solid rgba(255,255,255,.06);">'
        '<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">'
        f'<span style="font-family:DM Mono,monospace;font-size:11px;font-weight:700;'
        f'letter-spacing:.08em;text-transform:uppercase;color:{c};background:{bg};'
        f'border:1px solid {bd};border-radius:5px;padding:1px 8px;">{e.get("tag","New")}</span>'
        f'<span style="font-size:12px;color:#8896ac;">{e.get("date","")}</span>'
        '</div>'
        f'<div style="font-family:Syne,sans-serif;font-size:16px;font-weight:800;'
        f'color:#e2e8f0;margin-bottom:4px;">{e.get("title","")}</div>'
        f'<ul style="margin:0;padding-left:18px;">{items}</ul>'
        '</div>'
    )


@st.dialog("✨ What's New in QNTM")
def _open_dialog(entries: list) -> None:
    body = "".join(_entry_html(e) for e in entries)
    st.markdown(
        '<div style="font-size:13px;color:#8896ac;line-height:1.5;margin:-6px 0 2px;">'
        "Here\u2019s what\u2019s shipped since you were last here.</div>"
        f"{body}",
        unsafe_allow_html=True,
    )
    if st.button("Got it", use_container_width=True, type="primary"):
        st.rerun()   # closing rerun — the platform shell won't reopen it this session


# ── entry point (called once per session from the platform shell) ─────────────
def maybe_show_whats_new() -> None:
    """No-op for anon/demo users or when nothing is new; otherwise advance the
    seen mark (optimistically, so an X-close still counts) and open the modal."""
    user = st.session_state.get("user") or {}
    uid = user.get("id")
    if not uid or uid == "demo":
        return
    entries = unseen_entries(user)
    if not entries:
        return
    _mark_seen(uid, entries[0]["id"], user)
    _open_dialog(entries)
