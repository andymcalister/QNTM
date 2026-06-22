"""
QNTM — analytics (PostHog Python SDK + Supabase mirror)
================================================================================
Server-side event capture for a Streamlit app.

We deliberately do NOT use PostHog's JS autocapture: Streamlit renders inside
sandboxed iframes, so browser-side pageview/click capture is unreliable, and the
app is migrating off st.components.v1.html anyway. Instead we capture the named
events server-side via the PostHog Python SDK at the point each one happens, and
mirror a lightweight copy into Supabase (qntm_events) so the internal dashboard
works even when the PostHog API is unreachable.

Hard rules:
- Analytics NEVER breaks the app. Every external call is wrapped; failures are
  swallowed at debug level and the app continues.
- No analytics surface for normal users — the dashboard is admin-gated.

Public API:
    init_session()                                  -> call once at app entry
    capture(event, user=None, props=None, distinct_id=None)
    is_admin(user_or_email=None)                     -> bool
    render_analytics_dashboard()                     -> admin-only dashboard

Config (env var OR st.secrets):
    POSTHOG_API_KEY
    POSTHOG_HOST          (default https://us.i.posthog.com)
    ADMIN_EMAILS          (comma-separated; the dashboard is visible only to these)
"""
import os, json, uuid, logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger("qntm.analytics")

EVENTS_TABLE = "qntm_events"
UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign")

# Short shareable ref codes -> full UTM sets. Lets you share a clean
# qntm.live/?ref=x instead of a long ?utm_source=...&utm_medium=... string, and
# change a campaign's meaning in one place. Add new codes here as needed.
REF_CODES = {
    "x":        {"utm_source": "x", "utm_medium": "profile", "utm_campaign": "organic"},
    "x-post":   {"utm_source": "x", "utm_medium": "post",    "utm_campaign": "organic"},
}


# ── config ──────────────────────────────────────────────────────────────────
def _cfg(key, default=""):
    v = os.getenv(key, "")
    if v:
        return v
    try:
        import streamlit as st
        return st.secrets.get(key, default)
    except Exception:
        return default


def _admin_emails():
    raw = _cfg("ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.replace(";", ",").split(",") if e.strip()}


# ── PostHog client (lazy, cached, optional) ──────────────────────────────────
_ph = None
_ph_init = False


def _posthog():
    global _ph, _ph_init
    if _ph_init:
        return _ph
    _ph_init = True
    try:
        key = _cfg("POSTHOG_API_KEY", "")
        if not key:
            _ph = None
            return None
        from posthog import Posthog
        _ph = Posthog(
            project_api_key=key,
            host=_cfg("POSTHOG_HOST", "https://us.i.posthog.com"),
        )
    except Exception as e:
        log.debug(f"PostHog init skipped: {e}")
        _ph = None
    return _ph


# ── Supabase (reuse the app's canonical client) ──────────────────────────────
def _sb():
    try:
        from data_refresh import _get_supabase
        return _get_supabase()
    except Exception:
        return None


# ── identity + UTM ────────────────────────────────────────────────────────────
def _user_email(user):
    if not user:
        return None
    if isinstance(user, str):
        return user.strip() or None
    try:
        return user.get("email")
    except Exception:
        return None


def _session_user():
    try:
        import streamlit as st
        u = st.session_state.get("user") or st.session_state.get("u")
        return u if isinstance(u, dict) else None
    except Exception:
        return None


def anon_id():
    """Stable per-session anonymous id, so unauthenticated visits are still a
    single 'visitor' across events in that session."""
    try:
        import streamlit as st
        aid = st.session_state.get("_anon_id")
        if not aid:
            aid = "anon_" + uuid.uuid4().hex[:16]
            st.session_state["_anon_id"] = aid
        return aid
    except Exception:
        return "anon_unknown"


def _distinct_id(user=None, distinct_id=None):
    if distinct_id:
        return distinct_id
    email = _user_email(user) or _user_email(_session_user())
    return email or anon_id()


def _utm_from_session():
    try:
        import streamlit as st
        d = {k: st.session_state.get(f"_{k}", "") for k in UTM_KEYS}
        d["referrer"] = st.session_state.get("_referrer", "")
        return d
    except Exception:
        return {}


def init_session():
    """Call once near the top of the app (after set_page_config). Reads UTM +
    referrer from the URL into session_state so later events can attach them, and
    fires site_visit exactly once per session."""
    try:
        import streamlit as st
    except Exception:
        return
    try:
        qp = st.query_params
        # Expand a short ?ref=<code> into UTMs first; explicit utm_* params below
        # override it, so a fully-specified link always wins.
        ref = qp.get("ref")
        if ref and ref in REF_CODES:
            for k, v in REF_CODES[ref].items():
                if not st.session_state.get(f"_{k}"):
                    st.session_state[f"_{k}"] = v
        for k in UTM_KEYS:
            val = qp.get(k)
            if val:
                st.session_state[f"_{k}"] = val
        ref = qp.get("referrer")
        if ref and not st.session_state.get("_referrer"):
            st.session_state["_referrer"] = ref
        if not st.session_state.get("_site_visit_sent"):
            st.session_state["_site_visit_sent"] = True
            capture("site_visit")
    except Exception as e:
        log.debug(f"init_session skipped: {e}")


# ── capture ──────────────────────────────────────────────────────────────────
def capture(event, user=None, props=None, distinct_id=None):
    """Fire an event to PostHog and mirror it into Supabase. Never raises."""
    did = _distinct_id(user, distinct_id)
    utm = _utm_from_session()
    properties = dict(props or {})
    properties.update({k: v for k, v in utm.items() if v})

    # PostHog — best effort, non-blocking
    try:
        ph = _posthog()
        if ph:
            ph.capture(distinct_id=did, event=event, properties=properties)
    except Exception as e:
        log.debug(f"posthog capture failed ({event}): {e}")

    # Supabase mirror — best effort
    try:
        sb = _sb()
        if sb:
            sb.table(EVENTS_TABLE).insert({
                "event":        event,
                "distinct_id":  did,
                "utm_source":   utm.get("utm_source") or None,
                "utm_medium":   utm.get("utm_medium") or None,
                "utm_campaign": utm.get("utm_campaign") or None,
                "referrer":     utm.get("referrer") or None,
                "properties":   json.dumps(properties) if properties else None,
            }).execute()
    except Exception as e:
        log.debug(f"qntm_events mirror failed ({event}): {e}")


# ── admin gate ─────────────────────────────────────────────────────────────────
def is_admin(user_or_email=None):
    email = _user_email(user_or_email) or _user_email(_session_user())
    if not email:
        return False
    return email.lower() in _admin_emails()


# ── dashboard (admin only) ──────────────────────────────────────────────────────
def _parse_ts(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def render_analytics_dashboard():
    """Admin-only internal dashboard. Reads core metrics straight from the
    Supabase qntm_events mirror — no PostHog API call required."""
    import streamlit as st

    if not is_admin():
        st.error("Not authorized.")
        return

    st.markdown("## 📊 Analytics")
    sb = _sb()
    if not sb:
        st.warning("No database connection — analytics unavailable.")
        return

    now = datetime.now(timezone.utc)
    since_30 = (now - timedelta(days=30)).isoformat()

    # Single paginated pull of the last 30 days; windows computed in Python.
    rows, off = [], 0
    try:
        while True:
            b = (sb.table(EVENTS_TABLE)
                 .select("event,distinct_id,utm_source,referrer,created_at")
                 .gte("created_at", since_30)
                 .range(off, off + 999).execute().data) or []
            rows.extend(b)
            if len(b) < 1000:
                break
            off += 1000
    except Exception as e:
        st.error(f"Could not read qntm_events: {e}")
        st.caption("If this is a permissions error, the app needs the Supabase "
                   "service key (SUPABASE_SERVICE_KEY) to read analytics.")
        return

    if not rows:
        st.info("No events recorded yet. Once capture() is wired in, metrics "
                "appear here within minutes.")
        return

    today = now.date()
    d7 = now - timedelta(days=7)

    def _in7(r):
        t = _parse_ts(r.get("created_at"))
        return t is not None and t >= d7

    def _today(r):
        t = _parse_ts(r.get("created_at"))
        return t is not None and t.date() == today

    visits = [r for r in rows if r.get("event") == "site_visit"]
    signups = [r for r in rows if r.get("event") == "signup_completed"]

    visitors_today = len({r["distinct_id"] for r in visits if _today(r)})
    visitors_7d    = len({r["distinct_id"] for r in visits if _in7(r)})
    signups_today  = sum(1 for r in signups if _today(r))
    signups_7d     = sum(1 for r in signups if _in7(r))
    conv_7d        = (signups_7d / visitors_7d * 100.0) if visitors_7d else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Visitors today", visitors_today)
    c2.metric("Visitors (7d)", visitors_7d)
    c3.metric("Signups today", signups_today)
    c4.metric("Signups (7d)", signups_7d)
    st.metric("Visitor → signup (7d)", f"{conv_7d:.1f}%")

    st.divider()

    def _count_7d(event):
        return sum(1 for r in rows if r.get("event") == event and _in7(r))

    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Hidden Gems views (7d)", _count_7d("hidden_gems_viewed"))
    e2.metric("Simulator views (7d)",   _count_7d("simulator_viewed"))
    e3.metric("Watchlist adds (7d)",    _count_7d("watchlist_added"))
    e4.metric("Founder claims (7d)",    _count_7d("founder_membership_claimed"))

    st.divider()
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("#### Top referral sources (7d)")
        src = {}
        for r in rows:
            if not _in7(r):
                continue
            s = (r.get("utm_source") or r.get("referrer") or "direct")
            src[s] = src.get(s, 0) + 1
        ranked = sorted(src.items(), key=lambda x: x[1], reverse=True)[:8]
        if ranked:
            st.dataframe({"source": [s for s, _ in ranked],
                          "events": [c for _, c in ranked]},
                         use_container_width=True, hide_index=True)
        else:
            st.caption("No data yet.")

    with col_b:
        st.markdown("#### Top events (7d)")
        ev = {}
        for r in rows:
            if not _in7(r):
                continue
            ev[r["event"]] = ev.get(r["event"], 0) + 1
        ranked = sorted(ev.items(), key=lambda x: x[1], reverse=True)[:10]
        if ranked:
            st.dataframe({"event": [e for e, _ in ranked],
                          "count": [c for _, c in ranked]},
                         use_container_width=True, hide_index=True)
        else:
            st.caption("No data yet.")

    st.caption("Source: Supabase qntm_events mirror (last 30 days). "
               "Full funnels and retention live in PostHog.")
