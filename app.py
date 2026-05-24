"""
QNTM — Conviction Factor Model Platform
Futuristic dark design · Financial green · Full platform
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, date
import sys, os, contextlib
sys.path.insert(0, os.path.dirname(__file__))

st.set_page_config(
    page_title="QNTM — Conviction Factor Model",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── DEV ENVIRONMENT BANNER ────────────────────────────────────────────────────
import os
if os.getenv("ENVIRONMENT") == "dev":
    st.markdown("""
    <div style="background:#7c3aed;color:#fff;text-align:center;padding:6px 0;
         font-family:'DM Mono',monospace;font-size:12px;letter-spacing:.1em;
         position:sticky;top:0;z-index:9999;">
      ⚠ DEV ENVIRONMENT — changes here do not affect production
    </div>
    """, unsafe_allow_html=True)

from db import (register_user, login_user, get_holdings, upsert_holding,
                delete_holding, get_notifications, create_notification,
                mark_notifications_read, generate_totp_secret, verify_totp,
                enable_mfa, disable_mfa, get_user_mfa, update_preferences,
                upgrade_plan, plan_limit, PLAN_LIMITS,
                check_and_notify_signal_changes, save_signal_snapshot,
                get_signal_snapshot, get_unread_count, get_user_by_id)
from model_engine import (run_full_scan, detect_hidden_gems, BACKTEST_DATA,
                           ENTRY_THRESHOLD, EXIT_THRESHOLD, SECTORS,
                           fetch_macro_overlay, apply_macro_overlay)

# ── SIGNED JWT HELPERS ────────────────────────────────────────────────────────
import hmac, hashlib, base64, json as _json, time as _time

def _jwt_secret() -> str:
    """Use ENCRYPTION_KEY as JWT signing secret, fall back to a fixed dev key."""
    try:
        import streamlit as _st
        return _st.secrets.get("ENCRYPTION_KEY", "dev-secret-qntm-2025")
    except Exception:
        return "dev-secret-qntm-2025"

def _sign_token(uid: str, plan: str, days: int = 30) -> str:
    """For now return plain uid — JWT signing to be added once auth is stable."""
    return uid

def _verify_token(token: str):
    """For now treat token as plain uid."""
    return token, None

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Mono:wght@400;500&family=Outfit:wght@300;400;500;600&display=swap');

*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}

/* ── Kill all horizontal overflow everywhere ── */
html, body {
  overflow-x: hidden !important;
  max-width: 100vw !important;
}

/* ── Dark background — covers all Streamlit containers, old and new selectors */
html, body, [class*="css"],
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
[data-testid="stMainBlockContainer"],
[data-testid="stAppViewBlockContainer"],
section[data-testid="stMain"] > div,
.main, .stApp {
  font-family: 'Outfit', sans-serif !important;
  background: #0a0b14 !important;
  color: #e2e8f0 !important;
  overflow-x: hidden !important;
  max-width: 100% !important;
}
.main .block-container,
[data-testid="stMainBlockContainer"] {
  padding: 0 !important;
  max-width: 100% !important;
  width: 100% !important;
  background: #0a0b14 !important;
  overflow-x: hidden !important;
}
/* Clamp Streamlit column containers */
[data-testid="stHorizontalBlock"] {
  max-width: 100% !important;
  width: 100% !important;
  overflow-x: hidden !important;
  flex-wrap: wrap !important;
}
[data-testid="stColumn"] {
  min-width: 0 !important;
  overflow-x: hidden !important;
}

/* Hide all Streamlit chrome */
#MainMenu, footer, header,
[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"] { display: none !important; }
[data-testid="stSidebar"]        { display: none !important; }
[data-testid="collapsedControl"] { display: none !important; }

::-webkit-scrollbar{width:3px;}
::-webkit-scrollbar-track{background:#0a0b14;}
::-webkit-scrollbar-thumb{background:#00ff87;border-radius:2px;}

/* ── Mobile responsive: watchlist + model portfolio ── */
@media (max-width: 520px) {
  /* Watchlist: hide desktop table, show cards */
  .wl-table-header { display: none !important; }
  .wl-row           { display: none !important; }
  .wl-card          { display: block !important; }
  /* Model portfolio: hide desktop rows, show cards */
  .mp-row  { display: none !important; }
  .mp-card { display: block !important; }
}

/* Animations */
@keyframes fadeUp{from{opacity:0;transform:translateY(24px)}to{opacity:1;transform:translateY(0)}}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.3}}
@keyframes glow{0%,100%{box-shadow:0 0 4px rgba(0,255,135,.1)}50%{box-shadow:0 0 12px rgba(0,255,135,.2)}}
@keyframes scanLine{0%{top:-2px}100%{top:100%}}
@keyframes ticker{0%{transform:translateX(0)}100%{transform:translateX(-50%)}}
@keyframes borderAnim{0%,100%{border-color:rgba(0,255,135,.2)}50%{border-color:rgba(0,255,135,.6)}}
@keyframes countUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}

/* Typography */
.syne{font-family:'Syne',sans-serif;}
.mono{font-family:'DM Mono',monospace;}

/* ── Platform buttons — dark glass with green accent ── */
@keyframes btn-shimmer {
  0%   { background-position: -200% center; }
  100% { background-position:  200% center; }
}
.stButton > button {
  background: rgba(0,255,135,.06) !important;
  color: #00ff87 !important;
  border: 1px solid rgba(0,255,135,.22) !important;
  border-radius: 6px !important;
  font-family: 'Syne', sans-serif !important;
  font-weight: 700 !important;
  font-size: 12px !important;
  letter-spacing: .06em !important;
  padding: 10px 12px !important;
  text-transform: uppercase !important;
  cursor: pointer !important;
  position: relative !important;
  overflow: hidden !important;
  white-space: nowrap !important;
  text-overflow: ellipsis !important;
  min-height: 42px !important;
  height: 42px !important;
  transition: border-color .18s, background .18s, transform .12s !important;
  box-shadow: none !important;
}
.stButton > button::before {
  content: '' !important;
  position: absolute !important;
  inset: 0 !important;
  background: linear-gradient(105deg,
    transparent 40%,
    rgba(0,255,135,.10) 50%,
    transparent 60%) !important;
  background-size: 200% 100% !important;
  opacity: 0 !important;
  transition: opacity .2s !important;
}
.stButton > button:hover {
  border-color: rgba(0,255,135,.5) !important;
  background: rgba(0,255,135,.1) !important;
  box-shadow: none !important;
  transform: translateY(-1px) !important;
}
.stButton > button:hover::before { opacity: 1 !important; }
.stButton > button:active { transform: translateY(0) !important; }

/* Ghost button variant */
div[data-ghost="1"] .stButton > button {
  background: transparent !important;
  color: rgba(0,255,135,.7) !important;
  border: 1px solid rgba(0,255,135,.2) !important;
  box-shadow: none !important;
}
div[data-ghost="1"] .stButton > button:hover {
  background: rgba(0,255,135,.05) !important;
  border-color: rgba(0,255,135,.4) !important;
  box-shadow: 0 0 12px rgba(0,255,135,.1) !important;
  transform: none !important;
}

/* ── Inputs — cover all Streamlit input selectors old + new ── */
.stTextInput input,
.stNumberInput input,
.stDateInput input,
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-baseweb="input"] input,
[data-baseweb="base-input"] input {
  background: #0d1117 !important;
  border: 1px solid rgba(255,255,255,.18) !important;
  border-radius: 4px !important;
  color: #e2e8f0 !important;
  font-family: 'Outfit', sans-serif !important;
  font-size: 14px !important;
  caret-color: #00ff87 !important;
}
.stTextInput input:focus,
.stNumberInput input:focus,
[data-baseweb="input"]:focus-within input,
[data-baseweb="base-input"]:focus-within input {
  border-color: rgba(0,255,135,.5) !important;
  box-shadow: 0 0 0 2px rgba(0,255,135,.1) !important;
  outline: none !important;
  color: #ffffff !important;
}
/* Placeholder text */
.stTextInput input::placeholder,
.stNumberInput input::placeholder,
[data-baseweb="input"] input::placeholder {
  color: rgba(148,163,184,.45) !important;
}
/* Labels */
label,
.stTextInput label,
.stNumberInput label,
.stSelectbox label,
.stDateInput label,
[data-testid="stWidgetLabel"] {
  color: #64748b !important;
  font-size: 11px !important;
  letter-spacing: .1em !important;
  text-transform: uppercase !important;
  font-family: 'Outfit', sans-serif !important;
}
/* Force dark on baseweb input container */
[data-baseweb="input"],
[data-baseweb="base-input"],
[data-baseweb="input"] > div,
[data-baseweb="base-input"] > div {
  background: #0d1117 !important;
}
/* Select/dropdown */
div[data-baseweb="select"] > div,
[data-baseweb="select"] [data-baseweb="select-value-container"] {
  background: rgba(255,255,255,.05) !important;
  border: 1px solid rgba(255,255,255,.12) !important;
  border-radius: 4px !important;
  color: #e2e8f0 !important;
}
div[data-baseweb="select"] span,
[data-baseweb="select"] [data-baseweb="select-single-value"] {
  color: #e2e8f0 !important;
}
/* Number input spinner buttons */
.stNumberInput [data-baseweb="input"] {
  background: rgba(255,255,255,.05) !important;
}
/* Textarea */
.stTextArea textarea {
  background: rgba(255,255,255,.05) !important;
  border: 1px solid rgba(255,255,255,.12) !important;
  color: #e2e8f0 !important;
  font-family: 'Outfit', sans-serif !important;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"]{
  background:rgba(255,255,255,.03);border-radius:3px;
  border:1px solid rgba(255,255,255,.07);padding:3px;gap:2px;
}
.stTabs [data-baseweb="tab"]{
  color:#94a3b8;font-family:'Syne',sans-serif;font-size:12px;
  letter-spacing:.08em;text-transform:uppercase;border-radius:2px;padding:8px 18px;
}
.stTabs [aria-selected="true"]{
  color:#00ff87!important;background:rgba(0,255,135,.08)!important;
}
.stTabs [data-baseweb="tab-border"]{display:none!important;}

/* ── Tooltips ── */
.qntm-tip {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    cursor: help;
}
.qntm-tip .tip-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 14px;
    height: 14px;
    background: rgba(255,255,255,.1);
    border: 1px solid rgba(255,255,255,.15);
    border-radius: 50%;
    font-size: 9px;
    color: #64748b;
    flex-shrink: 0;
    font-style: normal;
}
.qntm-tip {
    position: relative;
    display: inline-block;
}
.qntm-tip .tip-box {
    display: none;
    position: fixed;
    background: #0d1117;
    border: 1px solid rgba(212,168,67,.4);
    border-radius: 10px;
    padding: 14px 16px;
    width: 260px;
    max-width: calc(100vw - 32px);
    z-index: 99999;
    pointer-events: none;
    box-shadow: 0 8px 40px rgba(0,0,0,.9);
    white-space: normal;
}
.qntm-tip .tip-box.visible {
    display: block;
}
.qntm-tip .tip-box .tip-title {
    font-family: 'Syne', sans-serif;
    font-size: 13px;
    font-weight: 700;
    color: #d4a843;
    margin-bottom: 6px;
}
.qntm-tip .tip-box .tip-body {
    font-size: 13px;
    color: #cbd5e1;
    line-height: 1.6;
}
.qntm-tip .tip-box .tip-weight {
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    color: #94a3b8;
    margin-top: 6px;
}
</style>
<style>

/* ── CTA button: gold primary — available on all pages ── */
.land-btn-primary > div > button,
.land-btn-primary button,
div.land-btn-primary .stButton > button,
div.land-btn-primary button[kind="secondary"] {
  background: linear-gradient(135deg,#d4a843 0%,#b8922e 50%,#d4a843 100%) !important;
  color: #0a0b14 !important;
  border: none !important;
  border-radius: 6px !important;
  font-family: 'Syne', sans-serif !important;
  font-weight: 800 !important;
  font-size: 13px !important;
  letter-spacing: .08em !important;
  text-transform: uppercase !important;
  min-height: 48px !important;
  height: auto !important;
  cursor: pointer !important;
  box-shadow: 0 0 20px rgba(212,168,67,.25) !important;
  transition: all .2s !important;
  white-space: normal !important;
}
.land-btn-primary > div > button:hover,
.land-btn-primary button:hover,
div.land-btn-primary .stButton > button:hover {
  background: linear-gradient(135deg,#e0b84e 0%,#c9a03e 50%,#e0b84e 100%) !important;
  box-shadow: 0 0 32px rgba(212,168,67,.4) !important;
  transform: translateY(-1px) !important;
}
/* ── Ghost button ── */
.land-btn-ghost > div > button,
.land-btn-ghost button {
  background: rgba(255,255,255,.04) !important;
  color: #e2e8f0 !important;
  border: 1px solid rgba(255,255,255,.15) !important;
  border-radius: 6px !important;
  font-family: 'Syne', sans-serif !important;
  font-weight: 700 !important;
  font-size: 14px !important;
  letter-spacing: .06em !important;
  text-transform: uppercase !important;
  min-height: 48px !important;
  cursor: pointer !important;
  transition: all .2s !important;
}
.land-btn-ghost > div > button:hover,
.land-btn-ghost button:hover {
  border-color: rgba(255,255,255,.3) !important;
  background: rgba(255,255,255,.08) !important;
}
/* ── CTA button: gold primary — available on all pages ── */
html, body, [class*="css"], .main, .stApp {
  font-size: 16px !important;
}
.stMarkdown p, [data-testid="stMarkdownContainer"] p {
  color: #cbd5e1 !important;
  font-size: 15px !important;
  line-height: 1.7 !important;
}
.stMarkdown h1, h1 { color: #f1f5f9 !important; font-size: 28px !important; }
.stMarkdown h2, h2 { color: #f1f5f9 !important; font-size: 22px !important; }
.stMarkdown h3, h3 { color: #e2e8f0 !important; font-size: 18px !important; }
.stMarkdown h4, h4 { color: #e2e8f0 !important; font-size: 16px !important; }
label, .stTextInput label, .stNumberInput label,
.stSelectbox label, .stDateInput label,
[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] {
  color: #94a3b8 !important;
  font-size: 13px !important;
  letter-spacing: .08em !important;
  text-transform: uppercase !important;
}
.stCheckbox label, .stCheckbox label p,
.stToggle label, .stToggle label p {
  color: #cbd5e1 !important;
  font-size: 15px !important;
  text-transform: none !important;
  letter-spacing: 0 !important;
}
.streamlit-expanderHeader, .streamlit-expanderHeader p {
  color: #cbd5e1 !important;
  font-size: 15px !important;
}
.stTabs [data-baseweb="tab"] {
  color: #94a3b8 !important;
  font-size: 14px !important;
}
.stTabs [aria-selected="true"] {
  color: #00ff87 !important;
  background: rgba(0,255,135,.08) !important;
}
div[data-baseweb="select"] span,
[data-baseweb="select"] [data-baseweb="select-single-value"] {
  color: #e2e8f0 !important;
  font-size: 15px !important;
}
[data-testid="stMetricValue"] { color: #00ff87 !important; font-size: 28px !important; }
[data-testid="stMetricLabel"] { color: #94a3b8 !important; font-size: 13px !important; }
.stRadio label, .stRadio label p,
.stRadio [data-testid="stMarkdownContainer"] p {
  color: #cbd5e1 !important;
  font-size: 14px !important;
  font-weight: 600 !important;
  text-transform: uppercase !important;
  letter-spacing: .06em !important;
}
[aria-checked="true"] label, [aria-checked="true"] label p {
  color: #00ff87 !important;
}

/* Forms */
.stForm{border:1px solid rgba(255,255,255,.07)!important;border-radius:6px!important;padding:1.5rem!important;background:rgba(255,255,255,.02)!important;}

/* Divider */
hr{border-color:rgba(255,255,255,.07)!important;}

/* Hide st.components.v1.html iframes used for JS-only operations */
iframe[height="0"], iframe[style*="height: 0"], 
[data-testid="stCustomComponentV1"] iframe {
    display: none !important;
    height: 0 !important;
    width: 0 !important;
    border: none !important;
    position: absolute !important;
    top: -9999px !important;
}


/* ── MOBILE RESPONSIVE ── */
@media (max-width: 768px) {
    /* Prevent iOS zoom on inputs */
    .stTextInput input,[data-baseweb="input"] input {
        font-size: 16px !important;
    }
    /* Scale landing hero text */
    h1 { font-size: 28px !important; }
    .land-section { padding: 32px 16px !important; }
    /* Tooltips stay on screen */
    .qntm-tip .tip-box {
        width: 220px !important;
        max-width: 80vw !important;
    }
    /* Our custom HTML data tables — horizontal scroll */
    .qntm-table-scroll {
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch !important;
    }
}
@media (max-width: 480px) {
    h1 { font-size: 22px !important; }
    .land-section { padding: 24px 12px !important; }
}
/* Viewport meta (Streamlit adds this but ensure scale=1) */
</style>
""", unsafe_allow_html=True)

# ── TOOLTIP + MOBILE JS — injected via components (only way to run JS in Streamlit) ──
import streamlit.components.v1 as _cv1_js
_cv1_js.html("""
<script>
(function() {
    function positionTip(tip, box) {
        var rect = tip.getBoundingClientRect();
        var bw = 260, margin = 12, bh = box.offsetHeight || 160;
        var top  = rect.top - bh - 10;
        var left = rect.left + rect.width / 2 - bw / 2;
        if (top < margin) top = rect.bottom + 10;
        if (top + bh > window.innerHeight - margin) top = margin;
        if (left < margin) left = margin;
        if (left + bw > window.innerWidth - margin) left = window.innerWidth - bw - margin;
        box.style.position = 'fixed';
        box.style.top  = top + 'px';
        box.style.left = left + 'px';
        box.style.display = 'block';
    }
    function hideTip(tip) {
        var box = tip.querySelector('.tip-box');
        if (box) box.style.display = 'none';
    }
    function hideAll() {
        parent.document.querySelectorAll('.tip-box').forEach(function(b) { b.style.display='none'; });
    }
    function showTip(tip) {
        hideAll();
        var box = tip.querySelector('.tip-box');
        if (!box) return;
        positionTip(tip, box);
    }
    // Desktop hover
    parent.document.addEventListener('mouseover', function(e) {
        var tip = e.target.closest('.qntm-tip');
        if (tip) showTip(tip); else hideAll();
    });
    // Mobile tap
    parent.document.addEventListener('touchend', function(e) {
        var tip = e.target.closest('.qntm-tip');
        if (tip) {
            var box = tip.querySelector('.tip-box');
            if (box && box.style.display === 'block') {
                box.style.display = 'none';
            } else {
                e.preventDefault();
                showTip(tip);
            }
        } else {
            hideAll();
        }
    }, { passive: false });
})();
</script>
""", height=0)

# ── SESSION STATE ─────────────────────────────────────────────────────────────
for k, v in {
    "page": "landing",
    "logged_in": False,
    "user": None,
    "mfa_verified": False,
    "pending_mfa_user": None,
    "pending_mfa_secret": None,
    "scan_results": None,
    "cookies_accepted": False,
    "show_mfa_setup": False,
    "totp_secret_temp": None,
    "auth_tab": "signin",
    "nav": "screener",
    "macro_data": {},
    "auto_upgrade": False,
    "remember_me":  False,
    "legal_doc": "privacy",
    "force_mfa_setup": False,   # True after first login if MFA not set up
    "port_period":  "1M",
    "live_refresh_running": False,
    "mfa_recovery_mode": False,
    "signed_out": False,
    "onboarding_done": True,
    "onboarding_step": 0,
    "tz_offset_hours": None,  # browser timezone offset, injected on first load
    "tz_name": None,          # IANA timezone name e.g. America/Los_Angeles
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── TIMEZONE DETECTION ────────────────────────────────────────────────────────
# Read ?_tz= query param set by browser JS on first load, store in session state
_tz_param = st.query_params.get("_tz", "")
if _tz_param and st.session_state.get("tz_offset_hours") is None:
    try:
        st.session_state.tz_offset_hours = float(_tz_param)
        st.query_params.pop("_tz", None)
    except Exception:
        pass

_tz_name_param = st.query_params.get("_tzname", "")
if _tz_name_param and st.session_state.get("tz_name") is None:
    st.session_state.tz_name = _tz_name_param
    st.query_params.pop("_tzname", None)

# Only inject timezone detector after cookies accepted — avoids blank box on cookie screen
if st.session_state.get("tz_offset_hours") is None and st.session_state.get("cookies_accepted"):
    import streamlit.components.v1 as _tz_cv1
    _tz_cv1.html("""
    <script>
    (function() {
        try {
            var offset = -(new Date().getTimezoneOffset() / 60);
            var tzname = Intl.DateTimeFormat().resolvedOptions().timeZone;
            var url = new URL(window.parent.location.href);
            if (!url.searchParams.get('_tz')) {
                url.searchParams.set('_tz', offset.toString());
                url.searchParams.set('_tzname', tzname);
                window.parent.location.replace(url.toString());
            }
        } catch(e) {}
    })();
    </script>
    """, height=0)


# ── PERSISTENT LOGIN — 7-day localStorage token ───────────────────────────────
# Stores {uid, plan, expires} in browser localStorage on remember-me login.
# Reads it back on every load. Falls back to query params for old sessions.

def _inject_localstorage_reader():
    """Read QNTM auth token from localStorage and restore session via query params."""
    import streamlit.components.v1 as _cv1
    _cv1.html("""
    <script>
    (function() {
        try {
            var raw = localStorage.getItem('qntm_auth');
            if (!raw) return;
            var url = new URL(window.parent.location.href);
            if (!url.searchParams.get('uid')) {
                url.searchParams.set('uid', raw);
                url.searchParams.set('plan', 'restore');
                window.parent.location.replace(url.toString());
            }
        } catch(e) {}
    })();
    </script>
    """, height=0)


def _write_localstorage_token(uid: str, plan: str):
    """Write a signed 30-day auth token to localStorage."""
    import streamlit.components.v1 as _cv1
    token = _sign_token(uid, plan, days=30)
    _cv1.html(f"""
    <script>
    try {{
        localStorage.setItem('qntm_auth', {_json.dumps(token)});
    }} catch(e) {{}}
    </script>
    """, height=0)


def _clear_localstorage_token():
    """Clear the auth token from localStorage on sign out."""
    import streamlit.components.v1 as _cv1
    _cv1.html("""
    <script>
    try { localStorage.removeItem('qntm_auth'); } catch(e) {}
    </script>
    """, height=0)


# ── Auto-restore session from localStorage or query params ────────────────────
if not st.session_state.logged_in:
    params = st.query_params
    if "uid" in params:
        _restore_ok = False
        try:
            saved_uid = params["uid"]
            verified_uid, _ = _verify_token(saved_uid)
            if verified_uid:
                user = get_user_by_id(verified_uid)
                if user:
                    qp_plan = params.get("plan", "")
                    if qp_plan in ("pro", "institutional") and user.get("plan") == "free":
                        user["plan"] = qp_plan
                    st.session_state.logged_in       = True
                    st.session_state.user            = user
                    st.session_state.mfa_verified    = True
                    st.session_state.signed_out      = False
                    st.session_state.page            = "platform"
                    st.session_state.onboarding_done = True
                    _dest = params.get("qnav", "")
                    _VALID = {"screener","gems","backtest","portfolio","simulator",
                              "model_portfolio","alerts","account","methodology"}
                    st.session_state.nav = _dest if _dest in _VALID else "screener"
                    _restore_ok = True
                else:
                    # DB returned nothing — build minimal session from query params
                    qp_plan = params.get("plan", "free")
                    st.session_state.logged_in       = True
                    st.session_state.user            = {"id": verified_uid, "plan": qp_plan, "email": "", "full_name": ""}
                    st.session_state.mfa_verified    = True
                    st.session_state.signed_out      = False
                    st.session_state.page            = "platform"
                    st.session_state.onboarding_done = True
                    _dest = params.get("qnav", "")
                    _VALID = {"screener","gems","backtest","portfolio","simulator",
                              "model_portfolio","alerts","account","methodology"}
                    st.session_state.nav = _dest if _dest in _VALID else "screener"
                    _restore_ok = True
        except Exception as _e:
            pass
    

    _nav_param = st.query_params.get("nav", "")
    _has_uid   = "uid" in st.query_params
    # Only inject localStorage reader on the landing page as a last resort
    # Injecting it globally causes location.replace() to wipe nav params mid-session

# ── HELPERS ───────────────────────────────────────────────────────────────────
def uid():
    return (st.session_state.user or {}).get("id", "demo")

def is_pro():
    return (st.session_state.user or {}).get("plan", "free") in ("pro", "institutional")

def go(page):
    st.session_state.page = page
    if st.session_state.get("logged_in") and st.session_state.get("user"):
        u = st.session_state.user
        signed = _sign_token(u["id"], u.get("plan", "free"))
        st.query_params["uid"]  = signed
        st.query_params["plan"] = u.get("plan", "free")
    st.rerun()

# ── ONBOARDING MODAL ──────────────────────────────────────────────────────────
def show_onboarding():
    pass  # disabled


# ══════════════════════════════════════════════════════════════════════════════
# LANDING PAGE
# ══════════════════════════════════════════════════════════════════════════════





# ══════════════════════════════════════════════════════════════════════════════
# LEGAL PAGES
# ══════════════════════════════════════════════════════════════════════════════
PRIVACY_POLICY = """
## Privacy Policy
**Effective Date: May 16, 2025 | QNTM Platform**

### 1. Who We Are
QNTM is a quantitative investment research platform operated by QNTM Technologies Inc.
Contact: privacy@qntm.app

### 2. Data We Collect
**Account data:** Name, email address (encrypted at rest), password (bcrypt hashed — unreadable by us).
**Usage data:** Pages visited, features used, scan timestamps. No browsing data outside QNTM.
**Portfolio data:** Tickers, share counts, average cost. Stored encrypted, never sold.
**Authentication data:** TOTP secrets (encrypted). Session tokens.

### 3. How We Use Data
- Authenticate your account and maintain your session
- Run the quantitative model against your portfolio
- Send signal change notifications (Pro users, opt-in only)
- Improve platform performance via anonymized analytics
- We do **not** sell, rent, or share your personal data with third parties for advertising

### 4. Data Storage & Security
All data stored in Supabase (SOC 2 Type II certified). Sensitive fields encrypted with AES-256-GCM
before storage. Passwords hashed with bcrypt (cost factor 12). TOTP secrets encrypted separately.
Email address stored in encrypted form plus a one-way SHA-256 hash for login lookup.

### 5. Data Retention
Account data retained while account is active. You may request deletion at any time.
Anonymized usage statistics retained up to 2 years.

### 6. Your Rights
You have the right to: access your data, correct inaccuracies, request deletion, export your data,
and withdraw consent at any time. Email privacy@qntm.app to exercise these rights.

### 7. Cookies
Essential session cookies: required for authentication. Cannot be disabled.
Analytical cookies: usage patterns to improve the platform. Can be declined at the cookie banner.
No advertising cookies. No third-party tracking pixels.

### 8. Changes
We will notify users of material changes via in-app notification 14 days in advance.
"""

TERMS_OF_SERVICE = """
## Terms of Service
**Effective Date: May 16, 2025 | QNTM Platform**

### 1. Acceptance
By creating an account or using QNTM, you agree to these Terms. If you do not agree, do not use the platform.

### 2. Service Description
QNTM is a **quantitative research and factor analysis tool**. It provides algorithmic scoring,
signal generation, and portfolio tracking for informational and educational purposes only.

### 3. NOT Investment Advice
**QNTM is not a registered investment adviser, broker-dealer, or financial planner.**
Nothing on QNTM constitutes investment advice, a recommendation to buy or sell any security,
or a guarantee of future performance. All model outputs are for research purposes only.
Past performance of the model does not predict future results. You are solely responsible
for your investment decisions. Always consult a qualified financial adviser.

### 4. Eligibility
You must be 18 or older. QNTM is available globally but users are responsible for compliance
with local financial regulations regarding investment research tools.

### 5. Account Responsibilities
You are responsible for maintaining the security of your account credentials. Enable two-factor
authentication. Notify us immediately at security@qntm.app of any unauthorized access.

### 6. Acceptable Use
You may not: scrape or copy model outputs for commercial redistribution; reverse-engineer the
scoring algorithm; share account access; use automated bots against the platform; or upload
malicious content.

### 7. Intellectual Property
The QNTM scoring model, factor methodology, and platform are proprietary. Market data displayed
is sourced from public APIs (Yahoo Finance). Company names and ticker symbols are the property
of their respective owners.

### 8. Subscriptions & Billing
Free plan: no charge, limited features as described. Pro plan: $29/month, billed monthly.
Founding Member: first 50 users receive Pro access free indefinitely. Cancel anytime.
No refunds for partial months.

### 9. Limitation of Liability
QNTM's total liability to you for any claim shall not exceed the amount you paid in the
prior 12 months (or $0 for free users). We are not liable for investment losses, market data
inaccuracies, or decisions made based on model output.

### 10. Governing Law
These Terms are governed by the laws of the State of Florida, USA.
Disputes shall be resolved by binding arbitration in Miami, Florida.
"""

DISCLAIMER_FULL = """
## Investment Disclaimer
**This disclaimer applies to all content on the QNTM platform.**

QNTM provides quantitative factor analysis, model scores, and signal generation as an educational
and research resource. The following must be understood before using any QNTM output:

**No Investment Advice:** Model HIGH, MODERATE, and LOW conviction signals are algorithmic outputs based on
historical factor analysis. They are NOT recommendations to purchase or sell any security.

**Past Performance:** The 5-year backtest results shown are based on historical data using the
model's current rules applied retroactively. Past model performance does not guarantee future results.
Backtests are subject to look-ahead bias and survivorship bias limitations despite our methodology.

**Market Risk:** All investments carry risk of loss, including the possible loss of the entire
principal amount invested. Equity markets can and do decline significantly.

**Model Limitations:** The QNTM model uses publicly available data and estimated fundamentals.
Data may be delayed, inaccurate, or incomplete. The model does not account for taxes, transaction
costs, liquidity constraints, or individual financial circumstances.

**Not a Fiduciary:** QNTM has no fiduciary duty to users. We are a technology platform, not a
registered investment adviser.

**Consult a Professional:** Before making any investment decision, consult a qualified financial
adviser, tax professional, or legal counsel appropriate to your situation.

**Regulatory Notice:** QNTM is not registered with the SEC, FINRA, or any state securities regulator.
"""

COOKIE_POLICY = """
## Cookie Policy
**Effective Date: May 16, 2025**

### Cookies We Use

| Cookie | Type | Purpose | Duration |
|--------|------|---------|----------|
| Session token | Essential | Maintains your login session | Session |
| CSRF protection | Essential | Prevents cross-site request forgery | Session |
| UI preferences | Functional | Remembers your dark/light mode preference | 1 year |
| Analytics | Analytical | Anonymous usage statistics | 90 days |

### No Advertising Cookies
We do not use cookies for advertising, retargeting, or tracking across other websites.

### Control Your Cookies
You can decline analytical cookies at the consent banner when you first visit.
Essential cookies cannot be disabled — the platform cannot function without them.
To remove all cookies, clear your browser storage for qntm.app.

### Contact
Cookie questions: privacy@qntm.app
"""


def data_freshness_banner():
    """Show data age pill with actual datetime from signal_log.created_at, in user's local time."""
    try:
        from data_refresh import _get_supabase
        from datetime import datetime, timezone, timedelta
        dt_str = None
        fresh  = True
        tz_offset = st.session_state.get("tz_offset_hours")
        tz_name   = st.session_state.get("tz_name")

        def _fmt(raw: str) -> str:
            dt     = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            dt_utc = dt.astimezone(timezone.utc)
            if tz_name:
                try:
                    from zoneinfo import ZoneInfo
                    dt_local = dt_utc.astimezone(ZoneInfo(tz_name))
                    tz_abbr  = dt_local.strftime("%Z")  # e.g. PDT, EST, GMT
                    return dt_local.strftime(f"%b %d · %H:%M {tz_abbr}")
                except Exception:
                    pass
            if tz_offset is not None:
                dt_local = dt_utc + timedelta(hours=tz_offset)
                sign     = "+" if tz_offset >= 0 else ""
                hrs      = int(tz_offset)
                return dt_local.strftime(f"%b %d · %H:%M UTC{sign}{hrs}")
            return dt_utc.strftime("%b %d · %H:%M UTC")

        try:
            sb = _get_supabase()
            if sb:
                resp = sb.table("fundamentals_cache").select("refreshed_at").order(
                    "refreshed_at", desc=True).limit(1).execute()
                if resp.data and resp.data[0].get("refreshed_at"):
                    raw    = resp.data[0]["refreshed_at"]
                    dt_str = _fmt(raw)
                    dt_utc = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
                    fresh  = (datetime.now(timezone.utc) - dt_utc) < timedelta(hours=26)
                else:
                    resp2 = sb.table("signal_log").select("created_at").order(
                        "created_at", desc=True).limit(1).execute()
                    if resp2.data:
                        raw    = resp2.data[0]["created_at"]
                        dt_str = _fmt(raw)
                        dt_utc = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
                        fresh  = (datetime.now(timezone.utc) - dt_utc) < timedelta(hours=26)
        except Exception:
            dt_str = None

        label  = f"Last refresh · {dt_str}" if dt_str else ("Data fresh" if fresh else "Stale data")
        color  = "#00ff87" if fresh else "#f59e0b"
        bg     = "rgba(0,255,135,.08)" if fresh else "rgba(245,158,11,.08)"
        border = "rgba(0,255,135,.2)"  if fresh else "rgba(245,158,11,.25)"
        suffix = "" if fresh else " · Rescan for live scores"
        st.markdown(
            f'<div style="display:inline-flex;align-items:center;gap:6px;'
            f'background:{bg};border:1px solid {border};'
            f'border-radius:20px;padding:5px 14px;font-size:12px;color:{color};'
            f'font-family:DM Mono,monospace;margin-bottom:12px;">'
            f'<span style="width:7px;height:7px;border-radius:50%;background:{color};display:inline-block;"></span>'
            f'{label}{suffix}</div>',
            unsafe_allow_html=True)
    except Exception:
        pass

def enrich_with_signal_log(results: list) -> list:
    """
    Merges latest signal_date and price from signal_log into scan results.
    Called after run_full_scan so every stock card can show last scan date + price.
    Safe to call even if Supabase is unavailable — returns results unchanged.
    """
    try:
        from data_refresh import _get_supabase
        sb = _get_supabase()
        if not sb or not results:
            return results
        tickers = [r["ticker"] for r in results]
        # Fetch latest signal_log row per ticker (most recent signal_date)
        rows = sb.table("signal_log") \
            .select("ticker,signal_date,price") \
            .in_("ticker", tickers) \
            .order("signal_date", desc=True) \
            .execute()
        if not rows.data:
            return results
        # Build map: ticker → {signal_date, price} keeping only the most recent row
        log_map = {}
        for row in rows.data:
            tk = row["ticker"]
            if tk not in log_map:
                log_map[tk] = {
                    "signal_date": row.get("signal_date","")[:10] if row.get("signal_date") else "",
                    "price":       float(row["price"]) if row.get("price") else None,
                }
        # Merge into results — only fill in missing values, don't overwrite live data
        for r in results:
            tk = r["ticker"]
            if tk in log_map:
                if not r.get("signal_date"):
                    r["signal_date"] = log_map[tk]["signal_date"]
                if not r.get("price") and log_map[tk]["price"]:
                    r["price"] = log_map[tk]["price"]
    except Exception:
        pass
    return results


def scan_health_check():
    """
    Shows last successful nightly scan time pulled from signal_log.
    Green = scanned today. Amber = scanned yesterday. Red = >48h ago or never.
    """
    try:
        from data_refresh import _get_supabase
        sb = _get_supabase()
        if not sb:
            return
        result = sb.table("signal_log") \
            .select("signal_date") \
            .order("signal_date", desc=True) \
            .limit(1) \
            .execute()
        if not result.data:
            st.markdown(
                '<div style="display:inline-flex;align-items:center;gap:6px;'
                'background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.2);'
                'border-radius:20px;padding:5px 14px;font-size:12px;color:#ef4444;'
                'font-family:DM Mono,monospace;margin-bottom:8px;">'
                '<span style="width:7px;height:7px;border-radius:50%;background:#ef4444;display:inline-block;"></span>'
                'No scan data found — run seed_track_record.py</div>',
                unsafe_allow_html=True)
            return
        from datetime import datetime, timezone
        last_date_str = result.data[0]["signal_date"]
        # signal_date may be "YYYY-MM-DD" or ISO datetime string
        try:
            last_dt = datetime.fromisoformat(last_date_str.replace("Z",""))
        except Exception:
            last_dt = datetime.strptime(last_date_str[:10], "%Y-%m-%d")
        now = datetime.now()
        age_h = (now - last_dt).total_seconds() / 3600
        if age_h < 26:
            color, bg, dot, label = "#00ff87", "rgba(0,255,135,.08)", "#00ff87", f"Nightly scan OK · {last_date_str[:10]}"
        elif age_h < 50:
            color, bg, dot, label = "#f59e0b", "rgba(245,158,11,.08)", "#f59e0b", f"Last scan {last_date_str[:10]} · check GitHub Actions"
        else:
            color, bg, dot, label = "#ef4444", "rgba(239,68,68,.08)", "#ef4444", f"Scan stale · last run {last_date_str[:10]} · check GitHub Actions"
        st.markdown(
            f'<div style="display:inline-flex;align-items:center;gap:6px;'
            f'background:{bg};border:1px solid {color}40;'
            f'border-radius:20px;padding:5px 14px;font-size:12px;color:{color};'
            f'font-family:DM Mono,monospace;margin-bottom:8px;">'
            f'<span style="width:7px;height:7px;border-radius:50%;background:{dot};display:inline-block;"></span>'
            f'{label}</div>',
            unsafe_allow_html=True)
    except Exception:
        pass


# ── PAGE SUMMARY BANNERS ──────────────────────────────────────────────────────
def page_summary(icon: str, title: str, subtitle: str, pills: list = None):
    """Consistent page header — pills param accepted but ignored (removed from UI)."""
    st.markdown(f"""
    <div style="padding:20px 32px 12px;">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:6px;">
        <span style="font-size:24px;">{icon}</span>
        <h1 style="font-family:Syne,sans-serif;font-size:24px;font-weight:800;color:#e2e8f0;margin:0;">{title}</h1>
      </div>
      <p style="color:#94a3b8;font-size:14px;line-height:1.6;max-width:680px;margin:0;">{subtitle}</p>
    </div>
    """, unsafe_allow_html=True)

def nav(section):
    st.session_state.nav = section
    st.rerun()

def signal_color(sig):
    return {"STRONG ALIGN":"#00ff87","HIGH ALIGN":"#4ade80","MODERATE":"#fbbf24",
            "LOW ALIGN":"#f97316","WEAK/NEG":"#ef4444"}.get(sig,"#64748b")

# ── PILLAR TOOLTIPS ──────────────────────────────────────────────────────────
PILLAR_TIPS = {
    "Momentum": {
        "weight": "30% of composite score",
        "body": "Price trend strength over 1, 3, and 6 months. RSI, MACD, moving average crossovers, and proximity to 52-week high. High momentum means the stock is in a confirmed uptrend with buying pressure — historically the single strongest predictor of near-term outperformance.",
    },
    "Quality": {
        "weight": "25% of composite score",
        "body": "Business quality measured by Return on Equity, profit margin, revenue growth, EPS beat rate, and free cash flow yield. High-quality companies survive downturns, compound capital, and tend to revert to outperformance after temporary selloffs.",
    },
    "Volume": {
        "weight": "20% of composite score",
        "body": "Relative trading volume, On-Balance Volume (OBV), Chaikin Money Flow, and accumulation/distribution patterns. Rising price with rising volume confirms institutional buying. Volume divergences often precede reversals.",
    },
    "Value": {
        "weight": "15% of composite score",
        "body": "Forward P/E, PEG ratio, EV/EBITDA, Price-to-Sales, and FCF yield. The model looks for stocks trading cheaply relative to their growth and quality — not just low P/E, but low P/E relative to earnings growth rate. Cheap quality beats expensive mediocrity.",
    },
    "Sentiment": {
        "weight": "10% of composite score",
        "body": "Short interest (% of float), insider buy/sell ratio, institutional ownership changes, and options put/call ratio. Low short interest + high insider buying + rising institutional ownership is a powerful contrarian signal that big money is accumulating.",
    },
}

def get_company_info(ticker: str) -> dict:
    """
    Returns {name, description} for a ticker.
    Common tickers resolve instantly from a built-in map.
    Others pull from yfinance and cache in session state.
    """
    # Instant lookup for most common tickers
    KNOWN = {
        "AAPL":"Apple Inc.","MSFT":"Microsoft Corporation","NVDA":"NVIDIA Corporation",
        "GOOGL":"Alphabet Inc.","GOOG":"Alphabet Inc.","META":"Meta Platforms Inc.",
        "AMZN":"Amazon.com Inc.","TSLA":"Tesla Inc.","NFLX":"Netflix Inc.",
        "AMD":"Advanced Micro Devices","INTC":"Intel Corporation","CSCO":"Cisco Systems",
        "ORCL":"Oracle Corporation","CRM":"Salesforce Inc.","ADBE":"Adobe Inc.",
        "INTU":"Intuit Inc.","QCOM":"Qualcomm Inc.","TXN":"Texas Instruments",
        "AVGO":"Broadcom Inc.","MU":"Micron Technology","AMAT":"Applied Materials",
        "JPM":"JPMorgan Chase & Co.","BAC":"Bank of America","GS":"Goldman Sachs",
        "MS":"Morgan Stanley","V":"Visa Inc.","MA":"Mastercard Inc.",
        "BLK":"BlackRock Inc.","AXP":"American Express","PYPL":"PayPal Holdings",
        "UNH":"UnitedHealth Group","LLY":"Eli Lilly and Company","JNJ":"Johnson & Johnson",
        "ABBV":"AbbVie Inc.","MRK":"Merck & Co.","PFE":"Pfizer Inc.",
        "TMO":"Thermo Fisher Scientific","AMGN":"Amgen Inc.","GILD":"Gilead Sciences",
        "WMT":"Walmart Inc.","COST":"Costco Wholesale","PG":"Procter & Gamble",
        "KO":"The Coca-Cola Company","PEP":"PepsiCo Inc.","HD":"Home Depot",
        "MCD":"McDonald's Corporation","NKE":"Nike Inc.","SBUX":"Starbucks Corporation",
        "XOM":"Exxon Mobil Corporation","CVX":"Chevron Corporation",
        "BRK":"Berkshire Hathaway","PLTR":"Palantir Technologies",
        "COIN":"Coinbase Global","HOOD":"Robinhood Markets",
        "SNOW":"Snowflake Inc.","DDOG":"Datadog Inc.","NET":"Cloudflare Inc.",
        "ZS":"Zscaler Inc.","CRWD":"CrowdStrike Holdings","PANW":"Palo Alto Networks",
        "NOW":"ServiceNow Inc.","WDAY":"Workday Inc.","TEAM":"Atlassian Corporation",
        "UBER":"Uber Technologies","LYFT":"Lyft Inc.","ABNB":"Airbnb Inc.",
        "DASH":"DoorDash Inc.","SPOT":"Spotify Technology",
    }

    cache_key = "company_info_cache"
    if cache_key not in st.session_state:
        st.session_state[cache_key] = {}
    cache = st.session_state[cache_key]
    if ticker in cache:
        return cache[ticker]

    # Use known name if available, skip yfinance for speed
    if ticker in KNOWN:
        result = {"name": KNOWN[ticker], "description": ""}
        cache[ticker] = result
        return result

    # Unknown ticker — try yfinance (only for search results, not bulk universe)
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        name = info.get("longName") or info.get("shortName") or ticker
        desc = info.get("longBusinessSummary") or ""
        if len(desc) > 220:
            desc = desc[:220].rsplit(" ", 1)[0] + "..."
        result = {"name": name, "description": desc}
    except Exception:
        result = {"name": ticker, "description": ""}
    cache[ticker] = result
    return result


    """Render a term with a hover tooltip info icon."""
    title = tip_dict.get("title", label)
    body  = tip_dict.get("body", "")
    weight= tip_dict.get("weight", "")
    weight_html = f'<div class="tip-weight">{weight}</div>' if weight else ""
    return (
        f'<span class="qntm-tip">{label}'
        f'<i class="tip-icon">i</i>'
        f'<span class="tip-box">'
        f'<div class="tip-title">{title}</div>'
        f'<div class="tip-body">{body}</div>'
        f'{weight_html}'
        f'</span></span>'
    )

def action_badge(action):
    colors = {"BUY":("#00ff87","rgba(0,255,135,.12)"),
              "HOLD":("#fbbf24","rgba(251,191,36,.12)"),
              "SELL":("#ef4444","rgba(239,68,68,.12)")}
    c, bg = colors.get(action, ("#64748b","rgba(100,116,139,.1)"))
    font_style = "font-family:'Syne',sans-serif;"
    return f'<span style="color:{c};background:{bg};border:1px solid {c}44;padding:2px 10px;border-radius:3px;font-size:13px;font-weight:600;letter-spacing:.08em;{font_style}">{action}</span>'

def score_bar_html(val, width=80):
    col = "#00ff87" if val>=65 else "#fbbf24" if val>=50 else "#ef4444"
    return f'<div style="width:{width}px;height:4px;background:rgba(255,255,255,.06);border-radius:2px;overflow:hidden;"><div style="width:{val}%;height:100%;background:{col};border-radius:2px;"></div></div>'

def macro_regime_banner_html(macro: dict) -> str:
    """Renders the macro regime banner with live stats from macro_data."""
    regime    = macro.get("regime","NEUTRAL")
    events    = macro.get("active_events",[])
    source    = macro.get("source","estimated")
    vix       = macro.get("vix")
    oil       = macro.get("oil_price")
    vix_level = vix    # alias used in stats block
    oil_price = oil    # alias used in stats block
    n_hdl     = macro.get("headlines_scanned", 0)

    # Regime-scaled macro weight (matches apply_macro_overlay)
    macro_w = {"RISK_OFF":25,"HIGH VOLATILITY":25,"RISK_ON":15,"MILDLY BULLISH":15,"NEUTRAL":10}.get(regime,25)
    quant_w = 100 - macro_w

    cfg = {
        "RISK_ON":          ("#1D9E75","rgba(29,158,117,.08)","rgba(29,158,117,.25)","●","Macro overlay amplifying high-conviction signals"),
        "MILDLY BULLISH":   ("#4ade80","rgba(74,222,128,.06)","rgba(74,222,128,.2)","◕","Mildly bullish environment — quant signals favoured"),
        "NEUTRAL":          ("#d4a843","rgba(212,168,67,.07)","rgba(212,168,67,.2)","◐","Macro overlay at baseline — minimal sector adjustment"),
        "RISK_OFF":         ("#ef4444","rgba(239,68,68,.07)","rgba(239,68,68,.2)","●","Macro dampening active — high-beta exposure reduced"),
        "HIGH VOLATILITY":  ("#f97316","rgba(249,115,22,.07)","rgba(249,115,22,.2)","⚡","High volatility — macro overlay at maximum dampening"),
    }.get(regime, ("#d4a843","rgba(212,168,67,.07)","rgba(212,168,67,.2)","◐","Macro overlay at baseline"))

    color, bg, border, icon, desc = cfg

    events_html = ""
    if events:
        nice = {"tariff_broad":"Tariff Headwinds","tariff_relief":"Tariff Relief",
                "fed_hawkish":"Fed Hawkish","fed_dovish":"Fed Dovish",
                "recession_signal":"Recession Signal","war_escalation":"War Escalation",
                "chip_export_ban":"Chip Export Ban","oil_spike":"Oil Spike"}
        for e in events[:4]:
            events_html += (f'<span style="background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);'
                           f'border-radius:3px;padding:2px 8px;font-size:13px;color:#94a3b8;margin-right:6px;">'
                           f'{nice.get(e,e.replace("_"," ").title())}</span>')

    # Source badge
    if macro.get("live"):
        src_parts = [f'⚡ Live']
        if n_hdl:  src_parts.append(f'{n_hdl} headlines')
        src_badge = f'<span style="font-size:13px;color:#1D9E75;margin-left:8px;">{" · ".join(src_parts)}</span>'
    else:
        src_badge = '<span style="font-size:13px;color:#94a3b8;margin-left:8px;">Est. · no live feeds</span>'

    # VIX / oil indicators
    indicators_html = ""
    if vix is not None:
        vix_col = "#ef4444" if vix >= 30 else "#fbbf24" if vix >= 20 else "#1D9E75"
        indicators_html += (f'<div style="text-align:center;">'
                           f'<div style="font-family:DM Mono,monospace;font-size:16px;font-weight:500;color:{vix_col};">{vix:.1f}</div>'
                           f'<div style="font-size:13px;color:#94a3b8;">VIX</div></div>')
    if oil is not None:
        oil_col = "#ef4444" if oil >= 90 else "#fbbf24" if oil >= 75 else "#1D9E75"
        indicators_html += (f'<div style="text-align:center;">'
                           f'<div style="font-family:DM Mono,monospace;font-size:16px;font-weight:500;color:{oil_col};">${oil:.0f}</div>'
                           f'<div style="font-size:13px;color:#94a3b8;">WTI Crude</div></div>')

    return (
        f'<div style="background:{bg};border:1px solid {border};border-radius:8px;'
        f'padding:14px 20px;margin-bottom:16px;">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">'
        f'<div style="display:flex;align-items:center;gap:10px;">'
        f'<span style="color:{color};font-size:13px;">{icon}</span>'
        f'<div>'
        f'<div style="display:flex;align-items:center;gap:6px;">'
        f'<span style="font-family:Syne,sans-serif;font-size:13px;font-weight:700;'
        f'color:{color};letter-spacing:.1em;">MACRO REGIME: {regime}</span>'
        f'{src_badge}</div>'
        f'<div style="font-size:14px;color:#94a3b8;margin-top:2px;">{desc}</div>'
        f'<div style="margin-top:6px;">{events_html}</div>'
        f'</div></div>'
        f'<div style="display:flex;gap:20px;flex-wrap:wrap;align-items:flex-start;">'

        # Quant weight
        f'<div class="qntm-tip" style="text-align:center;cursor:help;">'
        f'<div style="font-family:DM Mono,monospace;font-size:20px;font-weight:700;color:#e2e8f0;">{quant_w}%</div>'
        f'<div style="font-size:14px;color:#94a3b8;margin-top:3px;letter-spacing:.04em;">Quant Weight</div>'
        f'<span class="tip-box" style="width:260px;">'
        f'<div class="tip-title">Quant Weight</div>'
        f'<div class="tip-body">The percentage of each stock\'s final score driven purely by the 5-pillar factor model — momentum, quality, volume, value, and sentiment. Higher quant weight = model is doing the heavy lifting.</div>'
        f'</span></div>'

        # Macro weight
        f'<div class="qntm-tip" style="text-align:center;cursor:help;">'
        f'<div style="font-family:DM Mono,monospace;font-size:20px;font-weight:700;color:{color};">{macro_w}%</div>'
        f'<div style="font-size:14px;color:#94a3b8;margin-top:3px;letter-spacing:.04em;">Macro Weight</div>'
        f'<span class="tip-box" style="width:260px;">'
        f'<div class="tip-title">Macro Weight</div>'
        f'<div class="tip-body">The percentage of each score adjusted by the current macro regime. In RISK_OFF this rises to 35% — dampening high-beta exposure. In NEUTRAL it drops to 10% to let quant signals dominate.</div>'
        f'</span></div>'

        # Active events
        f'<div class="qntm-tip" style="text-align:center;cursor:help;">'
        f'<div style="font-family:DM Mono,monospace;font-size:20px;font-weight:700;color:#e2e8f0;">{len(events)}</div>'
        f'<div style="font-size:14px;color:#94a3b8;margin-top:3px;letter-spacing:.04em;">Active Events</div>'
        f'<span class="tip-box" style="width:260px;">'
        f'<div class="tip-title">Active Macro Events</div>'
        f'<div class="tip-body">Number of macro events currently detected — tariffs, Fed stance, geopolitical risk, oil shocks. Each event applies sector-level adjustments to scores. More events = stronger regime signal.</div>'
        f'</span></div>'

        + (
            f'<div class="qntm-tip" style="text-align:center;cursor:help;">'
            f'<div style="font-family:DM Mono,monospace;font-size:20px;font-weight:700;'
            f'color:{"#ef4444" if vix_level>=30 else "#fbbf24" if vix_level>=20 else "#1D9E75"};">{vix_level:.1f}</div>'
            f'<div style="font-size:14px;color:#94a3b8;margin-top:3px;letter-spacing:.04em;">VIX</div>'
            f'<span class="tip-box" style="left:auto;right:0;transform:none;">'
            f'<div class="tip-title">VIX — Fear Index</div>'
            f'<div class="tip-body">CBOE Volatility Index. Below 15 = calm market (RISK_ON). 15–25 = elevated uncertainty. Above 30 = fear/panic (forces RISK_OFF regime). VIX above 35 overrides all other regime signals.</div>'
            f'</span></div>'
            if vix_level is not None else ""
        )

        + (
            f'<div class="qntm-tip" style="text-align:center;cursor:help;">'
            f'<div style="font-family:DM Mono,monospace;font-size:20px;font-weight:700;'
            f'color:{"#ef4444" if oil_price>=90 else "#fbbf24" if oil_price>=75 else "#1D9E75"};">${oil_price:.0f}</div>'
            f'<div style="font-size:14px;color:#94a3b8;margin-top:3px;letter-spacing:.04em;">WTI Crude</div>'
            f'<span class="tip-box" style="left:auto;right:0;transform:none;">'
            f'<div class="tip-title">WTI Crude Oil Price</div>'
            f'<div class="tip-body">West Texas Intermediate crude price per barrel. Above $90 triggers an oil_spike macro event — bullish for Energy, bearish for Consumer Discretionary and Industrials. Below $65 signals weak demand.</div>'
            f'</span></div>'
            if oil_price is not None else ""
        )

        + f'</div></div></div>'
    )


def factor_panel_html(r: dict, is_gem: bool = False, company_info: dict = None) -> str:
    act    = r.get("adj_action", r.get("action","HOLD"))
    score  = r.get("adj_composite", r.get("composite", 50))
    quant  = r.get("composite", 50)
    delta  = r.get("score_delta", 0)
    act_colors = {"BUY":("#00ff87","rgba(0,255,135,.1)","rgba(0,255,135,.35)"),
                  "HOLD":("#fbbf24","rgba(251,191,36,.1)","rgba(251,191,36,.3)"),
                  "SELL":("#ef4444","rgba(239,68,68,.1)","rgba(239,68,68,.3)")}
    act_c, act_bg, act_brd = act_colors.get(act, ("#64748b","rgba(100,116,139,.1)","rgba(100,116,139,.3)"))
    left_border = f"3px solid {act_c}"
    pillars = [
        ("MOM",  r.get("momentum",50)),
        ("QUAL", r.get("quality",50)),
        ("VOL",  r.get("volume",50)),
        ("VAL",  r.get("value",50)),
        ("SENT", r.get("sentiment",50)),
    ]
    PILLAR_FULL_NAMES = {"MOM":"Momentum","QUAL":"Quality","VOL":"Volume","VAL":"Value","SENT":"Sentiment"}
    pillar_bars = ""
    for pname, pval in pillars:
        pc = "#00ff87" if pval>=65 else "#fbbf24" if pval>=50 else "#ef4444"
        full = PILLAR_FULL_NAMES.get(pname, pname)
        tip = PILLAR_TIPS.get(full, {})
        tip_body = tip.get("body","")
        tip_weight = tip.get("weight","")
        weight_html = f'<div class="tip-weight">{tip_weight}</div>' if tip_weight else ""
        label_html = (
            f'<span class="qntm-tip" style="font-size:13px;color:#94a3b8;cursor:help;">'
            f'{full}<i class="tip-icon">i</i>'
            f'<span class="tip-box"><div class="tip-title">{full}</div>'
            f'<div class="tip-body">{tip_body}</div>{weight_html}</span></span>'
        )
        pillar_bars += (
            f'<div style="flex:1;min-width:0;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">'
            f'{label_html}'
            f'<div style="font-family:DM Mono,monospace;font-size:15px;color:{pc};font-weight:700;">{pval:.0f}</div>'
            f'</div>'
            f'<div style="background:rgba(255,255,255,.05);border-radius:3px;height:6px;overflow:hidden;">'
            f'<div style="width:{pval}%;height:100%;background:{pc};border-radius:3px;"></div>'
            f'</div></div>'
        )
    sorted_pillars = sorted(pillars, key=lambda x: x[1], reverse=True)
    top2 = [p[0] for p in sorted_pillars[:2]]
    weak = [p[0] for p in sorted_pillars if p[1] < 45]
    driver = f"Driven by {top2[0]} + {top2[1]}"
    if weak: driver += f" — watch {weak[0]}"
    delta_c = "#1D9E75" if delta >= 0 else "#ef4444"
    delta_str = f"+{delta:.1f}" if delta >= 0 else f"{delta:.1f}"
    gem_badge = ' 💎' if is_gem else ""
    action_label = "HIGH" if act=="BUY" else "LOW" if act=="SELL" else "MODERATE"
    action_arrow = "▲" if act=="BUY" else "▼" if act=="SELL" else "─"
    ci_name = (company_info or {}).get("name","")
    ci_desc = (company_info or {}).get("description","")
    ticker_html = (
        f'<span class="qntm-tip" style="font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:#e2e8f0;cursor:help;">'
        f'{r["ticker"]}{gem_badge}<span class="tip-box" style="width:300px;">'
        f'<div class="tip-title">{ci_name}</div>'
        f'<div class="tip-body">{ci_desc or "Search this ticker for a full company overview."}</div>'
        f'</span></span>'
        if ci_name and ci_name != r["ticker"]
        else f'<span style="font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:#e2e8f0;">{r["ticker"]}{gem_badge}</span>'
    )
    price_html = (f'<div style="font-family:DM Mono,monospace;font-size:13px;color:#d4a843;margin-top:3px;">'
                  f'${r["price"]:,.2f} <span style="font-size:11px;color:#475569;">/ share</span>'
                  + (f' <span style="font-size:11px;color:#475569;margin-left:6px;">· scanned {r["signal_date"]}</span>'
                     if r.get("signal_date") else "")
                  + f'</div>'
                  if r.get("price") else
                  (f'<div style="font-size:11px;color:#475569;margin-top:3px;">scanned {r["signal_date"]}</div>'
                   if r.get("signal_date") else ""))
    name_html = f'<div style="font-size:13px;color:#94a3b8;margin-top:1px;">{ci_name}</div>' if ci_name and ci_name != r["ticker"] else ""
    return (
        f'<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);'
        f'border-left:{left_border};border-radius:8px;padding:16px 18px;margin-bottom:8px;">'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;">'
        f'<div style="min-width:0;flex:1;">'
        f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">'
        f'{ticker_html}'
        f'<span style="font-family:Syne,sans-serif;font-size:11px;font-weight:700;color:{act_c};'
        f'background:{act_bg};border:1px solid {act_brd};padding:3px 10px;border-radius:3px;'
        f'letter-spacing:.1em;white-space:nowrap;">{action_arrow} {action_label}</span>'
        f'<span style="font-size:11px;color:#475569;">{r.get("sector","")[:16]}</span>'
        f'</div>'
        f'{name_html}{price_html}'
        f'<div style="font-size:12px;color:#94a3b8;margin-top:4px;">{driver}</div>'
        f'</div>'
        f'<div style="text-align:right;flex-shrink:0;margin-left:8px;">'
        f'<div style="font-family:DM Mono,monospace;font-size:28px;font-weight:700;color:{act_c};">{score:.0f}</div>'
        f'<div style="font-size:12px;color:#94a3b8;">blended score</div>'
        f'<div style="font-size:12px;color:{delta_c};">macro {delta_str}</div>'
        f'</div></div>'
        f'<div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">{pillar_bars}</div>'
        f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;padding-top:10px;border-top:1px solid rgba(255,255,255,.05);">'
        f'<div style="background:rgba(255,255,255,.04);border-radius:4px;padding:7px 10px;">'
        f'<div style="font-size:11px;color:#94a3b8;letter-spacing:.07em;margin-bottom:3px;">QUANT</div>'
        f'<div style="font-family:DM Mono,monospace;font-size:16px;color:#94a3b8;">{quant:.1f}</div></div>'
        f'<div style="background:rgba(255,255,255,.04);border-radius:4px;padding:7px 10px;">'
        f'<div style="font-size:11px;color:#94a3b8;letter-spacing:.07em;margin-bottom:3px;">MACRO</div>'
        f'<div style="font-family:DM Mono,monospace;font-size:16px;color:{delta_c};">{delta_str}</div></div>'
        f'<div style="background:rgba(255,255,255,.04);border-radius:4px;padding:7px 10px;">'
        f'<div style="font-size:11px;color:#94a3b8;letter-spacing:.07em;margin-bottom:3px;">BLEND</div>'
        f'<div style="font-family:DM Mono,monospace;font-size:16px;color:#d4a843;">75/25</div></div>'
        f'<div style="background:rgba(255,255,255,.04);border-radius:4px;padding:7px 10px;">'
        f'<div style="font-size:11px;color:#94a3b8;letter-spacing:.07em;margin-bottom:3px;">RANK</div>'
        f'<div style="font-family:DM Mono,monospace;font-size:16px;color:#94a3b8;">{r.get("pct_rank",50):.0f}th</div></div>'
        f'</div></div>'
    )


def resolve_ticker(query: str) -> tuple[str, str]:
    """
    Given a ticker or company name, return (ticker, display_name).
    Tries: exact ticker match → name substring match in KNOWN → yfinance search.
    """
    q = query.strip().upper()
    if not q:
        return "", ""

    # Direct ticker match in universe
    if q in SECTORS:
        ci = get_company_info(q)
        return q, ci.get("name", q)

    # Search by name in KNOWN dict — key match first, then name substring
    q_lower = query.strip().lower()
    KNOWN_INLINE = {
        "AAPL":"Apple Inc.","MSFT":"Microsoft Corporation","NVDA":"NVIDIA Corporation",
        "GOOGL":"Alphabet Inc.","GOOG":"Alphabet Inc.","META":"Meta Platforms Inc.",
        "AMZN":"Amazon.com Inc.","TSLA":"Tesla Inc.","NFLX":"Netflix Inc.",
        "AMD":"Advanced Micro Devices","INTC":"Intel Corporation","CSCO":"Cisco Systems",
        "ORCL":"Oracle Corporation","CRM":"Salesforce Inc.","ADBE":"Adobe Inc.",
        "INTU":"Intuit Inc.","QCOM":"Qualcomm Inc.","TXN":"Texas Instruments",
        "AVGO":"Broadcom Inc.","MU":"Micron Technology","AMAT":"Applied Materials",
        "JPM":"JPMorgan Chase & Co.","BAC":"Bank of America","GS":"Goldman Sachs",
        "MS":"Morgan Stanley","V":"Visa Inc.","MA":"Mastercard Inc.",
        "BLK":"BlackRock Inc.","AXP":"American Express","PYPL":"PayPal Holdings",
        "UNH":"UnitedHealth Group","LLY":"Eli Lilly and Company","JNJ":"Johnson & Johnson",
        "ABBV":"AbbVie Inc.","MRK":"Merck & Co.","PFE":"Pfizer Inc.",
        "TMO":"Thermo Fisher Scientific","AMGN":"Amgen Inc.","GILD":"Gilead Sciences",
        "WMT":"Walmart Inc.","COST":"Costco Wholesale","PG":"Procter & Gamble",
        "KO":"The Coca-Cola Company","PEP":"PepsiCo Inc.","HD":"Home Depot",
        "MCD":"McDonald's Corporation","NKE":"Nike Inc.","SBUX":"Starbucks Corporation",
        "XOM":"Exxon Mobil Corporation","CVX":"Chevron Corporation",
        "BRK":"Berkshire Hathaway","PLTR":"Palantir Technologies",
        "COIN":"Coinbase Global","HOOD":"Robinhood Markets",
        "SNOW":"Snowflake Inc.","DDOG":"Datadog Inc.","NET":"Cloudflare Inc.",
        "ZS":"Zscaler Inc.","CRWD":"CrowdStrike Holdings","PANW":"Palo Alto Networks",
        "NOW":"ServiceNow Inc.","WDAY":"Workday Inc.","TEAM":"Atlassian Corporation",
        "NVIDIA":"NVIDIA Corporation",
        "NVDA":"NVIDIA Corporation",
        "APPLE":"Apple Inc.",
        "MICROSOFT":"Microsoft Corporation",
        "AMAZON":"Amazon.com Inc.",
        "GOOGLE":"Alphabet Inc.",
        "ALPHABET":"Alphabet Inc.",
        "META":"Meta Platforms Inc.",
        "FACEBOOK":"Meta Platforms Inc.",
        "TESLA":"Tesla Inc.",
        "NETFLIX":"Netflix Inc.",
        "PALANTIR":"Palantir Technologies",
        "COINBASE":"Coinbase Global",
        "SNOWFLAKE":"Snowflake Inc.",
        "CLOUDFLARE":"Cloudflare Inc.",
        "CROWDSTRIKE":"CrowdStrike Holdings",
        "UBER":"Uber Technologies",
        "AIRBNB":"Airbnb Inc.",
        "SPOTIFY":"Spotify Technology",
    }
    for ticker, name in KNOWN_INLINE.items():
        # Exact key match (e.g. "nvidia" → NVDA) or name substring
        if q_lower == ticker.lower() or q_lower in name.lower() or q_lower == ticker.lower():
            return ticker, name

    # Try yfinance search as last resort
    try:
        import yfinance as yf
        results = yf.Search(query, max_results=1).quotes
        if results:
            tk = results[0].get("symbol", q)
            nm = results[0].get("longname") or results[0].get("shortname") or tk
            return tk.upper(), nm
    except Exception:
        pass

    # Fall back to treating input as ticker
    return q, q
    """
    Renders a full factor transparency panel for a single stock.
    Shows: ticker · signal badge · 5-pillar bars · quant vs macro breakdown · factor driver text.
    """
    act    = r.get("adj_action", r.get("action","HOLD"))
    score  = r.get("adj_composite", r.get("composite", 50))
    quant  = r.get("composite", 50)
    delta  = r.get("score_delta", 0)
    regime = r.get("macro_regime","") or ""

    act_colors = {"BUY":("#00ff87","rgba(0,255,135,.1)","rgba(0,255,135,.35)"),
                  "HOLD":("#fbbf24","rgba(251,191,36,.1)","rgba(251,191,36,.3)"),
                  "SELL":("#ef4444","rgba(239,68,68,.1)","rgba(239,68,68,.3)")}
    act_c, act_bg, act_brd = act_colors.get(act, ("#64748b","rgba(100,116,139,.1)","rgba(100,116,139,.3)"))
    left_border = f"3px solid {act_c}"

    # 5 pillar bars
    pillars = [
        ("MOM",  r.get("momentum",50)),
        ("QUAL", r.get("quality",50)),
        ("VOL",  r.get("volume",50)),
        ("VAL",  r.get("value",50)),
        ("SENT", r.get("sentiment",50)),
    ]
    PILLAR_FULL_NAMES = {
        "MOM": "Momentum", "QUAL": "Quality",
        "VOL": "Volume",   "VAL":  "Value", "SENT": "Sentiment"
    }
    pillar_bars = ""
    for pname, pval in pillars:
        pc = "#00ff87" if pval>=65 else "#fbbf24" if pval>=50 else "#ef4444"
        full = PILLAR_FULL_NAMES.get(pname, pname)
        tip = PILLAR_TIPS.get(full, {})
        tip_title = full
        tip_body  = tip.get("body", "")
        tip_weight= tip.get("weight", "")
        weight_html = f'<div class="tip-weight">{tip_weight}</div>' if tip_weight else ""
        label_html = (
            f'<span class="qntm-tip" style="font-size:13px;color:#64748b;cursor:help;">'
            f'{full}'
            f'<i class="tip-icon">i</i>'
            f'<span class="tip-box">'
            f'<div class="tip-title">{tip_title}</div>'
            f'<div class="tip-body">{tip_body}</div>'
            f'{weight_html}'
            f'</span></span>'
        )
        pillar_bars += (
            f'<div style="flex:1;min-width:90px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">'
            f'{label_html}'
            f'<div style="font-family:DM Mono,monospace;font-size:15px;color:{pc};font-weight:700;">{pval:.0f}</div>'
            f'</div>'
            f'<div style="background:rgba(255,255,255,.05);border-radius:3px;height:7px;overflow:hidden;">'
            f'<div style="width:{pval}%;height:100%;background:linear-gradient(90deg,{pc}99,{pc});border-radius:3px;transition:width .4s;"></div>'
            f'</div></div>'
        )

    # Factor driver: identify top 2 and weakest pillar
    sorted_pillars = sorted(pillars, key=lambda x: x[1], reverse=True)
    top2 = [p[0] for p in sorted_pillars[:2]]
    weak = [p[0] for p in sorted_pillars if p[1] < 45]
    driver = f"Driven by {top2[0]} + {top2[1]}"
    if weak:
        driver += f" — watch {weak[0]}"

    # Macro delta chip
    delta_c = "#1D9E75" if delta >= 0 else "#ef4444"
    delta_str = f"+{delta:.1f}" if delta >= 0 else f"{delta:.1f}"

    gem_badge = '<span style="font-size:13px;margin-left:6px;">💎</span>' if is_gem else ""
    action_label = "HIGH" if act=="BUY" else "LOW" if act=="SELL" else "MODERATE"
    action_arrow = "▲" if act=="BUY" else "▼" if act=="SELL" else "─"

    # Build HTML as a variable first — no comments, no risk of comment stripping
    html_parts = [
        f'<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);'
        f'border-left:{left_border};border-radius:8px;padding:16px 18px;margin-bottom:8px;">',

        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;">',
        f'<div style="display:flex;align-items:center;gap:10px;">',
        f'<div>'
        f'<div style="display:flex;align-items:center;gap:6px;">'
        + (
            f'<span class="qntm-tip" style="font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:#e2e8f0;cursor:help;">'
            f'{r["ticker"]}{gem_badge}'
            f'<span class="tip-box" style="width:320px;">'
            f'<div class="tip-title" style="font-size:13px;">{company_info["name"]}</div>'
            f'<div class="tip-body">{company_info.get("description") or "Search this ticker for a full company overview."}</div>'
            f'</span></span>'
            if (company_info and company_info.get("name") and company_info["name"] != r["ticker"])
            else f'<span style="font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:#e2e8f0;">{r["ticker"]}{gem_badge}</span>'
        ) +
        f'</div>'
        + (
            f'<div style="font-size:13px;color:#94a3b8;margin-top:1px;">{company_info["name"]}</div>'
            if (company_info and company_info.get("name") and company_info["name"] != r["ticker"])
            else ''
        )
        + (
            f'<div style="font-family:DM Mono,monospace;font-size:12px;color:#d4a843;margin-top:3px;">'
            f'${r["price"]:,.2f} <span style="font-size:13px;color:#94a3b8;">/ share</span></div>'
            if r.get("price") else ''
        ) +
        f'</div>',
        f'<span style="font-family:Syne,sans-serif;font-size:13px;font-weight:700;color:{act_c};'
        f'background:{act_bg};border:1px solid {act_brd};padding:3px 10px;border-radius:3px;'
        f'letter-spacing:.1em;">{action_arrow} {action_label}</span>',
        f'<span style="font-size:13px;color:#94a3b8;">{r.get("sector","")[:16]}</span>',
        f'</div>',
        f'<div style="text-align:right;">',
        f'<div style="font-family:DM Mono,monospace;font-size:26px;font-weight:500;color:{act_c};">{score:.0f}</div>',
        f'<div style="font-size:14px;color:#94a3b8;margin-top:2px;">blended score</div>',
        f'</div></div>',

        f'<div style="display:flex;gap:10px;margin-bottom:12px;">{pillar_bars}</div>',

        f'<div style="display:flex;gap:8px;flex-wrap:wrap;padding-top:10px;border-top:1px solid rgba(255,255,255,.05);">',
        f'<div style="background:rgba(255,255,255,.04);border-radius:4px;padding:7px 12px;flex:1;min-width:70px;">'
        f'<div style="font-size:13px;color:#94a3b8;letter-spacing:.07em;margin-bottom:4px;">QUANT</div>'
        f'<div style="font-family:DM Mono,monospace;font-size:16px;color:#94a3b8;font-weight:500;">{quant:.1f}</div></div>',
        f'<div style="background:rgba(255,255,255,.04);border-radius:4px;padding:7px 12px;flex:1;min-width:70px;">'
        f'<div style="font-size:13px;color:#94a3b8;letter-spacing:.07em;margin-bottom:4px;">MACRO</div>'
        f'<div style="font-family:DM Mono,monospace;font-size:16px;color:{delta_c};font-weight:500;">{delta_str}</div></div>',
        f'<div style="background:rgba(255,255,255,.04);border-radius:4px;padding:7px 12px;flex:1;min-width:70px;">'
        f'<div style="font-size:13px;color:#94a3b8;letter-spacing:.07em;margin-bottom:4px;">BLEND</div>'
        f'<div style="font-family:DM Mono,monospace;font-size:16px;color:#d4a843;font-weight:500;">75/25</div></div>',
        f'<div style="background:rgba(255,255,255,.04);border-radius:4px;padding:7px 12px;flex:1;min-width:70px;">'
        f'<div style="font-size:13px;color:#94a3b8;letter-spacing:.07em;margin-bottom:4px;">RANK</div>'
        f'<div style="font-family:DM Mono,monospace;font-size:16px;color:#94a3b8;font-weight:500;">{r.get("pct_rank",50):.0f}th</div></div>',
        f'</div></div>',
    ]
    return "".join(html_parts)

# ── COOKIE BANNER ─────────────────────────────────────────────────────────────
def get_watchlist(user_id: str) -> list:
    """Fetch user watchlist from Supabase."""
    try:
        from data_refresh import _get_supabase
        sb = _get_supabase()
        if not sb: return []
        resp = sb.table("user_watchlist").select("*").eq("user_id", user_id).order("added_at", desc=True).execute()
        return resp.data or []
    except Exception:
        return []


def add_to_watchlist(user_id: str, ticker: str, price_at_add: float = None) -> bool:
    """Add ticker to watchlist. Returns True on success."""
    try:
        from data_refresh import _get_supabase
        from datetime import datetime
        sb = _get_supabase()
        if not sb: return False
        payload = {"user_id": user_id, "ticker": ticker,
                   "added_at": datetime.utcnow().isoformat()}
        if price_at_add:
            payload["price_at_add"] = round(price_at_add, 4)
        sb.table("user_watchlist").upsert(
            payload, on_conflict="user_id,ticker"
        ).execute()
        return True
    except Exception:
        return False


def remove_from_watchlist(user_id: str, ticker: str) -> bool:
    """Remove ticker from watchlist."""
    try:
        from data_refresh import _get_supabase
        sb = _get_supabase()
        if not sb: return False
        sb.table("user_watchlist").delete().eq("user_id", user_id).eq("ticker", ticker).execute()
        return True
    except Exception:
        return False


def cookie_banner():
    """No-op — cookie consent is now handled as a dedicated page in the router."""
    pass


def _cta_gold(label: str, href: str, full_width: bool = True) -> str:
    """Gold primary CTA — HTML link styled as gold button."""
    w = "width:100%;display:block;" if full_width else "display:inline-block;"
    return (
        f'<a href="{href}" target="_self" style="{w}text-align:center;padding:12px 20px;'
        f'background:linear-gradient(135deg,#d4a843 0%,#b8922e 50%,#d4a843 100%);'
        f'border:none;border-radius:6px;font-family:Syne,sans-serif;font-size:13px;font-weight:800;'
        f'letter-spacing:.06em;text-transform:uppercase;color:#0a0b14;text-decoration:none;'
        f'box-sizing:border-box;margin-top:4px;">{label}</a>'
    )


def _cta_ghost(label: str, href: str, full_width: bool = True) -> str:
    """Ghost secondary CTA — HTML link styled as ghost button."""
    w = "width:100%;display:block;" if full_width else "display:inline-block;"
    return (
        f'<a href="{href}" target="_self" style="{w}text-align:center;padding:12px 20px;'
        f'background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.18);'
        f'border-radius:6px;font-family:Syne,sans-serif;font-size:13px;font-weight:700;'
        f'letter-spacing:.06em;text-transform:uppercase;color:#e2e8f0;text-decoration:none;'
        f'box-sizing:border-box;margin-top:4px;">{label}</a>'
    )

# ── DISCLAIMER ────────────────────────────────────────────────────────────────
DISCLAIMER = """<div style="background:rgba(251,191,36,.05);border:1px solid rgba(251,191,36,.2);
border-radius:4px;padding:12px 16px;font-size:13px;color:#64748b;line-height:1.7;margin:1rem 0;">
⚠ <strong style="color:#fbbf24;">Disclaimer:</strong>
QNTM is a quantitative research and factor analysis tool for informational and educational
purposes only. It does not constitute investment advice, a recommendation to buy or sell
any security, or a guarantee of future performance. Past model performance does not predict
future results. All investments involve risk including possible loss of principal. Consult
a qualified financial adviser before making any investment decisions.
</div>"""

# ══════════════════════════════════════════════════════════════════════════════
# LANDING PAGE
# ══════════════════════════════════════════════════════════════════════════════





# ══════════════════════════════════════════════════════════════════════════════
# LEGAL PAGES
# ══════════════════════════════════════════════════════════════════════════════
PRIVACY_POLICY = """
## Privacy Policy
**Effective Date: May 16, 2025 | QNTM Platform**

### 1. Who We Are
QNTM is a quantitative investment research platform operated by QNTM Technologies Inc.
Contact: privacy@qntm.app

### 2. Data We Collect
**Account data:** Name, email address (encrypted at rest), password (bcrypt hashed — unreadable by us).
**Usage data:** Pages visited, features used, scan timestamps. No browsing data outside QNTM.
**Portfolio data:** Tickers, share counts, average cost. Stored encrypted, never sold.
**Authentication data:** TOTP secrets (encrypted). Session tokens.

### 3. How We Use Data
- Authenticate your account and maintain your session
- Run the quantitative model against your portfolio
- Send signal change notifications (Pro users, opt-in only)
- Improve platform performance via anonymized analytics
- We do **not** sell, rent, or share your personal data with third parties for advertising

### 4. Data Storage & Security
All data stored in Supabase (SOC 2 Type II certified). Sensitive fields encrypted with AES-256-GCM
before storage. Passwords hashed with bcrypt (cost factor 12). TOTP secrets encrypted separately.
Email address stored in encrypted form plus a one-way SHA-256 hash for login lookup.

### 5. Data Retention
Account data retained while account is active. You may request deletion at any time.
Anonymized usage statistics retained up to 2 years.

### 6. Your Rights
You have the right to: access your data, correct inaccuracies, request deletion, export your data,
and withdraw consent at any time. Email privacy@qntm.app to exercise these rights.

### 7. Cookies
Essential session cookies: required for authentication. Cannot be disabled.
Analytical cookies: usage patterns to improve the platform. Can be declined at the cookie banner.
No advertising cookies. No third-party tracking pixels.

### 8. Changes
We will notify users of material changes via in-app notification 14 days in advance.
"""

TERMS_OF_SERVICE = """
## Terms of Service
**Effective Date: May 16, 2025 | QNTM Platform**

### 1. Acceptance
By creating an account or using QNTM, you agree to these Terms. If you do not agree, do not use the platform.

### 2. Service Description
QNTM is a **quantitative research and factor analysis tool**. It provides algorithmic scoring,
signal generation, and portfolio tracking for informational and educational purposes only.

### 3. NOT Investment Advice
**QNTM is not a registered investment adviser, broker-dealer, or financial planner.**
Nothing on QNTM constitutes investment advice, a recommendation to buy or sell any security,
or a guarantee of future performance. All model outputs are for research purposes only.
Past performance of the model does not predict future results. You are solely responsible
for your investment decisions. Always consult a qualified financial adviser.

### 4. Eligibility
You must be 18 or older. QNTM is available globally but users are responsible for compliance
with local financial regulations regarding investment research tools.

### 5. Account Responsibilities
You are responsible for maintaining the security of your account credentials. Enable two-factor
authentication. Notify us immediately at security@qntm.app of any unauthorized access.

### 6. Acceptable Use
You may not: scrape or copy model outputs for commercial redistribution; reverse-engineer the
scoring algorithm; share account access; use automated bots against the platform; or upload
malicious content.

### 7. Intellectual Property
The QNTM scoring model, factor methodology, and platform are proprietary. Market data displayed
is sourced from public APIs (Yahoo Finance). Company names and ticker symbols are the property
of their respective owners.

### 8. Subscriptions & Billing
Free plan: no charge, limited features as described. Pro plan: $29/month, billed monthly.
Founding Member: first 50 users receive Pro access free indefinitely. Cancel anytime.
No refunds for partial months.

### 9. Limitation of Liability
QNTM's total liability to you for any claim shall not exceed the amount you paid in the
prior 12 months (or $0 for free users). We are not liable for investment losses, market data
inaccuracies, or decisions made based on model output.

### 10. Governing Law
These Terms are governed by the laws of the State of Florida, USA.
Disputes shall be resolved by binding arbitration in Miami, Florida.
"""

DISCLAIMER_FULL = """
## Investment Disclaimer
**This disclaimer applies to all content on the QNTM platform.**

QNTM provides quantitative factor analysis, model scores, and signal generation as an educational
and research resource. The following must be understood before using any QNTM output:

**No Investment Advice:** Model HIGH, MODERATE, and LOW conviction signals are algorithmic outputs based on
historical factor analysis. They are NOT recommendations to purchase or sell any security.

**Past Performance:** The 5-year backtest results shown are based on historical data using the
model's current rules applied retroactively. Past model performance does not guarantee future results.
Backtests are subject to look-ahead bias and survivorship bias limitations despite our methodology.

**Market Risk:** All investments carry risk of loss, including the possible loss of the entire
principal amount invested. Equity markets can and do decline significantly.

**Model Limitations:** The QNTM model uses publicly available data and estimated fundamentals.
Data may be delayed, inaccurate, or incomplete. The model does not account for taxes, transaction
costs, liquidity constraints, or individual financial circumstances.

**Not a Fiduciary:** QNTM has no fiduciary duty to users. We are a technology platform, not a
registered investment adviser.

**Consult a Professional:** Before making any investment decision, consult a qualified financial
adviser, tax professional, or legal counsel appropriate to your situation.

**Regulatory Notice:** QNTM is not registered with the SEC, FINRA, or any state securities regulator.
"""

COOKIE_POLICY = """
## Cookie Policy
**Effective Date: May 16, 2025**

### Cookies We Use

| Cookie | Type | Purpose | Duration |
|--------|------|---------|----------|
| Session token | Essential | Maintains your login session | Session |
| CSRF protection | Essential | Prevents cross-site request forgery | Session |
| UI preferences | Functional | Remembers your dark/light mode preference | 1 year |
| Analytics | Analytical | Anonymous usage statistics | 90 days |

### No Advertising Cookies
We do not use cookies for advertising, retargeting, or tracking across other websites.

### Control Your Cookies
You can decline analytical cookies at the consent banner when you first visit.
Essential cookies cannot be disabled — the platform cannot function without them.
To remove all cookies, clear your browser storage for qntm.app.

### Contact
Cookie questions: privacy@qntm.app
"""


def page_legal(doc_key: str = "privacy"):
    docs = {
        "privacy":    ("Privacy Policy",    PRIVACY_POLICY),
        "terms":      ("Terms of Service",  TERMS_OF_SERVICE),
        "disclaimer": ("Investment Disclaimer", DISCLAIMER_FULL),
        "cookies":    ("Cookie Policy",     COOKIE_POLICY),
    }
    title, text = docs.get(doc_key, docs["privacy"])

    st.markdown("""
    <style>
    .legal-body { max-width: 800px; margin: 0 auto; padding: 40px 32px; }
    .legal-body h2 { font-family:'Syne',sans-serif;font-size:28px;font-weight:800;
                     color:#e2e8f0;margin-bottom:6px; }
    .legal-body h3 { font-family:'Syne',sans-serif;font-size:16px;font-weight:700;
                     color:#d4a843;margin:24px 0 8px; }
    .legal-body p,.legal-body li { font-size:14px;color:#94a3b8;line-height:1.8; }
    .legal-body strong { color:#e2e8f0; }
    .legal-body table { width:100%;border-collapse:collapse;margin:12px 0; }
    .legal-body th { font-size:14px;color:#94a3b8;text-align:left;padding:8px 12px;
                     border-bottom:1px solid rgba(255,255,255,.08); }
    .legal-body td { font-size:13px;color:#94a3b8;padding:8px 12px;
                     border-bottom:1px solid rgba(255,255,255,.04); }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("""
    <a href="/" style="display:inline-flex;align-items:center;gap:6px;
       font-family:'Syne',sans-serif;font-size:13px;font-weight:700;color:#00ff87;
       text-decoration:none;padding:10px 16px;border:1px solid rgba(0,255,135,.3);
       border-radius:6px;margin:16px 16px 0;">← Back</a>
    """, unsafe_allow_html=True)

    st.markdown('<div class="legal-body">', unsafe_allow_html=True)
    st.markdown(text)
    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# COOKIE CONSENT PAGE — full page, 100% reliable buttons
# ══════════════════════════════════════════════════════════════════════════════
def page_cookie_consent():
    """No-op — cookie banner is now shown inline at bottom of landing page."""
    pass


def _cookie_banner():
    """Slim informational bottom banner — no click required, implied consent on use."""
    # Auto-accept on display — user is informed by seeing the banner
    if not st.session_state.get("cookies_accepted"):
        st.session_state.cookies_accepted = True
        st.query_params["ck"] = "1"

    st.markdown(
        '<style>'
        '#qntm-cookie-banner{'
        'position:fixed;bottom:0;left:0;right:0;z-index:9999;'
        'background:rgba(8,10,18,.95);backdrop-filter:blur(16px);'
        'border-top:1px solid rgba(255,255,255,.06);'
        'padding:12px 24px;}'
        '</style>'
        '<div id="qntm-cookie-banner">'
        '<div style="font-size:12px;color:#475569;line-height:1.5;max-width:900px;">'
        'QNTM uses essential cookies for login and session management and anonymous analytics to improve the platform. '
        'By using QNTM you agree to our '
        '<a href="?legal=privacy" style="color:#64748b;text-decoration:underline;">Privacy Policy</a> and '
        '<a href="?legal=terms" style="color:#64748b;text-decoration:underline;">Terms of Service</a>. '
        'QNTM is a quantitative research tool — not investment advice.'
        '</div>'
        '</div>',
        unsafe_allow_html=True
    )



# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC MODEL PORTFOLIO PAGE — no auth required, shareable link
def page_landing():
    bt = BACKTEST_DATA

    # Returning user with no uid in URL — try localStorage to restore session
    if not st.session_state.logged_in and not st.session_state.get("signed_out") and "uid" not in st.query_params:
        _inject_localstorage_reader()

    # ── Global landing CSS — overrides Streamlit defaults completely ─────────────
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Mono:wght@400;500&family=Outfit:wght@300;400;500;600&display=swap');

    /* ── Hard reset Streamlit to dark theme + kill all horizontal scroll ── */
    html, body { overflow-x: hidden !important; max-width: 100vw !important; }
    html, body, [class*="css"], .main, .block-container,
    [data-testid="stAppViewContainer"], [data-testid="stMain"],
    [data-testid="stMainBlockContainer"] {
        background-color: #0a0b14 !important;
        color: #e2e4f0 !important;
        font-family: 'Outfit', sans-serif !important;
        overflow-x: hidden !important;
        max-width: 100% !important;
    }
    [data-testid="stAppViewContainer"] > section > div {
        background-color: #0a0b14 !important;
        overflow-x: hidden !important;
    }
    /* Remove Streamlit default padding */
    .main .block-container {
        padding: 0 !important;
        max-width: 100% !important;
        overflow-x: hidden !important;
    }
    /* Clamp all Streamlit column blocks to viewport */
    [data-testid="stHorizontalBlock"] {
        max-width: 100vw !important;
        overflow-x: hidden !important;
    }
    /* Hide hamburger, header, footer */
    #MainMenu, header[data-testid="stHeader"], footer { display: none !important; }

    /* ── Layout helpers ── */
    .land-section { padding: 72px clamp(16px,4vw,48px); max-width: 1200px; margin: 0 auto; }
    .land-divider  { border-top: 1px solid rgba(255,255,255,.06); }

    /* ── Animations ── */
    @keyframes land-pulse  { 0%,100%{opacity:1} 50%{opacity:.3} }
    @keyframes land-ticker { 0%{transform:translateX(0)} 100%{transform:translateX(-50%)} }

    /* ── Streamlit columns on landing ── */
    section[data-testid="stMain"] [data-testid="stHorizontalBlock"] {
        gap: 6px !important;
        background: transparent !important;
        max-width: 100vw !important;
        overflow-x: hidden !important;
    }

    /* ── CTA button styles — liquid gold primary, glass ghost ── */
    @keyframes land-gold-shimmer {
      0%   { background-position: -300% center; }
      100% { background-position:  300% center; }
    }
    @keyframes land-float {
      0%,100% { transform: translateY(0px);   box-shadow: 0 8px 32px rgba(212,168,67,.25), 0 2px 8px rgba(0,0,0,.4); }
      50%      { transform: translateY(-4px);  box-shadow: 0 16px 40px rgba(212,168,67,.35), 0 4px 12px rgba(0,0,0,.5); }
    }

    .land-btn-primary > div > button,
    .land-btn-primary button {
        background: linear-gradient(
          105deg,
          #c8973a 0%,
          #e8be5a 25%,
          #d4a843 45%,
          #f0cc6a 55%,
          #d4a843 70%,
          #b8822a 100%
        ) !important;
        background-size: 300% 100% !important;
        color: #000 !important;
        border: none !important;
        border-radius: 6px !important;
        font-family: 'Syne', sans-serif !important;
        font-weight: 800 !important;
        font-size: 11px !important;
        letter-spacing: .18em !important;
        padding: 13px 28px !important;
        text-transform: uppercase !important;
        width: 100% !important;
        cursor: pointer !important;
        position: relative !important;
        overflow: hidden !important;
        box-shadow: 0 6px 24px rgba(212,168,67,.3), 0 2px 6px rgba(0,0,0,.5),
                    inset 0 1px 0 rgba(255,255,255,.25) !important;
        transition: box-shadow .25s, transform .2s, background-position .4s !important;
        animation: land-float 4s ease-in-out infinite !important;
    }
    .land-btn-primary > div > button::after,
    .land-btn-primary button::after {
        content: '' !important;
        position: absolute !important;
        top: 0 !important; left: -100% !important;
        width: 60% !important; height: 100% !important;
        background: linear-gradient(
          90deg, transparent,
          rgba(255,255,255,.25),
          transparent) !important;
        transform: skewX(-20deg) !important;
        transition: left .5s !important;
    }
    .land-btn-primary > div > button:hover::after,
    .land-btn-primary button:hover::after {
        left: 160% !important;
    }
    .land-btn-primary > div > button:hover,
    .land-btn-primary button:hover {
        background-position: 100% center !important;
        box-shadow: 0 12px 40px rgba(212,168,67,.5), 0 4px 12px rgba(0,0,0,.6),
                    inset 0 1px 0 rgba(255,255,255,.3) !important;
        animation-play-state: paused !important;
        transform: translateY(-3px) !important;
    }
    .land-btn-primary > div > button:active,
    .land-btn-primary button:active {
        transform: translateY(0) !important;
        animation-play-state: paused !important;
    }

    .land-btn-ghost > div > button,
    .land-btn-ghost button {
        background: rgba(212,168,67,.04) !important;
        color: #d4a843 !important;
        border: 1px solid rgba(212,168,67,.35) !important;
        border-radius: 6px !important;
        font-family: 'Syne', sans-serif !important;
        font-weight: 700 !important;
        font-size: 11px !important;
        letter-spacing: .18em !important;
        padding: 13px 28px !important;
        text-transform: uppercase !important;
        width: 100% !important;
        cursor: pointer !important;
        backdrop-filter: blur(8px) !important;
        box-shadow: inset 0 1px 0 rgba(212,168,67,.12),
                    0 2px 8px rgba(0,0,0,.3) !important;
        transition: background .2s, border-color .2s, box-shadow .2s, transform .2s !important;
    }
    .land-btn-ghost > div > button:hover,
    .land-btn-ghost button:hover {
        background: rgba(212,168,67,.10) !important;
        border-color: rgba(212,168,67,.65) !important;
        box-shadow: 0 0 16px rgba(212,168,67,.15),
                    inset 0 1px 0 rgba(212,168,67,.2),
                    0 4px 12px rgba(0,0,0,.4) !important;
        transform: translateY(-2px) !important;
        color: #e8be5a !important;
    }

    /* ── Scrollbar ── */
    ::-webkit-scrollbar { width: 3px; }
    ::-webkit-scrollbar-track { background: #0a0b14; }
    ::-webkit-scrollbar-thumb { background: #d4a843; border-radius: 2px; }
    </style>
    """, unsafe_allow_html=True)

    # ── NAV BAR ───────────────────────────────────────────────────────────────
    # Inject sticky nav CSS
    st.markdown("""
    <style>
    /* Sticky nav wrapper */
    .qntm-nav {
        position: sticky; top: 0; z-index: 999;
        background: rgba(10,11,20,.97);
        backdrop-filter: blur(12px);
        border-bottom: 1px solid rgba(255,255,255,.06);
        padding: 0 clamp(16px,4vw,48px);
        height: 60px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        width: 100%;
        box-sizing: border-box;
    }
    .qntm-nav-logo {
        font-family: 'Syne', sans-serif;
        font-size: 22px;
        font-weight: 800;
        letter-spacing: .18em;
        color: #e2e4f0;
    }
    .qntm-nav-logo span { color: #d4a843; }
    .qntm-nav-links { display: flex; gap: 10px; align-items: center; }
    </style>
    <div class="qntm-nav">
      <div class="qntm-nav-logo">Q<span>NTM</span></div>
      <div class="qntm-nav-links" id="qntm-nav-btns">
        <!-- Streamlit buttons injected below via columns -->
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Nav buttons — pure HTML links, no st.columns, no layout issues
    st.markdown("""
    <style>
    .qntm-nav-btns { display:flex; gap:8px; align-items:center; }
    .qntm-nav-btns a {
        font-family:'Syne',sans-serif; font-size:13px; font-weight:700;
        letter-spacing:.12em; text-transform:uppercase; text-decoration:none;
        padding:8px 14px; border-radius:6px; white-space:nowrap;
    }
    .qntm-nav-btn-ghost { color:#d4a843 !important; border:1px solid rgba(212,168,67,.4); background:rgba(212,168,67,.04); }
    .qntm-nav-btn-primary { color:#000 !important; background:#d4a843; }
    @media (max-width:600px) {
        .qntm-nav-btns a { font-size:11px; padding:7px 12px; letter-spacing:.04em; }
    }
    </style>
    <div style="display:flex;justify-content:flex-end;padding:0 16px;margin-top:-52px;position:relative;z-index:1000;height:52px;align-items:center;">
      <div class="qntm-nav-btns">
        <a href="?nav=signin" target="_self" class="qntm-nav-btn-ghost">Sign In</a>
        <a href="?nav=register" target="_self" class="qntm-nav-btn-primary">Join Free</a>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── HERO ──────────────────────────────────────────────────────────────────
    bt = BACKTEST_DATA
    _mr  = f"+{bt['model_total_ret']:.0f}%"
    _sr  = f"+{bt['spy_total_ret']:.0f}%"
    _sh  = f"{bt['sharpe']:.2f}"
    _wr  = f"{bt['win_rate']:.0f}%"
    _dd  = f"{bt['max_dd_model']:.1f}%"
    _dds = f"{bt['max_dd_spy']:.1f}%"

    # No f-string: avoids CSS brace conflicts and HTML comment stripping
    hero_html = (
        '<style>'
        '.qntm-hero{display:grid;grid-template-columns:1fr 1fr;gap:48px;align-items:center;'
        'padding:48px clamp(16px,4vw,48px) 36px;max-width:1200px;margin:0 auto;'
        'background:radial-gradient(ellipse 80% 50% at 30% 0%,rgba(212,168,67,.06) 0%,transparent 70%);}'
        '.qntm-stat-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;}'
        '@media(max-width:700px){.qntm-hero{grid-template-columns:1fr!important;gap:24px!important;}}'
        '</style>'
        '<div class="qntm-hero">'
        '<div>'
        '<div style="display:inline-flex;align-items:center;gap:8px;background:rgba(212,168,67,.08);'
        'border:1px solid rgba(212,168,67,.2);border-radius:100px;padding:5px 14px;margin-bottom:20px;">'
        '<div style="width:6px;height:6px;background:#00ff87;border-radius:50%;'
        'animation:land-pulse 2s infinite;flex-shrink:0;"></div>'
        '<span style="font-family:DM Mono,monospace;font-size:11px;color:#d4a843;letter-spacing:.1em;">'
        'MODEL LIVE · 5-YR VALIDATED · 834 STOCKS</span></div>'
        '<h1 style="font-family:Syne,sans-serif;font-size:clamp(34px,4.5vw,62px);'
        'font-weight:800;line-height:1.0;letter-spacing:-.02em;color:#ffffff;margin-bottom:16px;">'
        'Know where<br>conviction is<br>'
        '<span style="color:#d4a843;">strongest.</span></h1>'
        '<p style="font-size:15px;color:#94a3b8;max-width:420px;line-height:1.7;margin-bottom:28px;">'
        'A multi-factor quantitative model scoring 834 stocks daily across momentum, '
        'quality, volume, value, and sentiment — blended with a live macro regime overlay.'
        '</p></div>'
        '<div class="qntm-stat-grid">'
        '<div style="background:rgba(212,168,67,.06);border:1px solid rgba(212,168,67,.15);border-radius:10px;padding:18px 16px;">'
        '<div style="font-family:DM Mono,monospace;font-size:10px;color:#64748b;letter-spacing:.1em;margin-bottom:6px;">5-YR RETURN</div>'
        '<div style="font-family:Syne,sans-serif;font-size:28px;font-weight:800;color:#d4a843;line-height:1;">' + _mr + '</div>'
        '<div style="font-size:11px;color:#475569;margin-top:4px;">vs SPY ' + _sr + '</div></div>'
        '<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.06);border-radius:10px;padding:18px 16px;">'
        '<div style="font-family:DM Mono,monospace;font-size:10px;color:#64748b;letter-spacing:.1em;margin-bottom:6px;">SHARPE RATIO</div>'
        '<div style="font-family:Syne,sans-serif;font-size:28px;font-weight:800;color:#e2e8f0;line-height:1;">' + _sh + '</div>'
        '<div style="font-size:11px;color:#475569;margin-top:4px;">&gt;1.0 excellent</div></div>'
        '<div style="background:rgba(0,255,135,.04);border:1px solid rgba(0,255,135,.1);border-radius:10px;padding:18px 16px;">'
        '<div style="font-family:DM Mono,monospace;font-size:10px;color:#64748b;letter-spacing:.1em;margin-bottom:6px;">WIN RATE</div>'
        '<div style="font-family:Syne,sans-serif;font-size:28px;font-weight:800;color:#00ff87;line-height:1;">' + _wr + '</div>'
        '<div style="font-size:11px;color:#475569;margin-top:4px;">quarterly · 20 periods</div></div>'
        '<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.06);border-radius:10px;padding:18px 16px;">'
        '<div style="font-family:DM Mono,monospace;font-size:10px;color:#64748b;letter-spacing:.1em;margin-bottom:6px;">MAX DRAWDOWN</div>'
        '<div style="font-family:Syne,sans-serif;font-size:28px;font-weight:800;color:#e2e8f0;line-height:1;">' + _dd + '</div>'
        '<div style="font-size:11px;color:#475569;margin-top:4px;">vs SPY ' + _dds + '</div></div>'
        '</div></div>'
    )
    st.markdown(hero_html, unsafe_allow_html=True)

    # Hero CTA buttons — equal width HTML links
    hb1, hb2 = st.columns(2)
    with hb1:
        st.markdown(_cta_gold("Join Free →", "?nav=register"), unsafe_allow_html=True)
    with hb2:
        st.markdown(_cta_ghost("Sign In", "?nav=signin"), unsafe_allow_html=True)


    # ── TICKER TAPE — live from model scores ─────────────────────────────────
    # Pull top BUYs and bottom SELLs from scan results if available
    tape_scores = st.session_state.get("scan_results") or []
    if tape_scores:
        buys  = [s for s in tape_scores if s.get("adj_action","") == "BUY"  or s.get("action","") == "BUY"][:8]
        sells = [s for s in tape_scores if s.get("adj_action","") == "SELL" or s.get("action","") == "SELL"][:5]
        tape_items = (
            [(s["ticker"],"High","#00ff87") for s in buys] +
            [(s["ticker"],"Low","#E24B4A")  for s in sells]
        )
    else:
        # Static fallback — updated to current model signals
        tape_items = [
            ("NVDA","HIGH","#00ff87"),("META","HIGH","#00ff87"),
            ("AVGO","HIGH","#00ff87"),("JPM","HIGH","#00ff87"),
            ("NFLX","HIGH","#00ff87"),("COST","HIGH","#00ff87"),
            ("GS","HIGH","#00ff87"),("WMT","HIGH","#00ff87"),
            ("MA","HIGH","#00ff87"),("MSFT","HIGH","#00ff87"),
            ("TSLA","MOD","#d4a843"),
            ("UNH","LOW","#E24B4A"),("NKE","LOW","#E24B4A"),
            ("PFE","LOW","#E24B4A"),("SNAP","LOW","#E24B4A"),
        ]

    def tape_span(ticker, action, color):
        return f'<span style="color:{color};">{ticker} {action}</span> &middot; '

    tape_html = "".join(tape_span(*i) for i in tape_items).rstrip(" &middot; ")
    # Duplicate for seamless scroll
    st.markdown(f"""
    <div style="overflow:hidden;max-width:100vw;background:rgba(0,255,135,.04);
         border-top:1px solid rgba(0,255,135,.12);border-bottom:1px solid rgba(0,255,135,.12);
         padding:13px 0;margin-top:8px;">
      <div style="display:inline-flex;animation:land-ticker 45s linear infinite;white-space:nowrap;will-change:transform;">
        <span style="font-family:'DM Mono',monospace;font-size:12px;padding:0 24px;">
          {tape_html}
        </span>
        <span style="font-family:'DM Mono',monospace;font-size:12px;padding:0 24px;">
          {tape_html}
        </span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── PERFORMANCE SECTION ───────────────────────────────────────────────────
    st.markdown("""
    <div class="land-divider"></div>
    <div class="land-section">
      <div style="font-family:'DM Mono',monospace;font-size:13px;color:#d4a843;letter-spacing:.2em;margin-bottom:14px;">&mdash; PERFORMANCE</div>
      <h2 style="font-family:'Syne',sans-serif;font-size:clamp(28px,4vw,42px);font-weight:800;
           color:#fff;margin-bottom:10px;line-height:1.1;">
        5 years. 6 regimes.<br><span style="color:#d4a843;">Proven in every market.</span>
      </h2>
      <p style="color:#94a3b8;margin-bottom:40px;">Real data. Same rules every year. No tuning.</p>
    </div>
    """, unsafe_allow_html=True)

    # Big 4 stats — 2x2 HTML grid
    st.markdown(f"""
    <div style="width:100%;box-sizing:border-box;padding:0 16px;margin-bottom:24px;">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div style="background:#0e0f1a;border:1px solid rgba(255,255,255,.07);border-radius:8px;padding:14px;min-width:0;overflow:hidden;">
          <div style="font-family:DM Mono,monospace;font-size:14px;color:#94a3b8;letter-spacing:.08em;margin-bottom:6px;">MODEL 5-YR TOTAL</div>
          <div style="font-family:Syne,sans-serif;font-size:clamp(18px,4.5vw,28px);font-weight:800;color:#d4a843;line-height:1;">+{bt['model_total_ret']:.1f}%</div>
          <div style="font-size:13px;color:#94a3b8;margin-top:4px;">${bt['model_final_100k']:,} from $100K</div>
        </div>
        <div style="background:#0e0f1a;border:1px solid rgba(255,255,255,.07);border-radius:8px;padding:14px;min-width:0;overflow:hidden;">
          <div style="font-family:DM Mono,monospace;font-size:14px;color:#94a3b8;letter-spacing:.08em;margin-bottom:6px;">SPY SAME PERIOD</div>
          <div style="font-family:Syne,sans-serif;font-size:clamp(18px,4.5vw,28px);font-weight:800;color:#64748b;line-height:1;">+{bt['spy_total_ret']:.1f}%</div>
          <div style="font-size:13px;color:#94a3b8;margin-top:4px;">${bt['spy_final_100k']:,} from $100K</div>
        </div>
        <div style="background:#0e0f1a;border:1px solid rgba(255,255,255,.07);border-radius:8px;padding:14px;min-width:0;overflow:hidden;">
          <div style="font-family:DM Mono,monospace;font-size:14px;color:#94a3b8;letter-spacing:.08em;margin-bottom:6px;">MODEL CAGR</div>
          <div style="font-family:Syne,sans-serif;font-size:clamp(18px,4.5vw,28px);font-weight:800;color:#d4a843;line-height:1;">+{bt['model_cagr']:.1f}%</div>
          <div style="font-size:13px;color:#94a3b8;margin-top:4px;">vs SPY +{bt['spy_cagr']:.1f}% CAGR</div>
        </div>
        <div style="background:#0e0f1a;border:1px solid rgba(255,255,255,.07);border-radius:8px;padding:14px;min-width:0;overflow:hidden;">
          <div style="font-family:DM Mono,monospace;font-size:14px;color:#94a3b8;letter-spacing:.08em;margin-bottom:6px;">5-YR ADVANTAGE</div>
          <div style="font-family:Syne,sans-serif;font-size:clamp(13px,3vw,22px);font-weight:800;color:#1D9E75;line-height:1;">+${bt['model_advantage_usd']:,}</div>
          <div style="font-size:13px;color:#94a3b8;margin-top:4px;">on $100,000 invested</div>
        </div>
      </div>
    </div>
    <div style="width:100%;box-sizing:border-box;padding:0 16px;font-size:13px;color:#94a3b8;margin-bottom:14px;">Same rules every year — no tuning between regimes:</div>
    """, unsafe_allow_html=True)

    # Regime + risk metrics via HTML grids
    regime_cards = ""
    for p in bt["periods"]:
        bc  = "rgba(29,158,117,.35)" if p["beat"] else "rgba(226,75,74,.25)"
        ic  = "#1D9E75" if p["beat"] else "#E24B4A"
        mc  = "#1D9E75" if p["model_ret"] >= 0 else "#E24B4A"
        sc  = "#4ade80" if p["spy_ret"]  >= 0 else "#E24B4A"
        chk = "&#10003;" if p["beat"] else "&#10007;"
        regime_cards += (
            f'<div style="background:#0e0f1a;border:1px solid {bc};border-radius:8px;padding:12px 10px;min-width:0;">'
            f'<div style="font-family:DM Mono,monospace;font-size:14px;color:#94a3b8;margin-bottom:3px;">{p["key"]}</div>'
            f'<div style="font-family:Syne,sans-serif;font-size:13px;font-weight:700;color:#94a3b8;margin-bottom:6px;line-height:1.3;">{p["label"]}</div>'
            f'<div style="font-family:Syne,sans-serif;font-size:20px;font-weight:800;color:{ic};">{chk}</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:13px;color:{mc};margin-top:4px;">QNTM {p["model_ret"]:+.1f}%</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:13px;color:{sc};margin-top:2px;">SPY {p["spy_ret"]:+.1f}%</div>'
            f'</div>'
        )
    st.markdown(
        f'<div style="width:100%;box-sizing:border-box;padding:0 16px;margin-bottom:24px;"><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;">{regime_cards}</div></div>',
        unsafe_allow_html=True)

    spy_dd = bt.get("max_dd_spy", -25.4)
    risk_items = [
        ("SHARPE",     f"{bt['sharpe']:.2f}",                     "&gt;1.0 excellent"),
        ("SORTINO",    f"{bt['sortino']:.2f}",                    "&gt;1.5 strong"),
        ("INFO RATIO", f"{bt.get('information_ratio',1.25):.2f}", "&gt;0.5 signal"),
        ("MAX DD",     f"{bt['max_dd_model']:.1f}%",              f"SPY {spy_dd:.1f}%"),
        ("WIN RATE",   f"{bt['win_rate']:.1f}%",                  f"{bt['n_quarters']} quarters"),
        ("CAGR ALPHA", f"+{bt['cagr_alpha']:.1f}pp",              "/yr vs index"),
    ]
    risk_html = "".join([
        f'<div style="background:rgba(212,168,67,.05);border:1px solid rgba(212,168,67,.15);'
        f'border-radius:6px;padding:12px;text-align:center;min-width:0;">'
        f'<div style="font-family:DM Mono,monospace;font-size:14px;color:#94a3b8;letter-spacing:.08em;margin-bottom:6px;">{l}</div>'
        f'<div style="font-family:Syne,sans-serif;font-size:20px;font-weight:800;color:#d4a843;">{v}</div>'
        f'<div style="font-size:13px;color:#94a3b8;margin-top:4px;">{s}</div></div>'
        for l,v,s in risk_items
    ])
    st.markdown(
        f'<div style="width:100%;box-sizing:border-box;padding:0 16px;margin-bottom:16px;"><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;">{risk_html}</div></div>',
        unsafe_allow_html=True)

    # ── VS COMPETITORS BAR ────────────────────────────────────────────────────
    vs_data = [
        ("QNTM Model",        447000, "#d4a843"),
        ("Typical Quant Fund",310000, "#475569"),
        ("SPY (Index)",        231000, "#334155"),
        ("Retail Avg",         162000, "#1e293b"),
    ]
    max_val = 447000
    bars = ""
    for name, val, color in vs_data:
        pct = val / max_val * 100
        bars += (
            f'<div style="margin-bottom:10px;">'            f'<div style="display:flex;justify-content:space-between;margin-bottom:3px;">'            f'<span style="font-size:12px;color:#94a3b8;">{name}</span>'            f'<span style="font-family:DM Mono,monospace;font-size:12px;color:#cbd5e1;">${val:,}</span>'            f'</div>'            f'<div style="background:rgba(255,255,255,.05);border-radius:3px;height:8px;">'            f'<div style="width:{pct:.0f}%;height:100%;background:{color};border-radius:3px;"></div>'            f'</div></div>'
        )
    st.markdown(
        f'<div style="width:100%;box-sizing:border-box;padding:0 16px;margin-bottom:8px;">'        f'<div style="background:#0a0b14;border:1px solid rgba(255,255,255,.07);border-radius:8px;padding:20px 18px;">'        f'<div style="font-family:DM Mono,monospace;font-size:11px;color:#64748b;letter-spacing:.08em;margin-bottom:16px;">$100,000 INVESTED — 5 YEAR OUTCOME</div>'        f'{bars}'        f'<div style="font-size:11px;color:#475569;margin-top:12px;border-top:1px solid rgba(255,255,255,.05);padding-top:10px;">Q2 2020 – Q1 2025. Typical quant fund estimated at 1.25× SPY return. Retail avg estimated at 0.7× SPY. Past performance does not guarantee future results.</div>'        f'</div></div>',
        unsafe_allow_html=True)

        # ── THE MODEL ─────────────────────────────────────────────────────────────
    st.markdown("""
    <div class="land-divider" style="margin-top:32px;"></div>
    <div class="land-section">
      <div style="font-family:'DM Mono',monospace;font-size:13px;color:#d4a843;letter-spacing:.2em;margin-bottom:14px;">&mdash; THE MODEL</div>
      <h2 style="font-family:'Syne',sans-serif;font-size:clamp(28px,4vw,42px);font-weight:800;
           color:#fff;margin-bottom:12px;line-height:1.1;">
        Five pillars.<br><span style="color:#d4a843;">One conviction score.</span>
      </h2>
      <p style="color:#94a3b8;max-width:520px;margin-bottom:36px;line-height:1.7;">
        36 factors scored weekly across 5 research-backed pillars — plus a 75/25 macro overlay.
        The model tells you exactly what to enter, maintain, or exit. And why.
      </p>
    </div>
    """, unsafe_allow_html=True)

    pillars_html = ""
    for name, weight, desc, color in [
        ("Momentum",  "30%", "Price trend, RSI, MACD, MA crossovers, 52-week proximity",      "#d4a843"),
        ("Quality",   "25%", "ROE, profit margin, revenue growth, EPS beat rate, FCF yield",   "#1D9E75"),
        ("Volume",    "20%", "Relative volume, OBV, Chaikin Money Flow, accumulation/dist.",   "#00ff87"),
        ("Value",     "15%", "Forward P/E, PEG ratio, EV/EBITDA, Price-to-Sales, FCF yield",  "#f59e0b"),
        ("Sentiment", "10%", "Short interest, insider buy ratio, institutional ownership",      "#f97316"),
    ]:
        pillars_html += (
            f'<div style="background:#0e0f1a;border:1px solid rgba(255,255,255,.07);border-radius:8px;padding:18px 14px;">'
            f'<div style="font-family:Syne,sans-serif;font-size:26px;font-weight:800;color:{color};margin-bottom:4px;">{weight}</div>'
            f'<div style="font-family:Syne,sans-serif;font-size:13px;font-weight:700;color:#e2e4f0;margin-bottom:8px;">{name}</div>'
            f'<div style="font-size:13px;color:#94a3b8;line-height:1.6;">{desc}</div>'
            f'</div>'
        )
    st.markdown(
        f'<div style="width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;padding:0 16px;box-sizing:border-box;">'
        f'<div style="display:grid;grid-template-columns:repeat(5,minmax(140px,1fr));gap:10px;min-width:600px;">'
        f'{pillars_html}</div></div>',
        unsafe_allow_html=True)

    # Signal boxes — pure CSS grid, no st.columns
    st.markdown('<div style="height:16px;"></div>', unsafe_allow_html=True)
    signals_html = ""
    for label, score, desc, color, brd in [
        ("▲ HIGH",        "Score ≥ 60", "Enter position. Hold until exit signal fires. Designed for LTCG tax treatment — 12+ month holds.", "#1D9E75", "rgba(29,158,117,.3)"),
        ("─ MODERATE",    "Score 45–59", "Maintain existing positions. No new capital deployed. Monitor for further deterioration.",           "#f59e0b", "rgba(245,158,11,.25)"),
        ("▼ EXIT SIGNAL", "Score < 45",  "Exit or reduce. This caught UNH at month 3 — avoided the −49% full-year drawdown.",                "#E24B4A", "rgba(226,75,74,.25)"),
    ]:
        signals_html += (
            f'<div style="background:#0e0f1a;border:1px solid {brd};border-radius:8px;padding:22px;">'
            f'<div style="font-family:Syne,sans-serif;font-size:12px;font-weight:700;color:{color};letter-spacing:.1em;margin-bottom:8px;">{label}</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:22px;font-weight:500;color:{color};margin-bottom:10px;">{score}</div>'
            f'<div style="font-size:15px;color:#cbd5e1;line-height:1.8;">{desc}</div>'
            f'</div>'
        )
    st.markdown(
        f'<div style="width:100%;box-sizing:border-box;padding:0 16px;"><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;">{signals_html}</div></div>',
        unsafe_allow_html=True)


    # ── COMPETITOR MATRIX ─────────────────────────────────────────────────────
    st.markdown("""
    <div class="land-divider" style="margin-top:32px;"></div>
    <div class="land-section">
      <div style="font-family:'DM Mono',monospace;font-size:13px;color:#d4a843;letter-spacing:.2em;margin-bottom:14px;">&mdash; VS THE MARKET</div>
      <h2 style="font-family:'Syne',sans-serif;font-size:clamp(28px,4vw,42px);font-weight:800;
           color:#fff;margin-bottom:10px;line-height:1.1;">
        Institutional tools.<br><span style="color:#d4a843;">Retail price.</span>
      </h2>
      <p style="color:#94a3b8;margin-bottom:32px;">Everything Bloomberg does for quant signals — at 1% of the cost.</p>
    </div>
    """, unsafe_allow_html=True)

    def chk(v):
        if v == 1:  return '<span style="color:#1D9E75;font-size:15px;">&#10003;</span>'
        if v == 0:  return '<span style="color:#E24B4A;font-size:15px;">&#10007;</span>'
        return '<span style="color:#f59e0b;font-size:12px;">partial</span>'

    matrix_rows = [
        ("Price / month",          ["$29","$199","$299","$249","$49","$2,700+"]),
        ("Quant factor model",      [1, 0, "p", "p", "p", 1]),
        ("Live macro overlay",      [1, 0, 0, 0, 0, 1]),
        ("5-pillar conviction score",[1, 0, 0, "p", "p", 1]),
        ("Walk-forward backtest",   [1, 0, 0, 0, 0, 1]),
        ("Hidden gem detection",    [1, 0, 0, 0, 0, 0]),
        ("Portfolio simulator",     [1, 0, 0, "p", 0, 1]),
        ("Live model portfolio",    [1, 1, 0, 0, 0, 0]),
        ("15-min intraday refresh", [1, 0, 0, 0, "p", 1]),
        ("834-stock universe",      [1, "p", 1, 1, 1, 1]),
        ("Free tier available",     [1, 0, 0, 0, "p", 0]),
        ("Mobile native",           [1, 1, 1, "p", 1, 0]),
    ]

    cols_h = ["", "QNTM", "Motley Fool", "Seeking Alpha", "Morningstar", "TipRanks", "Bloomberg"]
    col_w  = ["35%", "11%", "11%", "11%", "11%", "11%", "10%"]

    header_html = "".join([
        f'<th style="width:{col_w[i]};padding:8px 6px;font-family:DM Mono,monospace;font-size:10px;'
        f'color:{"#d4a843" if c=="QNTM" else "#64748b"};letter-spacing:.06em;'
        f'text-align:{"left" if i==0 else "center"};border-bottom:1px solid rgba(255,255,255,.08);">'
        f'{c}</th>'
        for i,c in enumerate(cols_h)
    ])

    rows_html = ""
    for ri, (label, vals) in enumerate(matrix_rows):
        bg = "rgba(212,168,67,.04)" if ri % 2 == 0 else "transparent"
        row = f'<tr style="background:{bg};">'
        row += f'<td style="padding:8px 6px;font-size:12px;color:#94a3b8;">{label}</td>'
        for ci, v in enumerate(vals):
            is_qntm = ci == 0
            if isinstance(v, str) and v.startswith("$"):
                cell = f'<span style="font-family:DM Mono,monospace;font-size:11px;color:{"#d4a843" if is_qntm else "#475569"};">{v}</span>'
            elif v == "p":
                cell = chk("p")
            else:
                cell = chk(v)
            fw = "font-weight:700;" if is_qntm else ""
            row += f'<td style="text-align:center;padding:8px 4px;{fw}">{cell}</td>'
        row += "</tr>"
        rows_html += row

    matrix_html = (
        f'<div style="width:100%;box-sizing:border-box;padding:0 12px;margin-bottom:8px;overflow-x:auto;-webkit-overflow-scrolling:touch;">'
        f'<table style="width:100%;min-width:580px;border-collapse:collapse;background:#0a0b14;'
        f'border:1px solid rgba(255,255,255,.07);border-radius:8px;overflow:hidden;">'
        f'<thead><tr>{header_html}</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table>'
        f'<div style="font-size:11px;color:#475569;margin-top:8px;padding:0 2px;">'
        f'Competitor features and pricing based on publicly available information May 2026. Partial = limited implementation.</div>'
        f'</div>'
    )
    st.markdown(matrix_html, unsafe_allow_html=True)

    # ── PRICING ───────────────────────────────────────────────────────────────
    st.markdown("""
    <div class="land-divider" style="margin-top:32px;"></div>
    <div class="land-section">
      <div style="font-family:'DM Mono',monospace;font-size:13px;color:#d4a843;letter-spacing:.2em;margin-bottom:14px;">&mdash; PRICING</div>
      <h2 style="font-family:'Syne',sans-serif;font-size:clamp(28px,4vw,42px);font-weight:800;
           color:#fff;margin-bottom:10px;line-height:1.1;">
        Two tiers.<br><span style="color:#d4a843;">Both built for serious investors.</span>
      </h2>
      <p style="color:#94a3b8;margin-bottom:36px;">First 50 users get Founding Member access free — unlimited everything.</p>
    </div>
    """, unsafe_allow_html=True)

    def feat_row(text, highlight=False):
        dot = "●" if highlight else "○"
        dc  = "#1D9E75" if highlight else "#475569"
        tc  = "#e2e4f0" if highlight else "#64748b"
        return f'<div style="display:flex;align-items:flex-start;gap:6px;padding:3px 0;font-size:13px;"><span style="color:{dc};flex-shrink:0;">{dot}</span><span style="color:{tc};">{text}</span></div>'

    bt_ret_str = f"{bt['model_total_ret']:.0f}"

    def card_style(highlight=False):
        if highlight:
            return "background:rgba(212,168,67,.04);border:2px solid rgba(212,168,67,.5);border-radius:10px;padding:16px 12px;min-width:0;overflow:hidden;"
        return "background:#0e0f1a;border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:16px 12px;min-width:0;overflow:hidden;"

    free_card = f"""
      <div style="{card_style()}">
        <div style="font-family:Syne,sans-serif;font-size:13px;font-weight:700;color:#94a3b8;letter-spacing:.08em;margin-bottom:8px;">FREE</div>
        <div style="font-family:Syne,sans-serif;font-size:26px;font-weight:800;color:#e2e4f0;line-height:1;">$0</div>
        <div style="font-size:13px;color:#94a3b8;margin-bottom:14px;margin-top:3px;">forever · no card needed</div>
        <div style="border-top:1px solid rgba(255,255,255,.06);padding-top:12px;">
          {feat_row("834-stock screener")}
          {feat_row("HIGH / MOD / LOW conviction signals")}
          {feat_row("5-pillar score breakdown")}
          {feat_row("Live macro regime overlay")}
          {feat_row("Top 10 daily picks")}
          {feat_row("Portfolio tracking (10 positions)")}
          {feat_row("Backtest track record (read only)")}
          {feat_row("Walk-forward validated model")}
        </div>
      </div>"""

    founding_card = f"""
      <div style="{card_style(True)}">
        <div style="background:#d4a843;color:#000;font-family:Syne,sans-serif;font-size:8px;font-weight:700;letter-spacing:.08em;padding:2px 8px;border-radius:2px;display:inline-block;margin-bottom:8px;">MOST POPULAR</div>
        <div style="font-family:Syne,sans-serif;font-size:13px;font-weight:700;color:#94a3b8;letter-spacing:.08em;margin-bottom:8px;">PRO</div>
        <div style="font-family:Syne,sans-serif;font-size:26px;font-weight:800;color:#d4a843;line-height:1;">$29<span style="font-size:14px;font-weight:500;color:#94a3b8;">/mo</span></div>
        <div style="font-size:13px;color:#94a3b8;margin-bottom:14px;margin-top:3px;">first 50 users get it free</div>
        <div style="border-top:1px solid rgba(255,255,255,.06);padding-top:12px;">
          {feat_row("Everything in Free", True)}
          {feat_row("Unlimited portfolio positions", True)}
          {feat_row("Hidden Gems detection", True)}
          {feat_row("Portfolio Simulator (risk profiles)", True)}
          {feat_row("15-min intraday price refresh", True)}
          {feat_row("Signal change alerts", True)}
          {feat_row("Email notifications", True)}
          {feat_row("Founding member badge", True)}
        </div>
      </div>"""

    inst_card = f"""
      <div style="{card_style()}">
        <div style="font-family:Syne,sans-serif;font-size:13px;font-weight:700;color:#94a3b8;letter-spacing:.08em;margin-bottom:8px;">INSTITUTIONAL</div>
        <div style="font-family:Syne,sans-serif;font-size:clamp(16px,3.5vw,26px);font-weight:800;color:#e2e4f0;line-height:1;white-space:nowrap;">Custom</div>
        <div style="font-size:13px;color:#94a3b8;margin-bottom:14px;margin-top:3px;">contact us</div>
        <div style="border-top:1px solid rgba(255,255,255,.06);padding-top:12px;">
          {feat_row("Everything in Pro", True)}
          {feat_row("API access", True)}
          {feat_row("Custom universe", True)}
          {feat_row("White-label option", True)}
          {feat_row("Dedicated support", True)}
          {feat_row("Multi-user accounts", True)}
        </div>
      </div>"""

    st.markdown(
        f'<div style="width:100%;box-sizing:border-box;padding:0 12px;margin-bottom:16px;">'
        f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;">'
        f'{free_card}{founding_card}{inst_card}'
        f'</div></div>',
        unsafe_allow_html=True)

    pb1, pb2, pb3 = st.columns(3)
    with pb1:
        st.markdown(_cta_ghost("Start Free →", "?nav=register"), unsafe_allow_html=True)
    with pb2:
        st.markdown(_cta_gold("Claim Founding Spot →", "?nav=register"), unsafe_allow_html=True)
    with pb3:
        st.markdown(_cta_gold("Get Pro — $29/mo", "?nav=register"), unsafe_allow_html=True)

    # ── FOOTER ────────────────────────────────────────────────────────────────
    st.markdown("""
    <div class="land-divider" style="margin-top:32px;"></div>
    <div style="background:#080910;padding:48px clamp(16px,4vw,48px) 40px;">
      <div style="max-width:1200px;margin:0 auto;display:flex;justify-content:space-between;
           align-items:flex-start;flex-wrap:wrap;gap:32px;margin-bottom:32px;">
        <div>
          <div style="font-family:'Syne',sans-serif;font-size:20px;font-weight:800;
               color:#e2e4f0;margin-bottom:6px;">Q<span style="color:#d4a843;">NTM</span></div>
          <div style="font-size:14px;color:#94a3b8;line-height:1.7;max-width:280px;">
            Quantitative conviction factor model platform.<br>
            Institutional-grade research for retail investors.
          </div>
        </div>
        <div style="display:flex;gap:48px;flex-wrap:wrap;">
          <div>
            <div style="font-family:'DM Mono',monospace;font-size:13px;color:#64748b;letter-spacing:.12em;margin-bottom:12px;">LEGAL</div>
            <div style="font-size:13px;color:#94a3b8;line-height:2.2;">
              <a href="?legal=privacy" style="color:#94a3b8;text-decoration:none;display:block;">Privacy Policy</a>
              <a href="?legal=terms" style="color:#94a3b8;text-decoration:none;display:block;">Terms of Service</a>
              <a href="?legal=cookies" style="color:#94a3b8;text-decoration:none;display:block;">Cookie Policy</a>
            </div>
          </div>
          <div>
            <div style="font-family:'DM Mono',monospace;font-size:13px;color:#64748b;letter-spacing:.12em;margin-bottom:12px;">CONTACT</div>
            <div style="font-size:13px;color:#94a3b8;line-height:2.2;">
              <a href="mailto:hello@qntm.app" style="color:#94a3b8;text-decoration:none;display:block;">hello@qntm.app</a>
            </div>
          </div>
        </div>
      </div>
      <div style="background:rgba(212,168,67,.05);border:1px solid rgba(212,168,67,.15);
           border-radius:8px;padding:18px 22px;margin-bottom:28px;max-width:1200px;margin-left:auto;margin-right:auto;">
        <div style="font-family:'DM Mono',monospace;font-size:13px;color:#d4a843;letter-spacing:.12em;margin-bottom:8px;">IMPORTANT DISCLAIMER</div>
        <div style="font-size:12px;color:#64748b;line-height:1.8;">
          QNTM is a <strong style="color:#94a3b8;">quantitative research and factor analysis tool</strong>
          for informational and educational purposes only. It does <strong style="color:#94a3b8;">not</strong>
          constitute investment advice, a recommendation to buy or sell any security, or a guarantee of
          future performance. Past model performance does not predict future results. All investments
          involve risk including possible loss of principal. Always consult a qualified financial adviser.
        </div>
      </div>
      <div style="max-width:1200px;margin:0 auto;display:flex;justify-content:space-between;
           align-items:center;flex-wrap:wrap;gap:12px;padding-top:20px;
           border-top:1px solid rgba(255,255,255,.05);">
        <div style="font-size:13px;color:#94a3b8;">&copy; 2025 QNTM. All rights reserved.</div>
        <div style="font-size:13px;color:#94a3b8;">
          Not investment advice &middot; Quantitative research tool only
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    cookie_banner()


def page_auth():
    # Full-page background gradient
    st.markdown("""
    <div style="position:fixed;inset:0;background:radial-gradient(ellipse 70% 50% at 50% -10%,
         rgba(0,255,135,.06) 0%,transparent 65%);pointer-events:none;z-index:0;"></div>
    <style>
    /* Auth tab buttons — full width, equal size, active state highlighted */
    div[data-testid="column"] .stButton > button {
        border-radius: 0 !important;
        border: none !important;
        border-bottom: 2px solid rgba(255,255,255,.08) !important;
        background: transparent !important;
        color: #64748b !important;
        font-size: 12px !important;
        font-weight: 700 !important;
        letter-spacing: .04em !important;
        text-transform: uppercase !important;
        height: 44px !important;
        min-height: 44px !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: clip !important;
        padding: 0 8px !important;
    }
    div[data-testid="column"] .stButton > button:hover {
        background: rgba(0,255,135,.05) !important;
        border-bottom-color: rgba(0,255,135,.4) !important;
        color: #94a3b8 !important;
        transform: none !important;
    }
    </style>
    """, unsafe_allow_html=True)

    col_back, col_center, col_right = st.columns([1, 2, 1])
    with col_back:
        st.markdown('<div style="padding:24px 0 0 24px;">', unsafe_allow_html=True)
        if st.button("← Back", key="auth_back"):
            go("landing")
        st.markdown('</div>', unsafe_allow_html=True)

    with col_center:
        st.markdown("""
        <div style="text-align:center;padding:48px 0 36px;">
          <div style="font-family:'Syne',sans-serif;font-size:32px;font-weight:800;
               letter-spacing:.15em;color:#e2e4f0;">Q<span style="color:#00ff87;">NTM</span></div>
          <div style="font-size:13px;color:#64748b;letter-spacing:.2em;margin-top:6px;">
            CONVICTION FACTOR MODEL
          </div>
        </div>
        """, unsafe_allow_html=True)

        # Tab selection — stored in session so it survives reruns
        if "auth_tab" not in st.session_state:
            st.session_state.auth_tab = "signin"

        t1_label = "▶ Sign In" if st.session_state.auth_tab == "signin" else "Sign In"
        t2_label = "▶ Join Free" if st.session_state.auth_tab == "register" else "Join Free"
        tc1, tc2 = st.columns(2)
        with tc1:
            if st.button(t1_label, key="tab_signin_btn", use_container_width=True):
                st.session_state.auth_tab = "signin"
                st.rerun()
        with tc2:
            if st.button(t2_label, key="tab_register_btn", use_container_width=True):
                st.session_state.auth_tab = "register"
                st.rerun()

        if st.session_state.auth_tab == "signin":
            st.markdown('<div style="height:12px;"></div>', unsafe_allow_html=True)

            si_email = st.text_input("Email address", key="si_email",
                                     placeholder="you@example.com")
            si_pass  = st.text_input("Password", type="password", key="si_pass",
                                     placeholder="••••••••")
            st.markdown('<div style="height:10px;"></div>', unsafe_allow_html=True)

            if st.button("Sign In →", key="si_btn", use_container_width=True):
                if not si_email or not si_pass:
                    st.error("Enter your email and password")
                else:
                    with st.spinner("Authenticating..."):
                        res = login_user(si_email, si_pass)
                    if res["success"]:
                        user = res["user"]
                        mfa  = get_user_mfa(user["id"])
                        if mfa.get("mfa_enabled") and mfa.get("totp_secret"):
                            st.session_state.pending_mfa_user   = user
                            st.session_state.pending_mfa_secret = mfa["totp_secret"]
                            go("mfa")
                        else:
                            st.session_state.logged_in    = True
                            st.session_state.user         = user
                            st.session_state.mfa_verified = True
                            st.session_state.scan_results = None
                            # Only prompt MFA if never offered before
                            if not user.get("mfa_offered"):
                                st.session_state.force_mfa_setup = True
                            # Always persist — signed 30-day token
                            _signed = _sign_token(user["id"], user.get("plan","free"))
                            st.query_params["uid"]  = _signed
                            st.query_params["plan"] = user.get("plan","free")
                            _write_localstorage_token(user["id"], user.get("plan","free"))
                            st.session_state.nav = "screener"

                            go("platform")
                    else:
                        st.error(res.get("error", "Invalid email or password"))

            st.markdown("""
            <div style="text-align:center;margin-top:20px;">
              <span style="font-size:14px;color:#94a3b8;">
                No account? Hit <strong style="color:#00ff87;">Join Free</strong> above.
              </span>
            </div>
            """, unsafe_allow_html=True)

        # ── REGISTER ──────────────────────────────────────────────────────────
        else:
            st.markdown('<div style="height:12px;"></div>', unsafe_allow_html=True)

            # Plan selection
            st.markdown("""
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:20px;">
              <div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.08);
                   border-radius:6px;padding:14px;text-align:center;">
                <div style="font-family:'Syne',sans-serif;font-size:12px;font-weight:700;
                     color:#94a3b8;letter-spacing:.08em;margin-bottom:4px;">FREE</div>
                <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:#e2e4f0;">$0</div>
                <div style="font-size:13px;color:#94a3b8;margin-top:4px;">forever</div>
                <div style="font-size:13px;color:#94a3b8;margin-top:8px;line-height:1.6;">
                  Screener · HIGH/MODERATE/LOW conviction signals<br>Up to 10 portfolio positions<br>5-yr backtest data
                </div>
              </div>
              <div style="background:rgba(212,168,67,.05);border:1px solid rgba(212,168,67,.4);
                   border-radius:6px;padding:14px;text-align:center;">
                <div style="background:#d4a843;color:#000;font-size:12px;font-weight:700;
                     letter-spacing:.1em;padding:2px 8px;border-radius:2px;display:inline-block;
                     margin-bottom:4px;">FOUNDING MEMBER</div>
                <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:#d4a843;">$0</div>
                <div style="font-size:13px;color:#94a3b8;margin-top:4px;">first 50 users · then $29/mo</div>
                <div style="font-size:13px;color:#94a3b8;margin-top:8px;line-height:1.6;">
                  Unlimited holdings · Hidden Gems<br>Signal alerts · Email notifications<br>Priority support
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)

            rg_name  = st.text_input("Full name",         key="rg_name",  placeholder="Your name")
            rg_email = st.text_input("Email address",     key="rg_email", placeholder="you@example.com")
            rg_pass  = st.text_input("Password",          key="rg_pass",  placeholder="Min 8 characters",
                                     type="password")
            rg_pass2 = st.text_input("Confirm password",  key="rg_pass2", placeholder="Repeat password",
                                     type="password")
            rg_agree = st.checkbox(
                "I understand QNTM is a quantitative research tool, not investment advice",
                key="rg_agree"
            )
            st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)

            if st.button("Create Free Account →", key="rg_btn", use_container_width=True):
                if not rg_agree:
                    st.error("Please acknowledge the disclaimer to continue")
                elif not rg_name or not rg_name.strip():
                    st.error("Enter your full name")
                elif not rg_email or "@" not in rg_email:
                    st.error("Enter a valid email address")
                elif rg_pass != rg_pass2:
                    st.error("Passwords don't match")
                elif len(rg_pass) < 8:
                    st.error("Password must be at least 8 characters")
                else:
                    with st.spinner("Creating account..."):
                        res = register_user(rg_email, rg_pass, rg_name)
                    if res["success"]:
                        # Auto-upgrade if came from Founding Member CTA
                        if st.session_state.get("auto_upgrade"):
                            upgrade_plan(res["user_id"], "pro")
                            st.session_state.auto_upgrade = False
                            msg = "✓ Founding Member spot claimed! Full Pro access is active."
                            tag = "🏆 Founding Member"
                        else:
                            msg = "✓ Account created. Sign in above to continue."
                            tag = ""
                        st.markdown(f"""
                        <div style="background:rgba(0,255,135,.06);border:1px solid rgba(0,255,135,.25);
                             border-radius:6px;padding:14px 16px;font-size:13px;color:#00ff87;margin-top:8px;">
                          {msg}
                          {'<div style="font-size:13px;color:#d4a843;margin-top:4px;">' + tag + ' — unlimited holdings, hidden gems &amp; alerts are live.</div>' if tag else ''}
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.error(res.get("error", "Registration failed — please try again"))

        st.markdown('<div style="height:24px;"></div>', unsafe_allow_html=True)
        st.markdown(DISCLAIMER, unsafe_allow_html=True)

    # Legal footer — 2x2 grid, always fits any screen width
    st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)
    r1c1, r1c2 = st.columns(2)
    r2c1, r2c2 = st.columns(2)
    link_style = (
        "display:block;text-align:center;font-family:'DM Mono',monospace;"
        "font-size:11px;letter-spacing:.07em;color:#64748b;text-decoration:none;"
        "border:1px solid rgba(100,116,139,.2);border-radius:4px;padding:8px 4px;"
    )
    with r1c1:
        st.markdown(f'<a href="?legal=privacy" style="{link_style}">PRIVACY POLICY</a>', unsafe_allow_html=True)
    with r1c2:
        st.markdown(f'<a href="?legal=terms" style="{link_style}">TERMS OF SERVICE</a>', unsafe_allow_html=True)
    with r2c1:
        st.markdown(f'<a href="?legal=disclaimer" style="{link_style}">INVESTMENT DISCLAIMER</a>', unsafe_allow_html=True)
    with r2c2:
        st.markdown(f'<a href="?legal=cookies" style="{link_style}">COOKIE POLICY</a>', unsafe_allow_html=True)
    st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)

    cookie_banner()


# ══════════════════════════════════════════════════════════════════════════════
# MFA PAGE
# ══════════════════════════════════════════════════════════════════════════════
def page_mfa():
    _, col, _ = st.columns([1,2,1])
    with col:
        st.markdown("""
        <div style="text-align:center;padding:80px 0 40px;">
          <div style="font-family:'Syne',sans-serif;font-size:28px;font-weight:800;">
            Q<span style="color:#00ff87;">NTM</span>
          </div>
          <div style="margin-top:32px;font-size:36px;">🔐</div>
          <h2 style="font-family:'Syne',sans-serif;font-size:24px;font-weight:700;margin-top:12px;">Two-Factor Auth</h2>
          <p style="color:#94a3b8;margin-top:8px;">Enter the 6-digit code from your authenticator app</p>
        </div>
        """, unsafe_allow_html=True)

        # ── Normal MFA verification ───────────────────────────────────────────
        if not st.session_state.get("mfa_recovery_mode"):
            code = st.text_input("Authentication Code", max_chars=6, placeholder="000000", key="mfa_code")
            if st.button("Verify & Enter →", key="mfa_verify", use_container_width=True):
                if verify_totp(st.session_state.pending_mfa_secret, code):
                    user = st.session_state.pending_mfa_user
                    st.session_state.logged_in    = True
                    st.session_state.user         = user
                    st.session_state.mfa_verified = True
                    # Always persist — signed 30-day token
                    _signed = _sign_token(user["id"], user.get("plan","free"))
                    st.query_params["uid"]  = _signed
                    st.query_params["plan"] = user.get("plan","free")
                    _write_localstorage_token(user["id"], user.get("plan","free"))
                    st.session_state.nav = "screener"

                    go("platform")
                else:
                    st.error("Invalid code — check your app and try again")

            st.markdown('<div style="height:16px;"></div>', unsafe_allow_html=True)
            if st.button("← Back to sign in", key="mfa_back"):
                go("auth")

            # Recovery option
            st.markdown("""
            <div style="margin-top:24px;padding-top:20px;border-top:1px solid rgba(255,255,255,.06);
                 text-align:center;">
              <p style="font-size:14px;color:#94a3b8;">Lost access to your authenticator app?</p>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Reset 2FA with password →", key="mfa_recovery_btn", use_container_width=True):
                st.session_state.mfa_recovery_mode = True
                st.rerun()

        # ── MFA Recovery — verify password, then re-enroll ───────────────────
        else:
            st.markdown("""
            <div style="background:rgba(212,168,67,.06);border:1px solid rgba(212,168,67,.2);
                 border-radius:6px;padding:12px 16px;margin-bottom:16px;font-size:14px;color:#94a3b8;">
              Verify your password to disable 2FA and set up a new authenticator.
            </div>
            """, unsafe_allow_html=True)

            recovery_pw = st.text_input("Your Password", type="password", key="mfa_recovery_pw")

            if st.button("Verify Password & Reset 2FA", key="mfa_recovery_verify", use_container_width=True):
                if recovery_pw:
                    # Re-authenticate with password
                    user_data = st.session_state.get("pending_mfa_user", {})
                    email     = user_data.get("email", "")
                    result    = login_user(email, recovery_pw)
                    if result.get("success"):
                        # Disable MFA so they can re-enroll
                        disable_mfa(user_data.get("id",""))
                        # Log them in
                        st.session_state.logged_in          = True
                        st.session_state.user               = user_data
                        st.session_state.mfa_verified       = True
                        st.session_state.mfa_recovery_mode  = False
                        st.session_state.show_mfa_setup     = True   # trigger re-enroll flow
                        st.success("2FA reset. Setting up new authenticator...")
                        import time; time.sleep(1)
                        st.session_state.nav = "screener"

                        go("platform")
                    else:
                        st.error("Incorrect password — try again")
                else:
                    st.warning("Enter your password to continue")

            st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)
            if st.button("← Back", key="mfa_recovery_back"):
                st.session_state.mfa_recovery_mode = False
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PLATFORM — TOP NAV
# ══════════════════════════════════════════════════════════════════════════════
def platform_nav():
    user  = st.session_state.user or {}
    plan  = user.get("plan","free")
    n_count = get_unread_count(uid()) if plan in ("pro","institutional") else 0
    plan_color = "#00ff87" if plan in ("pro","institutional") else "#94a3b8"
    plan_rgb = "0,255,135" if plan=="pro" else "249,115,22" if plan=="institutional" else "148,163,184"
    display_name = (user.get("full_name") or "").split()[0] if user.get("full_name") else ""
    if not display_name:
        em = user.get("email","")
        display_name = em[:14] + ("..." if len(em) > 14 else "")

    cur_nav = st.session_state.get("nav","screener")
    nav_items = [
        ("screener",        "📊", "Screener"),
        ("watchlist",       "★",  "Watchlist"),
        ("gems",            "💎", "Hidden Gems"),
        ("backtest",        "📈", "Backtest"),
        ("portfolio",       "💼", "Portfolio"),
        ("simulator",       "🧮", "Simulator"),
        ("model_portfolio", "🏆", "Model Port."),
        ("alerts",          "🔔", "Alerts"),
        ("account",         "⚙️", "Account"),
        ("methodology",     "📖", "How It Works"),
    ]
    cur_em    = next((e for k,e,l in nav_items if k==cur_nav), "📊")
    cur_label = next((l for k,e,l in nav_items if k==cur_nav), "Screener")

    # Session params to preserve across navigation
    # Always read uid from session state — query params may be empty after pop
    _uid_val  = (st.session_state.user or {}).get("id", "")
    _plan_val = user.get("plan","free")
    qp_suffix = f"&plan={_plan_val}&ck=1"
    if _uid_val:
        qp_suffix = f"&uid={_uid_val}" + qp_suffix

    # Build the 3-col grid of box buttons
    grid_html = '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding:14px 16px 16px;">'
    for key, em, label in nav_items:
        href = f"?qnav={key}{qp_suffix}"
        if key == cur_nav:
            btn_style = (
                'display:flex;flex-direction:column;align-items:center;justify-content:center;'
                'gap:6px;padding:14px 8px;text-decoration:none;border-radius:8px;'
                'background:linear-gradient(135deg,rgba(0,255,135,.14),rgba(0,255,135,.04));'
                'border:1px solid rgba(0,255,135,.5);'
                'box-shadow:0 0 12px rgba(0,255,135,.1);'
            )
            em_style  = 'font-size:20px;line-height:1;'
            lbl_style = ('font-family:Syne,sans-serif;font-size:9px;font-weight:700;'
                         'letter-spacing:.03em;text-transform:uppercase;color:#00ff87;'
                         'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:96%;text-align:center;')
        else:
            btn_style = (
                'display:flex;flex-direction:column;align-items:center;justify-content:center;'
                'gap:6px;padding:14px 8px;text-decoration:none;border-radius:8px;'
                'background:rgba(255,255,255,.07);'
                'border:1px solid rgba(255,255,255,.15);'
                'transition:all .18s ease;'
            )
            em_style  = 'font-size:22px;line-height:1;'
            lbl_style = ('font-family:Syne,sans-serif;font-size:9px;font-weight:700;'
                         'letter-spacing:.03em;text-transform:uppercase;color:#94a3b8;'
                         'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:96%;text-align:center;')

        badge = (
            f'<span style="position:absolute;top:6px;right:6px;background:#ef4444;color:#fff;'
            f'border-radius:50%;width:14px;height:14px;display:flex;align-items:center;'
            f'justify-content:center;font-size:8px;font-weight:700;">{n_count}</span>'
        ) if (key == "alerts" and n_count > 0) else ""

        grid_html += (
            f'<a href="{href}" target="_self" style="position:relative;{btn_style}">'
            f'<span style="{em_style}">{em}</span>'
            f'<span style="{lbl_style}">{label}</span>'
            f'{badge}</a>'
        )

    # Sign out button
    grid_html += (
        f'<a href="?qnav=signout" target="_self" style="'
        f'display:flex;flex-direction:column;align-items:center;justify-content:center;'
        f'gap:6px;padding:14px 8px;text-decoration:none;border-radius:8px;'
        f'background:linear-gradient(135deg,rgba(239,68,68,.08),rgba(239,68,68,.02));'
        f'border:1px solid rgba(239,68,68,.2);">'
        f'<span style="font-size:20px;line-height:1;opacity:.7;">🚪</span>'
        f'<span style="font-family:Syne,sans-serif;font-size:10px;font-weight:600;'
        f'letter-spacing:.05em;text-transform:uppercase;color:#ef4444;">Sign Out</span>'
        f'</a>'
    )
    grid_html += '</div>'

    notif_dot = (
        f'<span style="background:#ef4444;color:#fff;border-radius:50%;width:18px;height:18px;'
        f'display:inline-flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;">'
        f'{n_count}</span>'
    ) if n_count > 0 else ""

    is_dev = os.getenv("ENVIRONMENT") == "dev"
    dd_top = "88px" if is_dev else "56px"

    nav_html = (
        '<style>'
        '#qntm-toggle{display:none;}'
        '#qntm-dd{'
        f'position:fixed;top:{dd_top};left:50%;transform:translateX(-50%);width:340px;'
        'background:rgba(7,10,18,.99);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);'
        'border:1px solid rgba(255,255,255,.1);border-radius:12px;z-index:1000;'
        'max-height:0;overflow:hidden;opacity:0;pointer-events:none;'
        'transition:max-height .3s cubic-bezier(.4,0,.2,1),opacity .22s ease;'
        'box-shadow:0 24px 64px rgba(0,0,0,.8);}'
        '#qntm-toggle:checked ~ #qntm-dd{'
        'max-height:600px;opacity:1;pointer-events:all;}'
        '#qntm-ov{display:none;position:fixed;inset:0;z-index:999;}'
        '#qntm-toggle:checked ~ #qntm-ov{display:block;}'
        '.qntm-menu-trigger{'
        'display:flex;align-items:center;gap:8px;cursor:pointer;'
        'background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.12);'
        'border-radius:8px;padding:8px 14px;'
        'font-family:Syne,sans-serif;font-size:13px;font-weight:600;color:#e2e8f0;'
        'transition:border-color .2s,background .2s;user-select:none;'
        'min-width:170px;justify-content:space-between;}'
        '#qntm-toggle:checked ~ div label.qntm-menu-trigger{'
        'border-color:rgba(0,255,135,.4);background:rgba(0,255,135,.06);}'
        '.qntm-chevron{width:14px;height:14px;opacity:.5;transition:transform .2s;flex-shrink:0;}'
        '#qntm-toggle:checked ~ div label.qntm-menu-trigger .qntm-chevron{'
        'transform:rotate(180deg);}'
        'a[href*="qnav"]:hover{background:linear-gradient(135deg,rgba(0,255,135,.1),rgba(0,255,135,.03))!important;'
        'border-color:rgba(0,255,135,.35)!important;}'
        '</style>'
        '<input type="checkbox" id="qntm-toggle">'
        f'<div id="qntm-dd">'
        '<div style="padding:12px 16px 8px;border-bottom:1px solid rgba(255,255,255,.06);">'
        '<span style="font-family:DM Mono,monospace;font-size:9px;color:#334155;letter-spacing:.14em;">MENU</span>'
        '</div>'
        + grid_html +
        '</div>'
        '<label for="qntm-toggle" id="qntm-ov"></label>'
        '<div style="background:rgba(2,4,8,.97);backdrop-filter:blur(12px);'
        'border-bottom:1px solid rgba(255,255,255,.07);'
        'padding:0 20px;height:56px;display:flex;align-items:center;justify-content:space-between;">'
        '<span style="font-family:Syne,sans-serif;font-size:20px;font-weight:800;'
        'letter-spacing:.15em;color:#e2e8f0;">Q<span style="color:#00ff87;">NTM</span></span>'
        '<label for="qntm-toggle" class="qntm-menu-trigger">'
        '<span>☰  MENU</span>'
        '<svg class="qntm-chevron" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2.5">'
        '<polyline points="6 9 12 15 18 9"/></svg>'
        '</label>'
        '<div style="display:flex;align-items:center;gap:10px;">'
        + notif_dot
        + f'<span style="background:rgba({plan_rgb},.15);color:{plan_color};'
        f'border:1px solid {plan_color}44;border-radius:4px;padding:3px 9px;'
        f'font-size:11px;font-weight:700;letter-spacing:.1em;font-family:Syne,sans-serif;">'
        f'{plan.upper()}</span>'
        f'<span style="font-size:11px;color:#64748b;font-family:DM Mono,monospace;">{display_name}</span>'
        '</div></div>'
    )

    st.markdown(nav_html, unsafe_allow_html=True)


def page_screener():
    from model_engine import (MACRO_EVENT_INFO, score_stock, fetch_price_data,
                               SECTORS as ALL_SECTORS, fetch_macro_overlay, apply_macro_overlay)

    page_summary(
        "📊", "Market Screener",
        "834 tickers across S&P 500 + Russell 1000, scored weekly on Momentum, Quality, Volume, Value, and Sentiment — "
        "then blended with a live macro regime overlay (75/25 quant/macro). "
        "Search any stock for an instant conviction score, or rescan the full universe."
    )
    st.markdown('<div style="padding:0 32px;">', unsafe_allow_html=True)

    # ── Rescan + Last Refresh — top of page ───────────────────────────────────
    data_freshness_banner()
    if st.button("🔄 Rescan Universe", key="rescan_main", use_container_width=True):
        st.session_state.scan_results = None
        st.rerun()


    st.markdown('<div style="height:12px;"></div>', unsafe_allow_html=True)

    # ── Hero search box ───────────────────────────────────────────────────────
    st.markdown("""
    <style>
    div[data-testid="stTextInput"][data-key="screener_search"] input {
        background: rgba(255,255,255,.04) !important;
        border: 2px solid rgba(0,255,135,.4) !important;
        border-radius: 12px !important;
        color: #e2e8f0 !important;
        font-size: 16px !important;
        font-family: 'Syne', sans-serif !important;
        padding: 18px 24px !important;
        height: 60px !important;
        box-shadow: 0 0 32px rgba(0,255,135,.15), inset 0 1px 0 rgba(255,255,255,.06) !important;
        transition: border-color .2s, box-shadow .2s !important;
    }
    div[data-testid="stTextInput"][data-key="screener_search"] input:focus {
        border-color: #00ff87 !important;
        box-shadow: 0 0 56px rgba(0,255,135,.25) !important;
        outline: none !important;
    }
    div[data-testid="stTextInput"][data-key="screener_search"] input::placeholder {
        color: #475569 !important;
        font-size: 15px !important;
    }
    </style>
    <div style="margin-bottom:10px;">
      <div style="font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:#e2e8f0;
           letter-spacing:-.01em;margin-bottom:3px;">
        ⚡ Instant Conviction Score
      </div>
      <div style="font-family:DM Mono,monospace;font-size:12px;color:#475569;letter-spacing:.06em;">
        Search any of 834 stocks — ticker or company name
      </div>
    </div>
    """, unsafe_allow_html=True)
    search_ticker = st.text_input(
        "Search ticker",
        placeholder="🔍  Enter ticker or company name — AAPL, Tesla, Nvidia, Microsoft...",
        key="screener_search",
        label_visibility="collapsed"
    ).strip().upper()
    st.markdown('<div style="height:4px;"></div>', unsafe_allow_html=True)

    if search_ticker:
        # Resolve company name → ticker first
        resolved_tk, resolved_name = resolve_ticker(search_ticker)
        display_query = f"{resolved_name} ({resolved_tk})" if resolved_name and resolved_name != resolved_tk else resolved_tk

        st.markdown(f'<div style="font-family:DM Mono,monospace;font-size:13px;color:#d4a843;letter-spacing:.1em;margin:12px 0 8px;">SCORE FOR {display_query}</div>', unsafe_allow_html=True)
        with st.spinner(f"Scoring {resolved_tk}..."):
            try:
                price_data = fetch_price_data([resolved_tk], period="1y")
                hist = price_data.get(resolved_tk, [])
                if not hist or len(hist) < 10:
                    st.markdown(
                        f'<div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08);'
                        f'border-radius:8px;padding:20px 24px;">'
                        f'<div style="font-family:Syne,sans-serif;font-size:15px;font-weight:700;color:#94a3b8;margin-bottom:6px;">'
                        f'"{search_ticker}" not found</div>'
                        f'<div style="font-size:13px;color:#475569;line-height:1.6;">'
                        f'No price data available. Try the exact ticker symbol — e.g. <strong style="color:#94a3b8;">AAPL</strong>, '
                        f'<strong style="color:#94a3b8;">NVDA</strong>, <strong style="color:#94a3b8;">TSLA</strong>.</div>'
                        f'</div>',
                        unsafe_allow_html=True)
                else:
                    scored = score_stock(resolved_tk, hist)
                    scored["sector"] = ALL_SECTORS.get(resolved_tk, "Unknown")
                    macro = st.session_state.get("macro_data") or fetch_macro_overlay(use_live_feeds=True)
                    scored_list = apply_macro_overlay([scored], macro)
                    sr = scored_list[0]
                    if sr.get("promoted"):
                        from model_engine import EXIT_THRESHOLD
                        regime = macro.get("regime","NEUTRAL")
                        eff_threshold = 62 if regime in ("RISK_OFF","HIGH VOLATILITY") else 60
                        adj = float(sr.get("adj_composite", sr.get("composite", 50)))
                        sr["adj_action"] = "BUY" if adj >= eff_threshold else ("SELL" if adj < EXIT_THRESHOLD else "HOLD")
                        sr["promoted"] = False
                    sr["pct_rank"] = 50
                    ci = get_company_info(resolved_tk)
                    st.markdown(factor_panel_html(sr, False, company_info=ci), unsafe_allow_html=True)
                    # Watchlist — HTML link with action params, same pattern as gems
                    wl = get_watchlist(uid())
                    wl_tickers = {w["ticker"] for w in wl}
                    in_wl = resolved_tk in wl_tickers
                    _uid_val = (st.session_state.user or {}).get("id", "")
                    _plan_val = (st.session_state.user or {}).get("plan", "free")
                    _qp = f"?qnav=screener&uid={_uid_val}&plan={_plan_val}&ck=1"
                    if in_wl:
                        _action_url = _qp + f"&wl_action=remove&wl_ticker={resolved_tk}"
                        st.markdown(
                            f'<a href="{_action_url}" target="_self" style="'
                            f'display:block;width:100%;text-align:center;padding:10px;margin-top:8px;'
                            f'background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.15);'
                            f'border-radius:6px;font-family:Syne,sans-serif;font-size:12px;font-weight:700;'
                            f'letter-spacing:.06em;text-transform:uppercase;color:#e2e8f0;text-decoration:none;'
                            f'box-sizing:border-box;">★ Watchlist</a>',
                            unsafe_allow_html=True
                        )
                    else:
                        _action_url = _qp + f"&wl_action=add&wl_ticker={resolved_tk}"
                        st.markdown(
                            f'<a href="{_action_url}" target="_self" style="'
                            f'display:block;width:100%;text-align:center;padding:10px;margin-top:8px;'
                            f'background:linear-gradient(135deg,#d4a843 0%,#b8922e 50%,#d4a843 100%);'
                            f'border:none;border-radius:6px;font-family:Syne,sans-serif;font-size:12px;font-weight:800;'
                            f'letter-spacing:.06em;text-transform:uppercase;color:#0a0b14;text-decoration:none;'
                            f'box-sizing:border-box;">☆ + Watchlist</a>',
                            unsafe_allow_html=True
                        )
                    if resolved_tk not in ALL_SECTORS:
                        st.markdown('<div style="font-size:13px;color:#475569;margin-bottom:16px;">⚠ Not in core universe — scored from live price data. Fundamental data may be limited.</div>', unsafe_allow_html=True)
            except Exception:
                st.markdown(
                    f'<div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08);'
                    f'border-radius:8px;padding:20px 24px;">'
                    f'<div style="font-family:Syne,sans-serif;font-size:15px;font-weight:700;color:#94a3b8;margin-bottom:6px;">'
                    f'"{search_ticker}" not found</div>'
                    f'<div style="font-size:13px;color:#475569;">Could not retrieve data. Check the symbol and try again.</div>'
                    f'</div>',
                    unsafe_allow_html=True)
        st.markdown('<div style="height:8px;border-bottom:1px solid rgba(255,255,255,.06);margin-bottom:20px;"></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    if st.session_state.scan_results is None:
        # Auto-trigger if data is old
        stale_msg = "Loading universe scores..."
        try:
            from data_refresh import cache_is_fresh
            if not cache_is_fresh():
                stale_msg = "Data is stale — loading estimated scores. Hit Rescan for live data."
        except Exception:
            pass
        with st.spinner(stale_msg):
            raw   = run_full_scan(use_live_prices=False)
            macro = fetch_macro_overlay()
            # Force sector BEFORE macro overlay so overlay uses correct sector keys
            for r in raw:
                if not r.get("sector") or r.get("sector") == "Unknown":
                    r["sector"] = ALL_SECTORS.get(r["ticker"], "Unknown")
            results = apply_macro_overlay(raw, macro)
            st.session_state.scan_results = enrich_with_signal_log(results)
            st.session_state.macro_data   = macro

    results = st.session_state.scan_results
    macro   = st.session_state.get("macro_data", {})
    gems = detect_hidden_gems(results, macro_data=st.session_state.get("macro_data"))
    gem_tickers = {g["ticker"] for g in gems}

    st.markdown('<div style="padding:0 32px;">', unsafe_allow_html=True)

    # ── Macro Regime Banner ────────────────────────────────────────────────────
    from model_engine import MACRO_EVENT_INFO
    st.markdown(macro_regime_banner_html(macro), unsafe_allow_html=True)

    # Active event details with read-more
    active_evts = macro.get("active_events", [])
    if active_evts:
        for evt in active_evts:
            info = MACRO_EVENT_INFO.get(evt)
            if not info:
                continue
            with st.expander(f"📖 {info['label']} — {info['summary']}", expanded=False):
                st.markdown(
                    f'<div style="padding:4px 0;">'
                    f'<div style="font-size:14px;color:#94a3b8;line-height:1.8;margin-bottom:12px;">{info["detail"]}</div>'
                    f'<div style="display:flex;gap:16px;flex-wrap:wrap;">'
                    f'<div style="flex:1;min-width:200px;background:rgba(239,68,68,.05);border:1px solid rgba(239,68,68,.15);border-radius:6px;padding:10px 14px;">'
                    f'<div style="font-size:13px;color:#ef4444;letter-spacing:.08em;margin-bottom:4px;">HEADWINDS</div>'
                    f'<div style="font-size:13px;color:#94a3b8;">{info["impact"]}</div></div>'
                    f'<div style="flex:1;min-width:200px;background:rgba(0,255,135,.04);border:1px solid rgba(0,255,135,.15);border-radius:6px;padding:10px 14px;">'
                    f'<div style="font-size:13px;color:#00ff87;letter-spacing:.08em;margin-bottom:4px;">TAILWINDS</div>'
                    f'<div style="font-size:13px;color:#94a3b8;">{info["bullish"]}</div></div>'
                    f'</div></div>',
                    unsafe_allow_html=True)

    # ── Differentiator Strip ───────────────────────────────────────────────────
    # Data freshness note
    st.markdown("""
    <div style="background:rgba(212,168,67,.04);border:1px solid rgba(212,168,67,.15);
         border-radius:6px;padding:10px 16px;margin-bottom:14px;
         display:flex;align-items:center;gap:10px;">
      <span style="font-size:13px;">ℹ️</span>
      <span style="font-size:12px;color:#64748b;line-height:1.6;">
        Universe scores are based on model fundamentals updated periodically.
        <strong style="color:#94a3b8;">Search any ticker above for a live score</strong>
        pulled fresh from market data.
      </span>
    </div>
    """, unsafe_allow_html=True)
    bt = BACKTEST_DATA

    st.markdown(DISCLAIMER, unsafe_allow_html=True)

    # Summary strip
    buys  = sum(1 for r in results if r.get("adj_action",r.get("action"))=="BUY")
    holds = sum(1 for r in results if r.get("adj_action",r.get("action"))=="HOLD")
    sells = sum(1 for r in results if r.get("adj_action",r.get("action"))=="SELL")

    # Summary strip — single HTML row, no Streamlit columns
    stat_items = [
        ("HIGH CONVICTION",  "#00ff87", str(buys)),
        ("MODERATE",         "#fbbf24", str(holds)),
        ("LOW CONVICTION",   "#ef4444", str(sells)),
        ("GEMS",  "#00ff87", str(len(gems))),
        ("UNIV",  "#475569", f"{len(results)}"),
    ]
    stats_html = "".join(
        f'<div style="flex:1;min-width:0;background:rgba(255,255,255,.02);'
        f'border:1px solid rgba(255,255,255,.07);border-radius:4px;padding:8px 4px;text-align:center;">'
        f'<div style="font-family:DM Mono,monospace;font-size:8px;color:#94a3b8;letter-spacing:.06em;margin-bottom:3px;">{l}</div>'
        f'<div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:{c};line-height:1;">{v}</div>'
        f'</div>'
        for l,c,v in stat_items
    )
    st.markdown(
        f'<div style="display:flex;gap:5px;margin-bottom:12px;">{stats_html}</div>',
        unsafe_allow_html=True)


    buys_ranked  = sorted([r for r in results if r.get("adj_action",r.get("action"))=="BUY"],
                          key=lambda x: x.get("adj_composite",x.get("composite",0)), reverse=True)
    sells_ranked = sorted([r for r in results if r.get("adj_action",r.get("action"))=="SELL"],
                          key=lambda x: x.get("adj_composite",x.get("composite",100)))

    st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)
    scr_tab1, scr_tab2, scr_tab3 = st.tabs(["⭐ TOP 10 SIGNALS", "🔍 FULL UNIVERSE", "📈 SECTOR BREAKDOWN"])

    # ── TAB 1: TOP 10 ──────────────────────────────────────────────────────────
    with scr_tab1:
        st.markdown("""
        <div style="font-size:13px;color:#94a3b8;margin-bottom:12px;">
          ⚠ Prices are indicative snapshots — may not reflect intraday changes.
          Search any ticker for a fresh live score.
        </div>
        """, unsafe_allow_html=True)
        col_b, col_s = st.columns(2)
        for col, label, color, ranked, action_lbl in [
            (col_b, "▲ TOP 10 HIGH CONVICTION", "#00ff87", buys_ranked[:10],  "▲ High Conviction"),
            (col_s, "▼ TOP 10 LOW CONVICTION",  "#ef4444", sells_ranked[:10], "▼ Low Conviction"),
        ]:
            with col:
                count = len(buys_ranked) if action_lbl=="▲ BUY" else len(sells_ranked)
                st.markdown(
                    f'<div style="font-family:DM Mono,monospace;font-size:12px;color:{color};'
                    f'letter-spacing:.1em;margin:16px 0 6px;">{label}</div>',
                    unsafe_allow_html=True)

                for i, r in enumerate(ranked):
                    score      = r.get("adj_composite", r.get("composite", 0))
                    gem        = " 💎" if r["ticker"] in gem_tickers else ""
                    ci         = get_company_info(r["ticker"])
                    name       = ci.get("name", r["ticker"]) if ci else r["ticker"]
                    name_short = name if len(name) <= 20 else name[:18] + "…"
                    price_str  = f'${r["price"]:,.2f}' if r.get("price") else ""
                    is_gem     = r["ticker"] in gem_tickers
                    macro_d    = r.get("score_delta", 0)
                    macro_str  = f'+{macro_d:.1f}' if macro_d >= 0 else f'{macro_d:.1f}'
                    macro_col  = "#00ff87" if macro_d >= 0 else "#ef4444"
                    label_str  = f"{r['ticker']}{gem}  ·  {name_short}  ·  **{score:.0f}**"

                    with st.expander(label_str, expanded=False):
                        # Compact card: price + macro + stacked pillar bars
                        mom = r.get("momentum", 50)
                        qua = r.get("quality",  50)
                        vol = r.get("volume",   50)
                        val = r.get("value",    50)
                        sen = r.get("sentiment",50)

                        def bar(v):
                            c = "#00ff87" if v>=60 else ("#f59e0b" if v>=45 else "#ef4444")
                            w = max(4, int(v))
                            return (f'<div style="height:4px;border-radius:2px;background:rgba(255,255,255,.08);margin:1px 0;">'
                                    f'<div style="width:{w}%;height:100%;background:{c};border-radius:2px;"></div></div>')

                        price_line = f'<span style="color:#d4a843;font-size:11px;">{price_str}</span> ' if price_str else ''
                        macro_line = f'<span style="color:{macro_col};font-size:11px;">macro {macro_str}</span>'

                        st.markdown(
                            f'<div style="padding:4px 2px;">'
                            f'<div style="display:flex;justify-content:space-between;margin-bottom:6px;">'
                            f'{price_line}{macro_line}'
                            f'</div>'
                            f'<div style="font-size:10px;color:#64748b;margin-bottom:1px;">MOM {mom:.0f}</div>{bar(mom)}'
                            f'<div style="font-size:10px;color:#64748b;margin-bottom:1px;margin-top:3px;">QUAL {qua:.0f}</div>{bar(qua)}'
                            f'<div style="font-size:10px;color:#64748b;margin-bottom:1px;margin-top:3px;">VOL {vol:.0f}</div>{bar(vol)}'
                            f'<div style="font-size:10px;color:#64748b;margin-bottom:1px;margin-top:3px;">VAL {val:.0f}</div>{bar(val)}'
                            f'<div style="font-size:10px;color:#64748b;margin-bottom:1px;margin-top:3px;">SENT {sen:.0f}</div>{bar(sen)}'
                            f'</div>',
                            unsafe_allow_html=True)
                st.caption(f"{count} total signals in universe")

    # ── TAB 2: FULL UNIVERSE ───────────────────────────────────────────────────
    with scr_tab2:
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            filter_sec = st.selectbox("Sector", ["All"]+sorted(set(SECTORS.values())), key="f_sec")
        with fc2:
            filter_act = st.selectbox("Signal", ["All","BUY","HOLD","SELL"], key="f_act", label_visibility="collapsed")
        with fc3:
            filter_sig = st.selectbox("Signal Strength", ["All","STRONG ALIGN","HIGH ALIGN","MODERATE","LOW ALIGN","WEAK/NEG"], key="f_sig")
        rb1, rb2 = st.columns(2)
        with rb1:
            if st.button("🔄 Rescan", key="rescan", use_container_width=True):
                st.session_state.scan_results = None
                st.rerun()
        with rb2:
            if st.button("⚡ Live Refresh", key="live_refresh", use_container_width=True):
                pass  # live refresh removed
                st.rerun()




        filtered = results
        if filter_sig != "All": filtered = [r for r in filtered if r["signal"]==filter_sig]
        if filter_sec != "All": filtered = [r for r in filtered if r["sector"]==filter_sec]
        if filter_act != "All":
            filtered = [r for r in filtered if r.get("adj_action",r.get("action"))==filter_act]

        st.markdown(
            f'<div style="font-family:DM Mono,monospace;font-size:13px;color:#64748b;'
            f'letter-spacing:.1em;margin:8px 0 12px;">{len(filtered)} STOCKS · 💎 = HIDDEN GEM</div>',
            unsafe_allow_html=True)
        for r in filtered:
            ci = get_company_info(r["ticker"])
            st.markdown(factor_panel_html(r, r["ticker"] in gem_tickers, company_info=ci), unsafe_allow_html=True)

    # ── TAB 3: SECTOR BREAKDOWN ────────────────────────────────────────────────
    with scr_tab3:
        sector_counts = {}
        for r in results:
            sec = r.get("sector","Other")
            act = r.get("adj_action", r.get("action","HOLD"))
            if sec not in sector_counts:
                sector_counts[sec] = {"BUY":0,"HOLD":0,"SELL":0}
            sector_counts[sec][act] = sector_counts[sec].get(act,0)+1

        st.markdown('<div style="font-family:DM Mono,monospace;font-size:13px;color:#94a3b8;letter-spacing:.1em;margin:16px 0 10px;">SIGNAL BREAKDOWN BY SECTOR</div>', unsafe_allow_html=True)
        for sec, counts in sorted(sector_counts.items()):
            total = sum(counts.values()) or 1
            b,h,s = counts.get("BUY",0),counts.get("HOLD",0),counts.get("SELL",0)
            bp,hp,sp = b/total*100, h/total*100, s/total*100
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:7px;">'
                f'<div style="font-size:13px;color:#64748b;width:170px;flex-shrink:0;">{sec}</div>'
                f'<div style="flex:1;display:flex;border-radius:4px;overflow:hidden;height:20px;">'
                f'<div style="width:{bp:.0f}%;background:rgba(0,255,135,.6);"></div>'
                f'<div style="width:{hp:.0f}%;background:rgba(251,191,36,.4);"></div>'
                f'<div style="width:{sp:.0f}%;background:rgba(239,68,68,.5);"></div>'
                f'</div>'
                f'<div style="font-size:14px;color:#94a3b8;width:130px;flex-shrink:0;">'
                f'<span style="color:#00ff87;">{b} HIGH</span> '
                f'<span style="color:#fbbf24;">{h} MOD</span> '
                f'<span style="color:#ef4444;">{s} LOW</span>'
                f'</div></div>',
                unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

def page_watchlist():
    """User watchlist — tracked stocks with live conviction scores."""
    page_summary("★", "Watchlist",
        "Stocks you're tracking. Conviction scores update daily — add any stock from the Screener search.")
    st.markdown('<div style="padding:0 32px;">', unsafe_allow_html=True)

    watchlist = get_watchlist(uid())
    scan      = st.session_state.get("scan_results") or []
    score_map = {r["ticker"]: r for r in scan}

    if not watchlist:
        st.markdown(
            '<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);'
            'border-radius:10px;padding:40px 24px;text-align:center;margin-top:16px;">'
            '<div style="font-size:32px;margin-bottom:12px;">★</div>'
            '<div style="font-family:Syne,sans-serif;font-size:16px;font-weight:700;color:#64748b;margin-bottom:8px;">'
            'Your watchlist is empty</div>'
            '<div style="font-size:13px;color:#334155;line-height:1.6;">'
            'Search any stock on the Screener and hit <strong style="color:#94a3b8;">Add to Watchlist</strong> '
            'to track its conviction score here.</div>'
            '</div>',
            unsafe_allow_html=True
        )
        st.markdown('</div>', unsafe_allow_html=True)
        return

    # If no scan loaded, show scores from signal_log
    if not score_map:
        try:
            from data_refresh import _get_supabase
            sb = _get_supabase()
            if sb:
                tickers = [w["ticker"] for w in watchlist]
                resp = sb.table("signal_log") \
                    .select("ticker,adj_composite,composite,price,signal,momentum,quality,volume,value,sentiment") \
                    .in_("ticker", tickers) \
                    .order("signal_date", desc=True) \
                    .limit(len(tickers) * 3) \
                    .execute()
                seen = set()
                for row in (resp.data or []):
                    tk = row["ticker"]
                    if tk not in seen:
                        seen.add(tk)
                        score_map[tk] = row
        except Exception:
            pass

    from model_engine import EXIT_THRESHOLD, ENTRY_THRESHOLD, SECTORS as _WL_SECTORS

    # Summary header
    n = len(watchlist)
    n_hi  = sum(1 for w in watchlist if float((score_map.get(w["ticker"]) or {}).get("adj_composite",0) or 0) >= 60)
    n_lo  = sum(1 for w in watchlist if float((score_map.get(w["ticker"]) or {}).get("adj_composite",50) or 50) < 45)
    _lo_html = f'<div style="font-size:13px;color:#ef4444;">▼ {n_lo} Low Conviction</div>' if n_lo else ""
    st.markdown(
        f'<div style="display:flex;gap:16px;margin-bottom:16px;flex-wrap:wrap;">'
        f'<div style="font-size:13px;color:#64748b;">{n} stocks tracked</div>'
        f'<div style="font-size:13px;color:#00ff87;">▲ {n_hi} High Conviction</div>'
        f'{_lo_html}'
        f'</div>',
        unsafe_allow_html=True
    )

    # Fetch live prices + prev close for day change via yfinance
    wl_tickers = [w["ticker"] for w in watchlist]
    day_change  = {}   # ticker -> {price, prev_close, chg_pct, chg_dollar}
    if wl_tickers:
        try:
            import yfinance as yf
            hist = yf.download(wl_tickers, period="5d", auto_adjust=True,
                               progress=False, threads=True)
            if not hist.empty:
                close = hist["Close"]
                if hasattr(close, "columns"):
                    for tk in wl_tickers:
                        if tk in close.columns:
                            vals = close[tk].dropna()
                            if len(vals) >= 2:
                                cur  = float(vals.iloc[-1])
                                prev = float(vals.iloc[-2])
                                day_change[tk] = {
                                    "price":      cur,
                                    "prev_close": prev,
                                    "chg_pct":    (cur - prev) / prev * 100,
                                    "chg_dollar": cur - prev,
                                }
                else:
                    vals = close.dropna()
                    if len(vals) >= 2 and len(wl_tickers) == 1:
                        cur  = float(vals.iloc[-1])
                        prev = float(vals.iloc[-2])
                        day_change[wl_tickers[0]] = {
                            "price":      cur,
                            "prev_close": prev,
                            "chg_pct":    (cur - prev) / prev * 100,
                            "chg_dollar": cur - prev,
                        }
        except Exception:
            pass

    # Also fetch entry prices from watchlist record if stored, else use first observed price
    wl_entry = {w["ticker"]: w.get("entry_price") or w.get("price_at_add") for w in watchlist}

    # Table header — hidden on mobile (cards show labels inline)
    st.markdown(
        '<div class="wl-table-header" style="display:grid;grid-template-columns:160px 110px 90px 70px 90px 90px 110px 1fr;'
        'gap:8px;padding:10px 16px;background:#0d1117;border-radius:6px 6px 0 0;'
        'border:1px solid rgba(255,255,255,.1);">'
        '<div style="font-size:11px;color:#94a3b8;letter-spacing:.1em;font-weight:700;">TICKER</div>'
        '<div style="font-size:11px;color:#94a3b8;letter-spacing:.1em;font-weight:700;">SECTOR</div>'
        '<div style="font-size:11px;color:#94a3b8;letter-spacing:.1em;font-weight:700;text-align:right;">PRICE</div>'
        '<div style="font-size:11px;color:#94a3b8;letter-spacing:.1em;font-weight:700;text-align:right;">SCORE</div>'
        '<div style="font-size:11px;color:#94a3b8;letter-spacing:.1em;font-weight:700;text-align:right;">DAY</div>'
        '<div style="font-size:11px;color:#94a3b8;letter-spacing:.1em;font-weight:700;text-align:right;">SINCE ADDED</div>'
        '<div style="font-size:11px;color:#94a3b8;letter-spacing:.1em;font-weight:700;text-align:right;">SIGNAL</div>'
        '<div style="font-size:11px;color:#94a3b8;letter-spacing:.1em;font-weight:700;">DRIVERS</div>'
        '</div>',
        unsafe_allow_html=True
    )

    for i, w in enumerate(watchlist):
        tk  = w["ticker"]
        sc  = score_map.get(tk, {})
        adj = float(sc.get("adj_composite", sc.get("composite", 0)) or 0)
        mom   = float(sc.get("momentum",  0) or 0)
        qual  = float(sc.get("quality",   0) or 0)
        vol   = float(sc.get("volume",    0) or 0)
        val   = float(sc.get("value",     0) or 0)
        sent  = float(sc.get("sentiment", 0) or 0)
        sector = _WL_SECTORS.get(tk, "—")
        ci    = get_company_info(tk)
        name  = (ci.get("name", tk) if ci else tk)[:24]

        # Price + day change from yfinance
        dc = day_change.get(tk, {})
        cur_price  = dc.get("price") or sc.get("price")
        chg_pct    = dc.get("chg_pct")
        chg_dollar = dc.get("chg_dollar")

        # Since watching — compare to entry price stored in DB
        entry_p    = wl_entry.get(tk)
        if entry_p and cur_price and float(entry_p) > 0:
            since_pct = (cur_price - float(entry_p)) / float(entry_p) * 100
        else:
            since_pct = None

        def _chg(pct, dollar=None):
            if pct is None: return "—", "#64748b"
            sign = "+" if pct >= 0 else ""
            color = "#00ff87" if pct >= 0 else "#ef4444"
            dollar_str = f" (${abs(dollar):.2f})" if dollar is not None else ""
            return f"{sign}{pct:.2f}%{dollar_str}", color

        day_str,    day_col    = _chg(chg_pct, chg_dollar)
        since_str,  since_col  = _chg(since_pct)
        price_str  = f"${cur_price:,.2f}" if cur_price else "—"
        score_str  = f"{adj:.0f}" if adj else "—"

        sig_label = "High Conviction" if adj >= 60 else ("Low Conviction" if adj < 45 else "Moderate")
        sig_color = "#00ff87" if adj >= 60 else ("#ef4444" if adj < 45 else "#fbbf24")
        score_col = "#00ff87" if adj >= 60 else ("#ef4444" if adj < 45 else "#fbbf24")
        border_c  = "#00ff87" if adj >= 60 else ("#ef4444" if adj < 45 else "#334155")
        bg = "rgba(255,255,255,.025)" if i % 2 == 0 else "rgba(255,255,255,.01)"

        pillars = sorted([("MOM",mom),("QUAL",qual),("VOL",vol),("VAL",val),("SENT",sent)],
                         key=lambda x: x[1], reverse=True)
        top2 = " · ".join(
            f'<span style="color:#94a3b8;">{p[0]}</span> '
            f'<span style="color:{("#00ff87" if p[1]>=65 else "#fbbf24")};">{p[1]:.0f}</span>'
            for p in pillars[:2]
        )
        weak = [p for p in pillars if p[1] < 45]
        weak_str = f' · <span style="color:#ef4444;">⚠ {weak[0][0]}</span>' if weak else ""

        st.markdown(
            f'<div class="wl-row" style="display:grid;grid-template-columns:160px 110px 90px 70px 90px 90px 110px 1fr;'
            f'gap:8px;padding:12px 16px;background:{bg};'
            f'border-left:3px solid {border_c};'
            f'border-right:1px solid rgba(255,255,255,.04);'
            f'border-bottom:1px solid rgba(255,255,255,.04);align-items:center;">'
            f'<div>'
            f'<div style="font-family:Syne,sans-serif;font-size:15px;font-weight:800;color:#e2e8f0;">{tk}</div>'
            f'<div style="font-size:11px;color:#64748b;margin-top:1px;">{name}</div>'
            f'</div>'
            f'<div style="font-size:12px;color:#64748b;">{sector}</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:13px;color:#d4a843;text-align:right;">{price_str}</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:16px;font-weight:700;color:{score_col};text-align:right;">{score_str}</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:12px;font-weight:600;color:{day_col};text-align:right;">{day_str}</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:12px;font-weight:600;color:{since_col};text-align:right;">{since_str}</div>'
            f'<div style="font-size:12px;color:{sig_color};text-align:right;font-weight:600;">{sig_label}</div>'
            f'<div style="font-size:11px;color:#64748b;">{top2}{weak_str}</div>'
            f'</div>'
            # Mobile card — hidden on desktop, shown on mobile
            f'<div class="wl-card" style="display:none;padding:14px 16px;background:{bg};'
            f'border-left:3px solid {border_c};border-bottom:1px solid rgba(255,255,255,.05);">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;">'
            f'<div>'
            f'<div style="font-family:Syne,sans-serif;font-size:16px;font-weight:800;color:#e2e8f0;">{tk}</div>'
            f'<div style="font-size:11px;color:#64748b;">{name} · {sector}</div>'
            f'</div>'
            f'<div style="text-align:right;">'
            f'<div style="font-family:DM Mono,monospace;font-size:18px;font-weight:700;color:{score_col};">{score_str}</div>'
            f'<div style="font-size:11px;color:{sig_color};font-weight:600;">{sig_label}</div>'
            f'</div>'
            f'</div>'
            f'<div style="display:flex;gap:16px;flex-wrap:wrap;">'
            f'<div><div style="font-size:10px;color:#475569;letter-spacing:.08em;">PRICE</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:13px;color:#d4a843;">{price_str}</div></div>'
            f'<div><div style="font-size:10px;color:#475569;letter-spacing:.08em;">DAY</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:13px;color:{day_col};">{day_str}</div></div>'
            f'<div><div style="font-size:10px;color:#475569;letter-spacing:.08em;">SINCE ADDED</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:13px;color:{since_col};">{since_str}</div></div>'
            f'</div>'
            f'<div style="margin-top:8px;font-size:11px;color:#64748b;">{top2}{weak_str}</div>'
            f'</div>',
            unsafe_allow_html=True
        )
        _uid_val = (st.session_state.user or {}).get("id", "")
        _plan_val = (st.session_state.user or {}).get("plan", "free")
        _rm_url = f"?qnav=watchlist&uid={_uid_val}&plan={_plan_val}&ck=1&wl_action=remove&wl_ticker={tk}"
        st.markdown(
            f'<a href="{_rm_url}" target="_self" style="'
            f'display:block;width:100%;text-align:center;padding:8px;margin-top:6px;'
            f'background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.25);'
            f'border-radius:6px;font-family:Syne,sans-serif;font-size:11px;font-weight:700;'
            f'letter-spacing:.06em;text-transform:uppercase;color:#ef4444;text-decoration:none;'
            f'box-sizing:border-box;">✕ Remove</a>',
            unsafe_allow_html=True
        )

    st.markdown(
        '<div style="padding:8px 14px;background:#050a0f;border:1px solid rgba(255,255,255,.07);'
        'border-radius:0 0 6px 6px;font-size:11px;color:#334155;">'
        'Scores updated daily via nightly refresh · Add stocks via Screener search</div>',
        unsafe_allow_html=True
    )
    st.markdown('</div>', unsafe_allow_html=True)


def _gem_why_tags(r: dict) -> list:
    """Short reason tags for why this stock was surfaced as a Hidden Gem."""
    tags, comp = [], float(r.get("adj_composite", r.get("composite", 50)) or 50)
    mom  = float(r.get("momentum",  50) or 50)
    qual = float(r.get("quality",   50) or 50)
    val  = float(r.get("value",     50) or 50)
    sent = float(r.get("sentiment", 50) or 50)
    vol  = float(r.get("volume",    50) or 50)
    delta = float(r.get("score_delta", 0) or 0)
    if mom  >= 65: tags.append("Momentum leadership")
    if qual >= 65: tags.append("Quality improving")
    if val  >= 65: tags.append("Undervalued")
    if sent >= 60: tags.append("Positive sentiment")
    if vol  >= 65: tags.append("Volume confirming")
    if delta > 2:  tags.append("Macro tailwind")
    if comp >= 68: tags.append("Rising conviction")
    reason = r.get("hidden_gem_reason", "")
    if "coverage" in reason.lower():  tags.append("Low analyst coverage")
    if "insider"  in reason.lower():  tags.append("Insider activity")
    return tags[:3]


def page_gems():
    page_summary(
        "💎", "Hidden Gems",
        "Mid-cap stocks with institutional-grade factor scores that fly under Wall Street's radar. "
        "QNTM screens for revenue acceleration, earnings beats, low short interest, and low analyst coverage — "
        "the stocks that show up before the crowd notices. Regime-adjusted thresholds mean the bar rises in volatile markets.",

    )

    if not is_pro():
        st.markdown("""
        <div style="margin:0 32px;background:rgba(0,255,135,.04);border:1px solid rgba(0,255,135,.2);
             border-radius:8px;padding:48px;text-align:center;">
          <div style="font-size:48px;margin-bottom:16px;">🔒</div>
          <div style="font-family:'Syne',sans-serif;font-size:24px;font-weight:800;
               color:#00ff87;margin-bottom:12px;">Founding Member Feature</div>
          <div style="color:#64748b;max-width:480px;margin:0 auto;line-height:1.7;margin-bottom:24px;">
            Hidden Gem detection is free for the first 50 founding members.
            These are mid-cap stocks with institutional-grade factor scores that
            fly under Wall Street's radar — the ones that show up before the crowd notices.
          </div>
          <div style="background:rgba(0,255,135,.08);border:1px solid rgba(0,255,135,.3);
               border-radius:6px;padding:16px 24px;display:inline-block;margin-bottom:24px;">
            <div style="font-family:'DM Mono',monospace;font-size:12px;color:#00ff87;">
              🎯 Preview: CELH — Revenue +62% YoY · Earnings +148% · Beat 4/4 quarters
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(_cta_gold("Join Free — First 50 Spots", "?nav=register"), unsafe_allow_html=True)
        return

    if st.session_state.scan_results is None:
        with st.spinner("Loading scores..."):
            st.session_state.scan_results = run_full_scan(use_live_prices=False)
        if not st.session_state.scan_results:
            st.info("No scan data available. Run a Rescan on the Screener first.")
            return

    gems = detect_hidden_gems(st.session_state.scan_results, macro_data=st.session_state.get("macro_data"))
    st.markdown(DISCLAIMER, unsafe_allow_html=True)

    if not gems:
        st.markdown('<div style="padding:0 32px;"><div style="color:#94a3b8;padding:40px;text-align:center;">No hidden gems detected in current scan.</div></div>', unsafe_allow_html=True)
        return

    regime = st.session_state.get("macro_data", {}).get("regime", "NEUTRAL")
    regime_colors = {"RISK_OFF":"#ef4444","HIGH VOLATILITY":"#f97316","RISK_ON":"#00ff87","MILDLY BULLISH":"#4ade80","NEUTRAL":"#d4a843"}
    regime_color = regime_colors.get(regime, "#d4a843")

    st.markdown(f'<div style="padding:0 32px;">', unsafe_allow_html=True)
    st.markdown(f"""
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
      <div style="font-size:13px;color:#94a3b8;">{len(gems)} hidden gems identified</div>
      <div style="font-size:13px;color:{regime_color};font-family:DM Mono,monospace;">
        Regime: {regime} · {"Threshold 67+" if regime in ("RISK_OFF","HIGH VOLATILITY") else "Threshold 60+" if regime in ("RISK_ON","MILDLY BULLISH") else "Threshold 62+"}
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Load current watchlist to know which gems are already added
    wl_tickers = {w["ticker"] for w in get_watchlist(uid())}

    grid_open = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;padding:0 4px;">'
    st.markdown(grid_open, unsafe_allow_html=True)

    for g in gems:
        tk = g.get("ticker", "")
        try:
            adj   = float(g.get("adj_composite") or g.get("composite") or 0)
            raw   = float(g.get("composite") or 0)
            delta = adj - raw
            price = g.get("price")
            ci    = get_company_info(g["ticker"])
            name  = ci.get("name", g["ticker"]) if ci else g["ticker"]
            name_short = name if len(name) <= 24 else name[:22] + "…"

            price_html = (
                f'<div style="font-family:DM Mono,monospace;font-size:13px;color:#d4a843;margin-top:2px;">'
                f'${float(price):,.2f} / share</div>'
            ) if price else ""

            delta_html = ""
            if abs(delta) >= 1:
                d_col   = "#ef4444" if delta < 0 else "#00ff87"
                d_arrow = "▼" if delta < 0 else "▲"
                delta_html = f'<span style="font-size:13px;color:{d_col};margin-left:6px;">{d_arrow} {abs(delta):.0f} macro adj</span>'

            reasons_html = "".join(
                f'<div style="font-size:14px;color:#4ade80;padding:4px 0;border-bottom:1px solid rgba(0,255,135,.08);display:flex;align-items:flex-start;gap:6px;"><span style="color:#00ff87;flex-shrink:0;">✓</span><span>{r}</span></div>'
                for r in g.get("gem_reasons", [])
            ) or '<div style="font-size:14px;color:#94a3b8;">Run Live Refresh for detailed factor reasons</div>'

            mom  = float(g.get("momentum")  or 0)
            qual = float(g.get("quality")   or 0)
            val  = float(g.get("value")     or 0)
            sent = float(g.get("sentiment") or 0)
            pillars_html = (
                f'<div style="text-align:center;"><div style="font-family:DM Mono,monospace;font-size:14px;color:#00ff87;">{mom:.0f}</div><div style="font-size:14px;color:#94a3b8;">MOM</div></div>'
                f'<div style="text-align:center;"><div style="font-family:DM Mono,monospace;font-size:14px;color:#00ff87;">{qual:.0f}</div><div style="font-size:14px;color:#94a3b8;">QUAL</div></div>'
                f'<div style="text-align:center;"><div style="font-family:DM Mono,monospace;font-size:14px;color:#00ff87;">{val:.0f}</div><div style="font-size:14px;color:#94a3b8;">VAL</div></div>'
                f'<div style="text-align:center;"><div style="font-family:DM Mono,monospace;font-size:14px;color:#00ff87;">{sent:.0f}</div><div style="font-size:14px;color:#94a3b8;">SENT</div></div>'
            )

            tk = g["ticker"]
            in_wl = tk in wl_tickers

            card = (
                '<div style="background:rgba(0,255,135,.04);border:1px solid rgba(0,255,135,.25);'
                'border-radius:10px;padding:20px 16px;">'
                '<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;">'
                '<div style="min-width:0;">'
                f'<div style="font-family:Syne,sans-serif;font-size:26px;font-weight:800;color:#e2e8f0;line-height:1;">{tk}</div>'
                f'<div style="font-size:13px;color:#94a3b8;margin-top:2px;">{name_short}</div>'
                f'<div style="font-size:13px;color:#94a3b8;">{g.get("sector","")}</div>'
                + price_html +
                '</div>'
                '<div style="text-align:right;flex-shrink:0;margin-left:8px;">'
                f'<div style="font-family:Syne,sans-serif;font-size:32px;font-weight:800;color:#00ff87;line-height:1;">{adj:.0f}</div>'
                '<div style="font-size:13px;color:#94a3b8;">adj score</div>'
                f'<div style="font-size:13px;color:#64748b;">raw {raw:.0f}</div>'
                + delta_html +
                '</div></div>'
                '<div style="display:flex;gap:12px;background:rgba(0,255,135,.06);border-radius:6px;padding:10px;margin:12px 0;">'
                + pillars_html +
                '</div>'
                '<div style="border-top:1px solid rgba(0,255,135,.1);padding-top:12px;">'
                + reasons_html +
                '</div>'
                + '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:10px;">'
                + "".join(
                    f'<span style="background:rgba(212,168,67,.1);border:1px solid rgba(212,168,67,.18);'
                    f'border-radius:10px;padding:2px 8px;font-size:10px;color:#d4a843;font-family:DM Mono,monospace;">{t}</span>'
                    for t in _gem_why_tags(g)
                )
                + '</div></div>'
            )
            st.markdown(card, unsafe_allow_html=True)

        except Exception:
            pass

        # Watchlist — HTML link with action params, no Streamlit button rerun
        in_wl = tk in wl_tickers
        _uid_val = (st.session_state.user or {}).get("id", "")
        _plan_val = (st.session_state.user or {}).get("plan", "free")
        _qp = f"?qnav=gems&uid={_uid_val}&plan={_plan_val}&ck=1"
        if in_wl:
            _action_url = _qp + f"&wl_action=remove&wl_ticker={tk}"
            st.markdown(
                f'<a href="{_action_url}" target="_self" style="'
                f'display:block;width:100%;text-align:center;padding:10px;margin-top:8px;'
                f'background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.15);'
                f'border-radius:6px;font-family:Syne,sans-serif;font-size:12px;font-weight:700;'
                f'letter-spacing:.06em;text-transform:uppercase;color:#e2e8f0;text-decoration:none;'
                f'box-sizing:border-box;">★ Watchlist</a>',
                unsafe_allow_html=True
            )
        else:
            _action_url = _qp + f"&wl_action=add&wl_ticker={tk}"
            st.markdown(
                f'<a href="{_action_url}" target="_self" style="'
                f'display:block;width:100%;text-align:center;padding:10px;margin-top:8px;'
                f'background:linear-gradient(135deg,#d4a843 0%,#b8922e 50%,#d4a843 100%);'
                f'border:none;border-radius:6px;font-family:Syne,sans-serif;font-size:12px;font-weight:800;'
                f'letter-spacing:.06em;text-transform:uppercase;color:#0a0b14;text-decoration:none;'
                f'box-sizing:border-box;">☆ + Watchlist</a>',
                unsafe_allow_html=True
            )

    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# BACKTEST PAGE
# ══════════════════════════════════════════════════════════════════════════════
def page_backtest():
    bt = BACKTEST_DATA
    page_summary(
        "📈", "Backtest Performance",
        f"Walk-forward validation across 5 years and 6 market regimes — COVID recovery, post-COVID bull, "
        f"bear/rate hike, AI boom, concentration rally, and tariff correction. Same rules every year, no tuning between regimes. "
        f"Real prices, 10bps transaction costs, 124 tickers × 20 quarters. "
        f"Result: +{bt['model_total_ret']:.0f}% cumulative vs SPY +{bt['spy_total_ret']:.0f}% over the same period.",

    )
    st.markdown('<div style="padding:0 32px;">', unsafe_allow_html=True)
    st.markdown(DISCLAIMER, unsafe_allow_html=True)

    # Hero numbers
    # Hero stats — 2x2 HTML grid works on all screen sizes
    st.markdown(f"""
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:24px 0;">
      <div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);
           border-left:2px solid #00ff87;border-radius:6px;padding:16px;">
        <div style="font-family:DM Mono,monospace;font-size:13px;color:#64748b;letter-spacing:.1em;margin-bottom:8px;">5-YR TOTAL RETURN</div>
        <div style="font-family:Syne,sans-serif;font-size:28px;font-weight:800;color:#00ff87;line-height:1;">+{bt['model_total_ret']:.1f}%</div>
        <div style="font-size:14px;color:#94a3b8;margin-top:6px;">${'100K'} → ${bt['model_final_100k']:,}</div>
      </div>
      <div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);
           border-radius:6px;padding:16px;">
        <div style="font-family:DM Mono,monospace;font-size:13px;color:#64748b;letter-spacing:.1em;margin-bottom:8px;">SPY SAME PERIOD</div>
        <div style="font-family:Syne,sans-serif;font-size:28px;font-weight:800;color:#fbbf24;line-height:1;">+{bt['spy_total_ret']:.1f}%</div>
        <div style="font-size:14px;color:#94a3b8;margin-top:6px;">${'100K'} → ${bt['spy_final_100k']:,}</div>
      </div>
      <div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);
           border-left:2px solid #00ff87;border-radius:6px;padding:16px;">
        <div style="font-family:DM Mono,monospace;font-size:13px;color:#64748b;letter-spacing:.1em;margin-bottom:8px;">MODEL CAGR</div>
        <div style="font-family:Syne,sans-serif;font-size:28px;font-weight:800;color:#00ff87;line-height:1;">+{bt['model_cagr']:.1f}%</div>
        <div style="font-size:14px;color:#94a3b8;margin-top:6px;">vs SPY +{bt['spy_cagr']:.1f}% CAGR</div>
      </div>
      <div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);
           border-left:2px solid #00ff87;border-radius:6px;padding:16px;">
        <div style="font-family:DM Mono,monospace;font-size:13px;color:#64748b;letter-spacing:.1em;margin-bottom:8px;">5-YR ADVANTAGE</div>
        <div style="font-family:Syne,sans-serif;font-size:24px;font-weight:800;color:#00ff87;line-height:1;">+${bt['model_advantage_usd']:,}</div>
        <div style="font-size:14px;color:#94a3b8;margin-top:6px;">on $100,000 invested</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Risk metrics — 3x2 HTML grid
    st.markdown(f"""
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:16px;">
      <div style="background:rgba(0,255,135,.04);border:1px solid rgba(0,255,135,.12);border-radius:6px;padding:12px;text-align:center;">
        <div style="font-family:DM Mono,monospace;font-size:14px;color:#94a3b8;letter-spacing:.08em;margin-bottom:6px;">SHARPE</div>
        <div style="font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:#00ff87;">{bt['sharpe']:.2f}</div>
        <div style="font-size:13px;color:#94a3b8;margin-top:4px;">&gt;1.0 excellent</div>
      </div>
      <div style="background:rgba(0,255,135,.04);border:1px solid rgba(0,255,135,.12);border-radius:6px;padding:12px;text-align:center;">
        <div style="font-family:DM Mono,monospace;font-size:14px;color:#94a3b8;letter-spacing:.08em;margin-bottom:6px;">SORTINO</div>
        <div style="font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:#00ff87;">{bt['sortino']:.2f}</div>
        <div style="font-size:13px;color:#94a3b8;margin-top:4px;">&gt;1.5 strong</div>
      </div>
      <div style="background:rgba(0,255,135,.04);border:1px solid rgba(0,255,135,.12);border-radius:6px;padding:12px;text-align:center;">
        <div style="font-family:DM Mono,monospace;font-size:14px;color:#94a3b8;letter-spacing:.08em;margin-bottom:6px;">INFO RATIO</div>
        <div style="font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:#00ff87;">{bt.get('information_ratio',1.25):.2f}</div>
        <div style="font-size:13px;color:#94a3b8;margin-top:4px;">&gt;0.5 signal</div>
      </div>
      <div style="background:rgba(0,255,135,.04);border:1px solid rgba(0,255,135,.12);border-radius:6px;padding:12px;text-align:center;">
        <div style="font-family:DM Mono,monospace;font-size:14px;color:#94a3b8;letter-spacing:.08em;margin-bottom:6px;">MAX DD</div>
        <div style="font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:#00ff87;">{bt['max_dd_model']:.1f}%</div>
        <div style="font-size:13px;color:#94a3b8;margin-top:4px;">SPY {bt.get('max_dd_spy',-25.4):.1f}%</div>
      </div>
      <div style="background:rgba(0,255,135,.04);border:1px solid rgba(0,255,135,.12);border-radius:6px;padding:12px;text-align:center;">
        <div style="font-family:DM Mono,monospace;font-size:14px;color:#94a3b8;letter-spacing:.08em;margin-bottom:6px;">WIN RATE</div>
        <div style="font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:#00ff87;">{bt['win_rate']:.1f}%</div>
        <div style="font-size:13px;color:#94a3b8;margin-top:4px;">{bt['n_quarters']} quarters</div>
      </div>
      <div style="background:rgba(0,255,135,.04);border:1px solid rgba(0,255,135,.12);border-radius:6px;padding:12px;text-align:center;">
        <div style="font-family:DM Mono,monospace;font-size:14px;color:#94a3b8;letter-spacing:.08em;margin-bottom:6px;">CAGR ALPHA</div>
        <div style="font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:#00ff87;">+{bt['cagr_alpha']:.1f}pp</div>
        <div style="font-size:13px;color:#94a3b8;margin-top:4px;">/yr vs index</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Growth chart — compute from real quarterly returns for accuracy
    import streamlit.components.v1 as _components
    st.markdown('<div style="height:24px;"></div>', unsafe_allow_html=True)
    st.markdown('<div style="font-family:\'DM Mono\',monospace;font-size:13px;color:#94a3b8;letter-spacing:.1em;margin-bottom:8px;">GROWTH OF $100,000 — Q2 2020 TO Q1 2025</div>', unsafe_allow_html=True)

    # Build growth curves from quarterly returns (most accurate)
    qr = bt.get("macro_quarterly_returns", {})
    quarters_ordered = [
        "2020-Q2","2020-Q3","2020-Q4",
        "2021-Q1","2021-Q2","2021-Q3","2021-Q4",
        "2022-Q1","2022-Q2","2022-Q3","2022-Q4",
        "2023-Q1","2023-Q2","2023-Q3","2023-Q4",
        "2024-Q1","2024-Q2","2024-Q3","2024-Q4",
        "2025-Q1",
    ]
    labels   = ["Start"] + quarters_ordered
    qntm_pts = [100000]
    spy_pts  = [100000]
    v_q, v_s = 100000.0, 100000.0
    for q in quarters_ordered:
        if q in qr:
            v_q = round(v_q * (1 + qr[q]["blended"]), 0)
            v_s = round(v_s * (1 + qr[q]["spy"]), 0)
        qntm_pts.append(int(v_q))
        spy_pts.append(int(v_s))
    chart_html = f"""<!DOCTYPE html><html>
<head><script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script></head>
<body style="margin:0;background:#0a0b14;padding:0;">
<div style="position:relative;height:380px;width:100%;">
<canvas id="gc"></canvas>
</div>
<script>
const labels = {labels};
const qntm   = {qntm_pts};
const spy    = {spy_pts};
new Chart(document.getElementById('gc'), {{
  type: 'line',
  data: {{
    labels: labels,
    datasets: [
      {{
        label: 'QNTM Model',
        data: qntm,
        borderColor: '#d4a843',
        backgroundColor: 'rgba(212,168,67,0.06)',
        borderWidth: 2.5,
        pointBackgroundColor: '#d4a843',
        pointRadius: 3,
        pointHoverRadius: 6,
        fill: true,
        tension: 0.3,
      }},
      {{
        label: 'S&P 500 (SPY)',
        data: spy,
        borderColor: 'rgba(100,116,139,0.9)',
        backgroundColor: 'rgba(100,116,139,0.03)',
        borderWidth: 1.5,
        pointBackgroundColor: '#64748b',
        pointRadius: 2,
        pointHoverRadius: 5,
        fill: true,
        tension: 0.3,
        borderDash: [5,4],
      }},
    ]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        backgroundColor: '#0d1117',
        borderColor: 'rgba(212,168,67,0.3)',
        borderWidth: 1,
        titleColor: '#d4a843',
        bodyColor: '#94a3b8',
        padding: 12,
        callbacks: {{
          label: ctx => ' $' + ctx.parsed.y.toLocaleString(),
        }}
      }}
    }},
    scales: {{
      x: {{
        grid: {{ color: 'rgba(255,255,255,0.03)' }},
        ticks: {{
          color: '#334155',
          font: {{ family: 'DM Mono, monospace', size: 10 }},
          maxTicksLimit: 10,
          maxRotation: 45,
        }},
        border: {{ color: 'rgba(255,255,255,0.05)' }},
      }},
      y: {{
        grid: {{ color: 'rgba(255,255,255,0.03)' }},
        ticks: {{
          color: '#334155',
          font: {{ family: 'DM Mono, monospace', size: 10 }},
          callback: v => '$' + (v/1000).toFixed(0) + 'K',
        }},
        border: {{ color: 'rgba(255,255,255,0.05)' }},
      }}
    }}
  }}
}});
const c = document.createElement('div');
c.style = 'display:flex;gap:20px;padding:8px 0 0 8px;';
c.innerHTML = `
  <span style="display:flex;align-items:center;gap:6px;font-family:DM Mono,monospace;font-size:13px;color:#d4a843;">
    <span style="width:18px;height:2.5px;background:#d4a843;display:inline-block;border-radius:2px;"></span>
    QNTM Model
  </span>
  <span style="display:flex;align-items:center;gap:6px;font-family:DM Mono,monospace;font-size:13px;color:#94a3b8;">
    <span style="width:18px;height:1.5px;background:#64748b;display:inline-block;border-radius:2px;opacity:0.7;"></span>
    S&P 500 (SPY)
  </span>`;
document.body.prepend(c);
</script>
</body></html>"""
    _components.html(chart_html, height=480)

    # ── Macro Overlay Attribution Section ─────────────────────────────────────
    st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)
    st.markdown("""
    <div style="font-family:'DM Mono',monospace;font-size:13px;color:#d4a843;
         letter-spacing:.1em;margin:20px 0 12px;">
      ⚡ WALK-FORWARD BACKTEST — REGIME-SCALED MACRO OVERLAY (Q2 2020 – Q1 2025)
    </div>
    <div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);
         border-radius:6px;padding:14px 18px;margin-bottom:14px;font-size:14px;color:#94a3b8;line-height:1.7;">
      Methodology: genuine point-in-time walk-forward simulation. Real yfinance price histories fetched
      as-of each quarter-start date. Scores recomputed every quarter from available data — no static
      fundamentals applied retroactively. 10bps transaction cost per trade. 124 large-cap tickers.
      Minimum 15 positions enforced. Macro weight scales by regime: 35% RISK_OFF · 15% RISK_ON · 10% NEUTRAL.
      Survivorship bias disclosed (200bps/yr haircut applied to adjusted figures).
    </div>
    """, unsafe_allow_html=True)

    mac_stats = [
        ("75/25 Blended Return",f"+{bt['macro_cumulative_return']:.1f}%",f"${bt['macro_final_100k']:,} from $100K","#d4a843"),
        ("Pure Quant Return",f"+{bt['pure_quant_cumulative']:.1f}%","No macro overlay","#94a3b8"),
        ("Blended vs SPY",f"+{bt['blended_vs_spy_pp']:.0f}pp","Cumulative outperformance","#1D9E75"),
        ("Macro: Drawdown Saved",f"-{bt['macro_drawdown_improvement_pp']:.1f}pp","vs pure quant max DD","#1D9E75"),
    ]
    mac_html = "".join([
        f'<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);'
        f'border-top:2px solid {color};border-radius:6px;padding:16px;text-align:center;min-width:0;overflow:hidden;">'
        f'<div style="font-family:DM Mono,monospace;font-size:13px;color:#64748b;letter-spacing:.08em;margin-bottom:10px;">{label}</div>'
        f'<div style="font-family:Syne,sans-serif;font-size:clamp(18px,4vw,26px);font-weight:800;color:{color};line-height:1;">{val}</div>'
        f'<div style="font-size:13px;color:#94a3b8;margin-top:8px;">{sub}</div>'
        f'</div>'
        for label,val,sub,color in mac_stats
    ])
    st.markdown(
        f'<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-bottom:12px;">{mac_html}</div>',
        unsafe_allow_html=True)

    st.markdown('<div style="height:12px;"></div>', unsafe_allow_html=True)

    # Honest comparison table
    st.markdown("""
    <div style="font-family:'DM Mono',monospace;font-size:13px;color:#94a3b8;
         letter-spacing:.1em;margin:8px 0 8px;">SIDE-BY-SIDE: BLENDED vs PURE QUANT vs SPY</div>
    """, unsafe_allow_html=True)

    comparison = [
        ("75/25 Blended","#d4a843",
         bt['macro_cumulative_return'], bt['macro_annualized_return'],
         bt['macro_sharpe'], bt['macro_sortino'], bt['macro_max_drawdown'],
         bt['macro_win_rate'], bt.get('information_ratio', 1.25),
         bt.get('macro_cumulative_return_adj')),
        ("Pure Quant (no macro)","#94a3b8",
         bt['pure_quant_cumulative'], bt['pure_quant_annualized'],
         bt['pure_quant_sharpe'], None, bt['pure_quant_max_drawdown'], None, None, None),
        ("SPY Benchmark","#475569",
         bt['benchmark_cumulative'], bt['benchmark_annualized'],
         bt['benchmark_sharpe'], None, bt['benchmark_max_drawdown'], None, None, None),
    ]
    comp_html = ""
    for name,color,cum,ann,sharpe,sortino,mdd,wr,ir,adj in comparison:
        sortino_row = f'<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.05);"><span style="font-size:13px;color:#94a3b8;">Sortino</span><span style="font-family:DM Mono,monospace;font-size:13px;color:#94a3b8;">{sortino:.2f}</span></div>' if sortino else ""
        wr_row = f'<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.05);"><span style="font-size:13px;color:#94a3b8;">Win Rate</span><span style="font-family:DM Mono,monospace;font-size:13px;color:#94a3b8;">{wr:.1f}%</span></div>' if wr else ""
        ir_row = f'<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.05);"><span style="font-size:13px;color:#94a3b8;">Info Ratio</span><span style="font-family:DM Mono,monospace;font-size:13px;color:#94a3b8;">{ir:.2f}</span></div>' if ir else ""
        adj_row = f'<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.05);"><span style="font-size:13px;color:#94a3b8;">Adj. Return*</span><span style="font-family:DM Mono,monospace;font-size:13px;color:#94a3b8;">+{adj:.1f}%</span></div>' if adj else ""
        comp_html += (
            f'<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);'
            f'border-left:3px solid {color};border-radius:6px;padding:12px;min-width:0;overflow:hidden;">'
            f'<div style="font-family:Syne,sans-serif;font-size:13px;font-weight:700;color:{color};letter-spacing:.06em;margin-bottom:10px;">{name}</div>'
            f'<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.05);"><span style="font-size:13px;color:#94a3b8;">Cumulative</span><span style="font-family:DM Mono,monospace;font-size:13px;color:{color};">+{cum:.1f}%</span></div>'
            f'{adj_row}'
            f'<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.05);"><span style="font-size:13px;color:#94a3b8;">Annualized</span><span style="font-family:DM Mono,monospace;font-size:13px;color:{color};">+{ann:.1f}%</span></div>'
            f'<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.05);"><span style="font-size:13px;color:#94a3b8;">Sharpe</span><span style="font-family:DM Mono,monospace;font-size:13px;color:#94a3b8;">{sharpe:.2f}</span></div>'
            f'{sortino_row}{ir_row}{wr_row}'
            f'<div style="display:flex;justify-content:space-between;padding:5px 0;"><span style="font-size:13px;color:#94a3b8;">Max Drawdown</span><span style="font-family:DM Mono,monospace;font-size:13px;color:#ef4444;">-{mdd:.1f}%</span></div>'
            f'</div>'
        )
    st.markdown(
        f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px;">{comp_html}</div>',
        unsafe_allow_html=True)

    # Regime breakdown
    st.markdown('<div style="height:12px;"></div>', unsafe_allow_html=True)
    st.markdown("""
    <div style="font-family:'DM Mono',monospace;font-size:13px;color:#94a3b8;
         letter-spacing:.1em;margin-bottom:8px;">MACRO REGIME BREAKDOWN (avg quarterly return)</div>
    """, unsafe_allow_html=True)

    regime_summary = bt.get("macro_regime_summary", {})
    regime_display = [
        ("RISK-ON (10 qtrs)",   "RISK_ON",  "#1D9E75"),
        ("NEUTRAL (7 qtrs)",    "NEUTRAL",  "#d4a843"),
        ("RISK-OFF (4 qtrs)",   "RISK_OFF", "#ef4444"),
    ]
    for label, key, color in regime_display:
        rd = regime_summary.get(key, {})
        b_pct  = rd.get("blended_avg_pct", 0)
        q_pct  = rd.get("quant_avg_pct", 0)
        s_pct  = rd.get("spy_avg_pct", 0)
        b_alpha = rd.get("blended_alpha_bps", 0)
        b_col  = "#1D9E75" if b_pct >= 0 else "#ef4444"
        a_col  = "#1D9E75" if b_alpha >= 0 else "#ef4444"
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:12px;padding:10px 14px;
             background:rgba(255,255,255,.015);border:1px solid rgba(255,255,255,.06);
             border-left:3px solid {color};border-radius:4px;margin-bottom:6px;">
          <div style="font-family:'DM Mono',monospace;font-size:13px;color:#94a3b8;width:150px;flex-shrink:0;">
            {label}
          </div>
          <div style="display:flex;gap:24px;flex-wrap:wrap;flex:1;">
            <div>
              <div style="font-size:13px;color:#94a3b8;letter-spacing:.08em;margin-bottom:4px;">BLENDED AVG</div>
              <div style="font-family:'DM Mono',monospace;font-size:17px;font-weight:500;color:{b_col};">{b_pct:+.2f}%</div>
            </div>
            <div>
              <div style="font-size:12px;color:#64748b;letter-spacing:.08em;margin-bottom:2px;">PURE QUANT</div>
              <div style="font-family:'DM Mono',monospace;font-size:14px;font-weight:500;color:#94a3b8;">{q_pct:+.2f}%</div>
            </div>
            <div>
              <div style="font-size:13px;color:#94a3b8;letter-spacing:.07em;margin-bottom:4px;">SPY AVG</div>
              <div style="font-family:'DM Mono',monospace;font-size:14px;font-weight:500;color:#94a3b8;">{s_pct:+.2f}%</div>
            </div>
            <div>
              <div style="font-size:13px;color:#94a3b8;letter-spacing:.04em;margin-bottom:4px;">BlendED vs SPY</div>
              <div style="font-family:'DM Mono',monospace;font-size:14px;font-weight:500;color:{a_col};">{b_alpha:+.0f} bps</div>
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("""
    <div style="background:rgba(212,168,67,.05);border:1px solid rgba(212,168,67,.15);
         border-radius:6px;padding:14px 18px;margin-top:12px;font-size:12px;color:#64748b;line-height:1.8;">
      <strong style="color:#d4a843;">What the regime-scaled macro overlay actually does:</strong>
      The blended portfolio applies 35% macro weight in RISK_OFF, 15% in RISK_ON, and 10% in NEUTRAL —
      scaling conviction by regime clarity. Pure quant returned +230.8% but with a -19.9% max drawdown.
      The macro overlay boosted that to +346.6% cumulative (+215.6pp vs SPY) while cutting max drawdown
      to just -6.5% — a 13.4pp improvement. In RISK_OFF regimes (2022 rate shock, 2025 tariff shock),
      the blended portfolio averaged +1.5% per quarter while SPY averaged -7.9% — 936bps of protection.
      <strong style="color:#94a3b8;">Methodology: walk-forward, real prices, 10bps transaction costs, 124 tickers, disclosed biases.</strong>
    </div>
    """, unsafe_allow_html=True)

    # Regime grid
    st.markdown('<div style="font-family:\'DM Mono\',monospace;font-size:13px;color:#94a3b8;letter-spacing:.1em;margin:24px 0 12px;">REGIME SCORECARD</div>', unsafe_allow_html=True)
    r_cols = st.columns(6)
    for col, p in zip(r_cols, bt["periods"]):
        beat  = p["beat"]
        col_c = "rgba(0,255,135,.15)" if beat else "rgba(239,68,68,.1)"
        brd   = "rgba(0,255,135,.3)"  if beat else "rgba(239,68,68,.25)"
        icon  = "✓" if beat else "✗"
        ic    = "#00ff87" if beat else "#ef4444"
        mc    = "#00ff87" if p["model_ret"]>=0 else "#ef4444"
        sc    = "#4ade80" if p["spy_ret"]>=0 else "#ef4444"
        with col:
            st.markdown(f"""
            <div style="background:{col_c};border:1px solid {brd};border-radius:6px;padding:14px 12px;">
              <div style="font-family:'DM Mono',monospace;font-size:13px;color:#94a3b8;margin-bottom:4px;">{p['key']}</div>
              <div style="font-family:'Syne',sans-serif;font-size:12px;font-weight:700;color:#94a3b8;margin-bottom:10px;">{p['label']}</div>
              <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:{ic};">{icon}</div>
              <div style="margin-top:8px;">
                <div style="font-family:'DM Mono',monospace;font-size:13px;color:{mc};font-weight:500;">QNTM {p['model_ret']:+.1f}%</div>
                <div style="font-family:'DM Mono',monospace;font-size:13px;color:{sc};margin-top:2px;">SPY {p['spy_ret']:+.1f}%</div>
                <div style="font-size:13px;color:#94a3b8;margin-top:6px;">{p['char']}</div>
              </div>
            </div>
            """, unsafe_allow_html=True)

    # Holdings table — styled HTML matching platform theme
    st.markdown(
        '<div style="font-family:DM Mono,monospace;font-size:13px;color:#94a3b8;'
        'letter-spacing:.1em;margin:32px 0 12px;">12-MONTH CONVICTION PORTFOLIO — ACTUAL POSITIONS &amp; RETURNS</div>',
        unsafe_allow_html=True)

    # Table header — wrapped for mobile horizontal scroll
    st.markdown(
        '<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;">'
        '<div style="min-width:520px;">'
        '<div style="display:grid;grid-template-columns:80px 80px 100px 1fr 110px 90px;'
        'gap:8px;padding:10px 16px;background:#050a0f;border-radius:6px 6px 0 0;'
        'border:1px solid rgba(255,255,255,.07);">'
        '<div style="font-size:13px;color:#64748b;letter-spacing:.1em;">TICKER</div>'
        '<div style="font-size:13px;color:#64748b;letter-spacing:.1em;">ACTION</div>'
        '<div style="font-size:13px;color:#64748b;letter-spacing:.1em;">SCORE</div>'
        '<div style="font-size:13px;color:#64748b;letter-spacing:.1em;">HOLD PERIOD</div>'
        '<div style="font-size:13px;color:#64748b;letter-spacing:.1em;">12M RETURN</div>'
        '<div style="font-size:13px;color:#64748b;letter-spacing:.1em;">RESULT</div>'
        '</div>',
        unsafe_allow_html=True)

    for h in bt["holdings_12m"]:
        ret    = h["return_pct"]
        act    = h["action"]
        act_c  = "#00ff87" if act=="BUY" else "#ef4444"
        ret_c  = "#00ff87" if ret > 0 else "#ef4444"
        arrow  = "▲" if act=="BUY" else "▼"
        win    = ret > 0
        result_c = "#00ff87" if win else "#ef4444"
        result   = "✓ WIN" if win else "✗ LOSS"
        row_bg   = "rgba(0,255,135,.02)" if win else "rgba(239,68,68,.02)"
        st.markdown(
            f'<div style="display:grid;grid-template-columns:80px 80px 100px 1fr 110px 90px;'
            f'gap:8px;padding:12px 16px;background:{row_bg};'
            f'border-left:1px solid rgba(255,255,255,.05);border-right:1px solid rgba(255,255,255,.05);'
            f'border-bottom:1px solid rgba(255,255,255,.05);align-items:center;">'
            f'<div style="font-family:Syne,sans-serif;font-size:15px;font-weight:800;color:#e2e8f0;">{h["ticker"]}</div>'
            f'<div><span style="font-size:13px;font-weight:700;color:{act_c};'
            f'background:{act_c}18;border:1px solid {act_c}44;padding:2px 8px;border-radius:3px;">'
            f'{arrow} {act}</span></div>'
            f'<div style="font-family:DM Mono,monospace;font-size:14px;color:{act_c};font-weight:600;">{h["signal"]}</div>'
            f'<div style="font-size:13px;color:#94a3b8;">{h["held"]}</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:16px;font-weight:700;color:{ret_c};">{ret:+.1f}%</div>'
            f'<div style="font-size:13px;font-weight:700;color:{result_c};">{result}</div>'
            f'</div>',
            unsafe_allow_html=True)

    st.markdown('<div style="padding:8px 16px;background:#050a0f;border:1px solid rgba(255,255,255,.07);border-radius:0 0 6px 6px;font-size:13px;color:#94a3b8;">Stocks avoided: ' +
                ", ".join([f'{a["ticker"]} ({a["return_pct"]:+.1f}%)' for a in bt["avoided"][:5]]) +
                ' — exited or never entered on signal</div></div></div>',
                unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PORTFOLIO PAGE
# ══════════════════════════════════════════════════════════════════════════════

def _make_excel(rows: list, headers: list, sheet_name: str = "Export") -> bytes:
    """Generate an in-memory Excel file from a list of dicts. Returns bytes."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, PatternFill
    from io import BytesIO

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name

    # Header row
    header_fill = PatternFill("solid", start_color="0D1117")
    header_font = Font(name="Arial", bold=True, color="D4A843", size=10)
    for ci, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=ci, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    # Data rows
    row_font  = Font(name="Arial", size=10)
    for ri, row in enumerate(rows, 2):
        for ci, h in enumerate(headers, 1):
            val = row.get(h, "")
            cell = ws.cell(row=ri, column=ci, value=val)
            cell.font = row_font
            if ri % 2 == 0:
                cell.fill = PatternFill("solid", start_color="0A0B14")

    # Auto-width columns
    for col in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

    # Freeze header row
    ws.freeze_panes = "A2"

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()

def page_portfolio():
    user = st.session_state.user or {}
    plan = user.get("plan", "free")
    max_h = plan_limit(plan, "max_holdings")
    has_notifs = plan_limit(plan, "notifications")

    page_summary(
        "💼", "My Portfolio",
        "Add your positions and QNTM applies the full conviction model to each one every scan. "
        "See your blended score, pillar breakdown, and whether the signal has changed since you entered. "
        "Free accounts track up to 10 positions. Pro unlocks unlimited holdings and real-time signal alerts.",
    )
    st.markdown('<div style="padding:0 32px;">', unsafe_allow_html=True)

    # ── Ensure scan results ────────────────────────────────────────────────────
    if st.session_state.scan_results is None:
        with st.spinner("Loading model signals..."):
            raw   = run_full_scan(use_live_prices=False)
            macro = fetch_macro_overlay()
            st.session_state.scan_results = apply_macro_overlay(raw, macro)
            st.session_state.macro_data   = macro

    score_map = {s["ticker"]: s for s in st.session_state.scan_results}
    holdings  = get_holdings(uid())
    n_holdings = len(holdings)

    # ── Portfolio conviction summary ────────────────────────────────────
    if holdings and score_map:
        _sc = [float(score_map.get(h["ticker"],{}).get("adj_composite",50) or 50) for h in holdings]
        _hi, _mo, _lo = sum(1 for x in _sc if x>=60), sum(1 for x in _sc if 45<=x<60), sum(1 for x in _sc if x<45)
        _avg = sum(_sc)/len(_sc)
        _cl  = "High" if _avg>=60 else ("Low" if _avg<45 else "Moderate")
        _cc  = "#00ff87" if _avg>=60 else ("#ef4444" if _avg<45 else "#fbbf24")
        _html = '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:0 32px 20px;">'
        for _lb, _vl, _cl2, _sb in [
            ("PORTFOLIO CONVICTION", _cl,      _cc,       f"avg score {_avg:.0f}"),
            ("HIGH CONVICTION",      str(_hi), "#00ff87", "positions"),
            ("MODERATE",             str(_mo), "#fbbf24", "positions"),
            ("LOW CONVICTION",       str(_lo), "#ef4444", f"{"⚠ " if _lo>0 else ""}{_lo} positions"),
        ]:
            _fsz = "16px" if len(_vl)>3 else "22px"
            _html += (
                f'<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.06);"'
                f'border-radius:8px;padding:12px 14px;text-align:center;">'
                f'<div style="font-size:9px;color:#475569;letter-spacing:.08em;margin-bottom:4px;">{_lb}</div>'
                f'<div style="font-family:Syne,sans-serif;font-size:{_fsz};font-weight:700;color:{_cl2};">{_vl}</div>'
                f'<div style="font-size:9px;color:#475569;margin-top:3px;">{_sb}</div></div>'
            )
        _html += '</div>'
        st.markdown(_html, unsafe_allow_html=True)


    # ── Plan capacity bar ──────────────────────────────────────────────────────
    if plan == "free":
        pct = min(100, int(n_holdings / max_h * 100))
        bar_c = "#ef4444" if n_holdings >= max_h else "#fbbf24" if n_holdings >= 8 else "#00ff87"
        st.markdown(f"""
        <div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);
             border-radius:6px;padding:12px 16px;margin-bottom:16px;
             display:flex;align-items:center;gap:16px;">
          <div style="flex:1;">
            <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
              <span style="font-size:14px;color:#94a3b8;">Free plan — positions used</span>
              <span style="font-family:'DM Mono',monospace;font-size:12px;color:{bar_c};">
                {n_holdings} / {max_h}
              </span>
            </div>
            <div style="background:rgba(255,255,255,.06);border-radius:3px;height:4px;overflow:hidden;">
              <div style="width:{pct}%;height:100%;background:{bar_c};border-radius:3px;
                   transition:width .3s;"></div>
            </div>
          </div>
          <div style="font-size:13px;color:#64748b;flex-shrink:0;">
            {'<span style="color:#ef4444;">At limit</span>' if n_holdings >= max_h else f'{max_h - n_holdings} remaining'}
          </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Pro upgrade nudge ──────────────────────────────────────────────────────
    if plan == "free" and n_holdings >= 7:
        st.markdown(f"""
        <div style="background:rgba(212,168,67,.05);border:1px solid rgba(212,168,67,.2);
             border-radius:6px;padding:12px 16px;margin-bottom:12px;
             display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
          <div style="font-size:13px;color:#d4a843;">
            ⚡ Upgrade to Pro — unlimited positions, hidden gems, and signal alerts
          </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(_cta_gold("Upgrade to Pro — $29/mo", "?nav=register"), unsafe_allow_html=True)

    st.markdown(DISCLAIMER, unsafe_allow_html=True)

    # ── Check for signal changes (pro users get notifications) ─────────────────
    if holdings and score_map:
        prev_signals = get_signal_snapshot(uid())
        signal_changes = check_and_notify_signal_changes(uid(), plan, score_map, prev_signals)
        save_signal_snapshot(uid(), st.session_state.scan_results)

        if signal_changes:
            for chg in signal_changes:
                change_type = chg.get("type", "action_change")

                if change_type == "action_change" and chg["to"] == "SELL":
                    st.markdown(
                        f'<div style="background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.4);'
                        f'border-radius:6px;padding:12px 16px;margin-bottom:8px;">'
                        f'<span style="font-family:Syne,sans-serif;font-size:12px;font-weight:700;'
                        f'color:#ef4444;letter-spacing:.1em;">▼ LOW CONVICTION: {chg["ticker"]}</span>'
                        f'<span style="font-size:14px;color:#94a3b8;margin-left:12px;">'
                        f'Score dropping — check Alerts tab</span></div>',
                        unsafe_allow_html=True)

                elif change_type == "action_change" and chg["to"] == "BUY":
                    st.markdown(
                        f'<div style="background:rgba(0,255,135,.08);border:1px solid rgba(0,255,135,.3);'
                        f'border-radius:6px;padding:12px 16px;margin-bottom:8px;">'
                        f'<span style="font-family:Syne,sans-serif;font-size:12px;font-weight:700;'
                        f'color:#00ff87;letter-spacing:.1em;">▲ HIGH CONVICTION: {chg["ticker"]}</span>'
                        f'<span style="font-size:14px;color:#94a3b8;margin-left:12px;">'
                        f'Conviction strengthening</span></div>',
                        unsafe_allow_html=True)

                elif change_type == "deterioration":
                    delta = chg.get("delta", 0)
                    st.markdown(
                        f'<div style="background:rgba(251,191,36,.06);border:1px solid rgba(251,191,36,.3);'
                        f'border-radius:6px;padding:12px 16px;margin-bottom:8px;">'
                        f'<span style="font-family:Syne,sans-serif;font-size:12px;font-weight:700;'
                        f'color:#fbbf24;letter-spacing:.1em;">⚠ DETERIORATING: {chg["ticker"]}</span>'
                        f'<span style="font-size:14px;color:#94a3b8;margin-left:12px;">'
                        f'Score dropped {abs(delta):.0f} pts · Still HOLD but monitor closely</span></div>',
                        unsafe_allow_html=True)

    # ── SELL / EXIT signals across portfolio ───────────────────────────────────
    exit_signals = []
    for h in holdings:
        sc = score_map.get(h["ticker"])
        if sc:
            act = sc.get("adj_action", sc.get("action", "HOLD"))
            if act == "SELL":
                exit_signals.append((h["ticker"], sc.get("adj_composite", sc.get("composite",0)), sc.get("signal","")))

    if exit_signals:
        ticker_chips = "".join([
            f'<span style="display:inline-flex;align-items:center;gap:6px;margin-right:12px;'
            f'margin-bottom:6px;background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.3);'
            f'border-radius:4px;padding:4px 10px;">'
            f'<span style="font-family:DM Mono,monospace;font-size:13px;color:#e2e8f0;font-weight:500;">{tk}</span>'
            f'<span style="font-size:13px;color:#ef4444;">{sc:.0f}</span>'
            f'</span>'
            for tk, sc, sig in exit_signals
        ])
        st.markdown(f"""
        <div style="background:rgba(239,68,68,.07);border:1px solid rgba(239,68,68,.3);
             border-radius:8px;padding:16px 20px;margin-bottom:20px;">
          <div style="font-family:'Syne',sans-serif;font-size:13px;font-weight:700;
               color:#ef4444;letter-spacing:.12em;margin-bottom:10px;">⚠ ACTIVE EXIT SIGNALS</div>
          <div style="display:flex;flex-wrap:wrap;">{ticker_chips}</div>
          <div style="font-size:13px;color:#94a3b8;margin-top:8px;">
            Model score below exit threshold (45). Review these positions.
          </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Add position form ──────────────────────────────────────────────────────
    at_limit = n_holdings >= max_h

    # Prominent Add Position header
    st.markdown("""
    <div style="background:linear-gradient(135deg,rgba(0,255,135,.08),rgba(0,255,135,.02));
         border:1px solid rgba(0,255,135,.3);border-radius:10px;padding:14px 20px;margin-bottom:4px;">
      <div style="font-family:Syne,sans-serif;font-size:15px;font-weight:700;color:#00ff87;">
        ➕ Add Position
      </div>
      <div style="font-size:12px;color:#64748b;margin-top:2px;">Search a ticker and enter your shares + cost basis</div>
    </div>
    """, unsafe_allow_html=True)
    with st.expander("", expanded=(n_holdings == 0)):
        if at_limit and plan == "free":
            st.markdown("""
            <div style="background:rgba(239,68,68,.06);border:1px solid rgba(239,68,68,.2);
                 border-radius:6px;padding:14px;font-size:13px;color:#ef4444;">
              Free plan limit reached (10 positions). Upgrade to Pro for unlimited holdings.
            </div>
            """, unsafe_allow_html=True)
        else:
            r1c1, r1c2, r1c3 = st.columns([2, 2, 2])
            with r1c1:
                tk_query = st.text_input("Ticker / Company Name", key="p_tk", placeholder="e.g. Tesla, AAPL")
            with r1c2: new_sh   = st.number_input("Shares",       key="p_sh",   min_value=0.0, step=1.0, format="%.2f")
            with r1c3: new_cost = st.number_input("Avg Cost ($)", key="p_cost", min_value=0.0, step=0.01, format="%.2f")

            # Resolve and preview
            resolved_ticker, resolved_name = "", ""
            if tk_query and tk_query.strip():
                with st.spinner("Looking up...") if len(tk_query) > 2 and not tk_query.strip().isupper() else contextlib.nullcontext():
                    resolved_ticker, resolved_name = resolve_ticker(tk_query)
                if resolved_ticker and resolved_name and resolved_name != resolved_ticker:
                    st.markdown(
                        f'<div style="font-size:14px;color:#00ff87;margin-bottom:8px;">'
                        f'✓ {resolved_ticker} — {resolved_name}</div>',
                        unsafe_allow_html=True)
                elif resolved_ticker:
                    st.markdown(
                        f'<div style="font-size:14px;color:#94a3b8;margin-bottom:8px;">'
                        f'Ticker: {resolved_ticker}</div>',
                        unsafe_allow_html=True)

            r2c1, r2c2 = st.columns([3, 1])
            with r2c1: new_date = st.date_input("Entry Date", key="p_date", value=date.today())
            with r2c2:
                st.markdown('<div style="height:28px;"></div>', unsafe_allow_html=True)
                if st.button("Add", key="p_add", use_container_width=True):
                    new_tk = resolved_ticker or tk_query.strip().upper()
                    if new_tk and new_sh > 0:
                        tk_clean = new_tk.upper().strip()
                        ok = upsert_holding(uid(), tk_clean, new_sh, new_cost, new_date)
                        if ok:
                            st.success(f"Added {tk_clean}")
                            # Fire notification if signal is active
                            sc = score_map.get(tk_clean)
                            if sc:
                                act = sc.get("adj_action", sc.get("action", "HOLD"))
                                comp = sc.get("adj_composite", sc.get("composite", 50))
                                if act == "SELL":
                                    st.warning(f"⚠ Note: Model currently shows EXIT signal on {tk_clean} (score {comp:.0f})")
                                elif act == "BUY":
                                    create_notification(uid(), tk_clean, "buy_signal",
                                        f"HIGH conviction active: {tk_clean}",
                                        f"Score {comp:.0f} — {sc.get('signal','')}")
                            else:
                                st.info(f"{tk_clean} is outside the model universe — no signal available")
                            st.rerun()
                        else:
                            st.error("Failed to add position — check ticker and try again")
                    else:
                        st.warning("Enter a ticker symbol and number of shares")

    # ── Empty state ────────────────────────────────────────────────────────────
    if not holdings:
        st.markdown("""
        <div style="text-align:center;padding:48px 24px;max-width:480px;margin:0 auto;">
          <div style="font-size:52px;margin-bottom:16px;">💼</div>
          <div style="font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:#e2e8f0;margin-bottom:12px;">
            Add your first position
          </div>
          <div style="font-size:14px;color:#64748b;line-height:1.8;margin-bottom:28px;">
            QNTM will run the full conviction model against every stock you add —
            showing your blended score, pillar breakdown, and whether the signal
            has changed since you entered.
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:28px;">
            <div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);border-radius:8px;padding:14px 10px;">
              <div style="font-size:20px;margin-bottom:6px;">📊</div>
              <div style="font-size:13px;color:#64748b;line-height:1.5;">Conviction<br>score</div>
            </div>
            <div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);border-radius:8px;padding:14px 10px;">
              <div style="font-size:20px;margin-bottom:6px;">🎯</div>
              <div style="font-size:13px;color:#64748b;line-height:1.5;">Signal<br>changes</div>
            </div>
            <div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);border-radius:8px;padding:14px 10px;">
              <div style="font-size:20px;margin-bottom:6px;">💰</div>
              <div style="font-size:13px;color:#64748b;line-height:1.5;">P&L<br>tracking</div>
            </div>
          </div>
          <div style="font-size:14px;color:#94a3b8;">Use the ＋ Add Position button above to get started</div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        return

    # ── Portfolio summary strip ────────────────────────────────────────────────
    port_buys  = sum(1 for h in holdings if score_map.get(h["ticker"],{}).get("adj_action", score_map.get(h["ticker"],{}).get("action")) == "BUY")
    port_holds = sum(1 for h in holdings if score_map.get(h["ticker"],{}).get("adj_action", score_map.get(h["ticker"],{}).get("action")) == "HOLD")
    port_sells = sum(1 for h in holdings if score_map.get(h["ticker"],{}).get("adj_action", score_map.get(h["ticker"],{}).get("action")) == "SELL")
    port_na    = n_holdings - port_buys - port_holds - port_sells

    port_summary_data = [
        ("▲ BUY Signals",     port_buys,  "#00ff87"),
        ("─ Hold",            port_holds, "#fbbf24"),
        ("▼ Sell / Exit",     port_sells, "#ef4444"),
        ("Outside Universe",  port_na,    "#475569"),
    ]
    ps_html = "".join([
        f'<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);'
        f'border-radius:6px;padding:14px;min-width:0;">'
        f'<div style="font-size:13px;color:#94a3b8;letter-spacing:.08em;margin-bottom:6px;font-family:DM Mono,monospace;">{label}</div>'
        f'<div style="font-size:28px;font-weight:800;color:{color};font-family:Syne,sans-serif;line-height:1;">{int(val)}</div>'
        f'<div style="font-size:13px;color:#94a3b8;margin-top:3px;">position{"s" if val!=1 else ""}</div>'
        f'</div>'
        for label,val,color in port_summary_data
    ])
    st.markdown(
        f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:16px;">{ps_html}</div>',
        unsafe_allow_html=True)

    # ── Portfolio Value Tracker ───────────────────────────────────────────────
    SIGNAL_ANNUAL_RATE = {"BUY": 0.409, "HOLD": 0.12, "SELL": -0.05, "N/A": 0.10}
    PERIOD_DATA = [
        ("1D","Today",1), ("1W","1 Week",7), ("1M","1 Month",30),
        ("3M","3 Months",90), ("1Y","1 Year",365), ("5Y","5 Years",1825),
        ("10Y","10 Years",3650), ("ALL","All Time",None),
    ]

    if holdings:
        total_cost_basis = sum(
            float(h.get("avg_cost",0) or 0) * float(h.get("shares",0) or 0)
            for h in holdings
        )
        if "port_period" not in st.session_state:
            st.session_state.port_period = "1M"

        # Period selectbox — clean dropdown, no cramped buttons
        _pp_labels = [f"{plbl} ({pkey})" for pkey,plbl,_ in PERIOD_DATA]
        _pp_keys   = [pkey for pkey,_,_ in PERIOD_DATA]
        _pp_idx    = _pp_keys.index(st.session_state.port_period) if st.session_state.port_period in _pp_keys else 2
        _pp_sel = st.selectbox("View period", _pp_labels, index=_pp_idx, key="port_period_sel",
                               label_visibility="visible")
        _pp_chosen = _pp_keys[_pp_labels.index(_pp_sel)]
        if _pp_chosen != st.session_state.port_period:
            st.session_state.port_period = _pp_chosen
            st.rerun()

        # Compute return for selected period
        sel = next((p for p in PERIOD_DATA if p[0]==st.session_state.port_period), PERIOD_DATA[2])
        pkey, plbl, pdays = sel
        total_current = 0.0
        from datetime import date as _date
        for h in holdings:
            cost   = float(h.get("avg_cost",0) or 0)
            shares = float(h.get("shares",0) or 0)
            sc2    = score_map.get(h["ticker"])
            act2   = sc2.get("adj_action", sc2.get("action","N/A")) if sc2 else "N/A"
            rate   = SIGNAL_ANNUAL_RATE.get(act2, 0.10)
            if pdays:
                period_ret = (1+rate)**(pdays/365) - 1
            else:
                try:
                    ed = _date.fromisoformat(str(h.get("entry_date",""))[:10])
                    period_ret = (1+rate)**(max(((_date.today()-ed).days),1)/365) - 1
                except:
                    period_ret = rate * 2
            total_current += cost * shares * (1 + period_ret)

        total_change     = total_current - total_cost_basis
        chg_pct          = (total_change / total_cost_basis * 100) if total_cost_basis > 0 else 0
        change_c         = "#00ff87" if total_change >= 0 else "#ef4444"
        arrow            = "▲" if total_change >= 0 else "▼"

        b2    = sum(1 for h in holdings if (score_map.get(h["ticker"],{}) or {}).get("adj_action",(score_map.get(h["ticker"],{}) or {}).get("action","N/A"))=="BUY")
        hold2 = sum(1 for h in holdings if (score_map.get(h["ticker"],{}) or {}).get("adj_action",(score_map.get(h["ticker"],{}) or {}).get("action","N/A"))=="HOLD")
        sell2 = len(holdings) - b2 - hold2

        vc_html = (
            f'<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);'
            f'border-left:3px solid #e2e8f0;border-radius:8px;padding:14px;min-width:0;overflow:hidden;">'
            f'<div style="font-size:13px;color:#94a3b8;letter-spacing:.08em;margin-bottom:5px;">TOTAL VALUE</div>'
            f'<div style="font-family:Syne,sans-serif;font-size:clamp(18px,4vw,28px);font-weight:800;color:#e2e8f0;line-height:1;">${total_current:,.0f}</div>'
            f'<div style="font-size:13px;color:#94a3b8;margin-top:4px;">Cost basis ${total_cost_basis:,.0f}</div></div>'

            f'<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);'
            f'border-left:3px solid {change_c};border-radius:8px;padding:14px;min-width:0;overflow:hidden;">'
            f'<div style="font-size:13px;color:#94a3b8;letter-spacing:.08em;margin-bottom:5px;">$ CHANGE</div>'
            f'<div style="font-family:Syne,sans-serif;font-size:clamp(16px,4vw,26px);font-weight:800;color:{change_c};line-height:1;">{arrow} ${abs(total_change):,.0f}</div>'
            f'<div style="font-size:13px;color:#94a3b8;margin-top:4px;">{plbl}</div></div>'

            f'<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);'
            f'border-left:3px solid {change_c};border-radius:8px;padding:14px;min-width:0;overflow:hidden;">'
            f'<div style="font-size:13px;color:#94a3b8;letter-spacing:.08em;margin-bottom:5px;">% CHANGE</div>'
            f'<div style="font-family:Syne,sans-serif;font-size:clamp(16px,4vw,26px);font-weight:800;color:{change_c};line-height:1;">{arrow} {abs(chg_pct):.1f}%</div>'
            f'<div style="font-size:13px;color:#94a3b8;margin-top:4px;">{plbl}</div></div>'

            f'<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);'
            f'border-radius:8px;padding:14px;min-width:0;">'
            f'<div style="font-size:13px;color:#94a3b8;letter-spacing:.08em;margin-bottom:6px;">SIGNAL MIX</div>'
            f'<div style="display:flex;gap:10px;">'
            f'<div><div style="font-size:20px;font-weight:800;color:#00ff87;font-family:Syne,sans-serif;">{b2}</div><div style="font-size:13px;color:#94a3b8;">BUY</div></div>'
            f'<div><div style="font-size:20px;font-weight:800;color:#fbbf24;font-family:Syne,sans-serif;">{hold2}</div><div style="font-size:13px;color:#94a3b8;">HOLD</div></div>'
            f'<div><div style="font-size:20px;font-weight:800;color:#ef4444;font-family:Syne,sans-serif;">{sell2}</div><div style="font-size:13px;color:#94a3b8;">SELL</div></div>'
            f'</div></div>'
        )
        st.markdown(
            f'<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-bottom:4px;">{vc_html}</div>',
            unsafe_allow_html=True)

        st.markdown('<div style="font-size:13px;color:#64748b;margin:4px 0 20px;">Returns estimated from model signal rates. Add live price integration for real-time values.</div>', unsafe_allow_html=True)

    # ── Holdings cards ─────────────────────────────────────────────────────────
    st.markdown("""
    <div style="font-family:DM Mono,monospace;font-size:13px;color:#64748b;letter-spacing:.1em;margin-bottom:6px;">YOUR POSITIONS — MODEL SIGNALS APPLIED</div>
    <div style="font-size:13px;color:#94a3b8;margin-bottom:14px;">
      ⚠ Prices pulled from market data — indicative only, may not reflect real-time intraday changes.
      Run ⚡ Live Refresh in the Screener for the most current values.
    </div>
    """, unsafe_allow_html=True)

    for h in holdings:
        tk     = h["ticker"]
        sc     = score_map.get(tk)
        cost   = float(h.get("avg_cost", 0) or 0)
        shares = float(h.get("shares", 0) or 0)
        entry  = h.get("entry_date", "")

        # Price: use score dict first (from fundamentals cache), then yfinance
        live_price = None
        if sc and sc.get("price"):
            live_price = float(sc["price"])
        else:
            try:
                from model_engine import get_current_price
                p = get_current_price(tk)
                if p and p > 0:
                    live_price = p
            except Exception:
                pass

        market_value   = live_price * shares if live_price and shares else (cost * shares if cost and shares else None)
        unrealized_gl  = (live_price - cost) * shares if live_price and cost and shares else None
        gl_pct         = ((live_price - cost) / cost * 100) if live_price and cost else None
        gl_c           = "#00ff87" if (unrealized_gl or 0) >= 0 else "#ef4444"
        gl_arrow       = "▲" if (unrealized_gl or 0) >= 0 else "▼"

        if sc:
            comp   = sc.get("adj_composite", sc.get("composite", 50))
            # Override stale cached signal using live score thresholds
            act    = "SELL" if comp < 45 else ("BUY" if comp >= 60 else "HOLD")
            sig    = sc.get("signal", "")
            mom    = sc.get("momentum", 50)
            qual   = sc.get("quality", 50)
            vol    = sc.get("volume", 50)
            val    = sc.get("value", 50)
            sent   = sc.get("sentiment", 50)
            delta  = sc.get("score_delta", 0)
            sector = sc.get("sector", "")

            # Factor driver text
            pillars_sorted = sorted([("MOM",mom),("QUAL",qual),("VOL",vol),("VAL",val),("SENT",sent)],
                                     key=lambda x:x[1], reverse=True)
            top2   = [p[0] for p in pillars_sorted[:2]]
            weak   = [p[0] for p in pillars_sorted if p[1] < 45]
            driver = f"Driven by {top2[0]} + {top2[1]}"
            if weak: driver += f" — watch {weak[0]}"
        else:
            comp, act, sig = 0, "N/A", "NOT IN UNIVERSE"
            mom = qual = vol = val = sent = delta = 0
            sector = "Unknown"
            driver = ""  # ticker not in universe — no signal, shown by N/A badge

        act_colors = {
            "BUY":  ("#00ff87","rgba(0,255,135,.1)" ,"2px solid #00ff87"),
            "HOLD": ("#fbbf24","rgba(251,191,36,.07)","1px solid rgba(251,191,36,.25)"),
            "SELL": ("#ef4444","rgba(239,68,68,.08)" ,"2px solid #ef4444"),
            "N/A":  ("#475569","rgba(255,255,255,.02)","1px solid rgba(255,255,255,.07)"),
        }
        act_c, act_bg, act_brd = act_colors.get(act, act_colors["N/A"])
        arrow = "▲" if act=="BUY" else "▼" if act=="SELL" else "─"
        act_label = "High" if act=="BUY" else "Low" if act=="SELL" else "Moderate"

        # Pillar bars — clean horizontal with gradient fill
        def pbar_row(name, v):
            c = "#00ff87" if v>=65 else "#fbbf24" if v>=50 else "#ef4444"
            tip   = PILLAR_TIPS.get(name, {})
            tbody = tip.get('body', '')
            twt   = tip.get('weight', '')
            whtml = f'<div class="tip-weight">{twt}</div>' if twt else ''
            lbl   = (
                f'<span class="qntm-tip" style="font-size:13px;color:#64748b;cursor:help;">'
                f'{name}<i class="tip-icon">i</i>'
                f'<span class="tip-box">'
                f'<div class="tip-title">{name}</div>'
                f'<div class="tip-body">{tbody}</div>'
                f'{whtml}</span></span>'
            )
            return (
                f'<div style="min-width:0;">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">'
                f'{lbl}'
                f'<div style="font-family:DM Mono,monospace;font-size:14px;color:{c};font-weight:700;">{v:.0f}</div>'
                f'</div>'
                f'<div style="background:rgba(255,255,255,.05);border-radius:3px;height:5px;overflow:hidden;">'
                f'<div style="width:{v}%;height:100%;background:linear-gradient(90deg,{c}99,{c});border-radius:3px;"></div>'
                f'</div></div>'
            )

        pillar_html = "".join([
            pbar_row(n, v)
            for n,v in [
                ("Momentum", mom),
                ("Quality",  qual),
                ("Volume",   vol),
                ("Value",    val),
                ("Sentiment",sent),
            ]
        ])

        delta_c = "#00ff87" if delta >= 0 else "#ef4444"
        delta_str = f"+{delta:.1f}" if delta >= 0 else f"{delta:.1f}"
        quant_disp = f"{sc['composite']:.1f}" if sc and sc.get('composite') is not None else "—"
        delta_disp = delta_str if sc else "—"
        sig_disp   = (sig[:10] if sig else "—") if sig else "—"

        if live_price:
            price_block = (f'<div><div style="font-size:14px;color:#94a3b8;letter-spacing:.06em;margin-bottom:2px;">CURRENT PRICE</div>'
                          f'<div style="font-family:DM Mono,monospace;font-size:16px;color:#d4a843;font-weight:500;">${live_price:,.2f}</div></div>')
        else:
            price_block = ('<div><div style="font-size:14px;color:#94a3b8;letter-spacing:.06em;margin-bottom:2px;">CURRENT PRICE</div>'
                          '<div style="font-family:DM Mono,monospace;font-size:16px;color:#94a3b8;">—</div></div>')
        shares_block = (f'<div><div style="font-size:14px;color:#94a3b8;letter-spacing:.06em;margin-bottom:2px;">SHARES</div>'
                       f'<div style="font-family:DM Mono,monospace;font-size:16px;color:#94a3b8;">{shares:.2f}</div></div>')
        cost_block = (f'<div><div style="font-size:14px;color:#94a3b8;letter-spacing:.06em;margin-bottom:2px;">AVG COST</div>'
                     f'<div style="font-family:DM Mono,monospace;font-size:16px;color:#94a3b8;">${cost:.2f}</div></div>') if cost > 0 else ""
        mv_block = (f'<div><div style="font-size:14px;color:#94a3b8;letter-spacing:.06em;margin-bottom:2px;">MKT VALUE</div>'
                   f'<div style="font-family:DM Mono,monospace;font-size:16px;color:#e2e8f0;">${market_value:,.0f}</div></div>') if market_value else ""
        gl_block = (f'<div><div style="font-size:14px;color:#94a3b8;letter-spacing:.06em;margin-bottom:2px;">P&amp;L</div>'
                   f'<div style="font-family:DM Mono,monospace;font-size:16px;color:{gl_c};">{gl_arrow} ${abs(unrealized_gl):,.0f}</div></div>') if unrealized_gl is not None else ""
        entry_block = (f'<div style="font-size:13px;color:#94a3b8;">entry '
                      f'<span style="color:#94a3b8;font-family:DM Mono,monospace;">{str(entry)[:10]}</span></div>') if entry else ""

        card_html = (
            f'<div style="background:{act_bg};border:{act_brd};border-radius:10px;padding:16px;margin-bottom:10px;overflow:hidden;">'
            # Header row
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;">'
            f'<div style="min-width:0;flex:1;">'
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap;">'
            f'<span style="font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:#e2e8f0;">{tk}</span>'
            f'<span style="font-family:Syne,sans-serif;font-size:13px;font-weight:700;color:{act_c};'
            f'background:{act_c}18;border:1px solid {act_c}44;padding:2px 8px;border-radius:3px;'
            f'letter-spacing:.1em;white-space:nowrap;">{arrow} {act}</span>'
            f'<span style="font-size:14px;color:#94a3b8;">{sector}</span>'
            f'</div>'
            f'<div style="font-size:13px;color:#94a3b8;">{driver}</div>'
            f'</div>'
            f'<div style="text-align:right;flex-shrink:0;margin-left:8px;">'
            f'<div style="font-family:DM Mono,monospace;font-size:28px;font-weight:700;color:{act_c};">{comp:.0f}</div>'
            f'<div style="font-size:13px;color:#94a3b8;">blended score</div>'
            f'<div style="font-size:13px;color:{delta_c};">macro {delta_str}</div>'
            f'</div></div>'
            # Position data row
            f'<div style="display:flex;gap:12px;margin-bottom:12px;flex-wrap:wrap;align-items:flex-end;">'
            f'{price_block}{shares_block}{cost_block}{mv_block}{gl_block}{entry_block}'
            f'</div>'
            # Pillar bars — 2-col grid on mobile
            f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:10px;">{pillar_html}</div>'
            # Score boxes
            f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;padding-top:10px;border-top:1px solid rgba(255,255,255,.05);">'
            f'<div style="background:rgba(255,255,255,.04);border-radius:4px;padding:6px 8px;">'
            f'<div style="font-size:14px;color:#94a3b8;letter-spacing:.04em;margin-bottom:3px;">QUANT</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:16px;color:#94a3b8;">{quant_disp}</div></div>'
            f'<div style="background:rgba(255,255,255,.04);border-radius:4px;padding:6px 8px;">'
            f'<div style="font-size:14px;color:#94a3b8;letter-spacing:.04em;margin-bottom:3px;">MACRO</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:16px;color:{delta_c};">{delta_disp}</div></div>'
            f'<div style="background:rgba(255,255,255,.04);border-radius:4px;padding:6px 8px;">'
            f'<div style="font-size:14px;color:#94a3b8;letter-spacing:.04em;margin-bottom:3px;">BLEND</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:16px;color:#d4a843;">75/25</div></div>'
            f'<div style="background:rgba(255,255,255,.04);border-radius:4px;padding:6px 8px;overflow:hidden;">'
            f'<div style="font-size:14px;color:#94a3b8;letter-spacing:.04em;margin-bottom:3px;">SIGNAL</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:14px;color:#94a3b8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{sig_disp}</div></div>'
            f'</div></div>'
        )
        st.markdown(card_html, unsafe_allow_html=True)

        if st.button(f"🗑 Remove {tk}", key=f"del_{tk}"):
            delete_holding(uid(), tk)
            st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)

    # ── Export to Excel ───────────────────────────────────────────────────────
    if holdings:
        try:
            export_rows = []
            for h in holdings:
                score_data = score_map.get(h["ticker"], {})
                export_rows.append({
                    "Ticker":         h["ticker"],
                    "Entry Date":     h.get("entry_date", ""),
                    "Entry Price":    h.get("entry_price", ""),
                    "Current Price":  score_data.get("price", ""),
                    "Shares":         round(h["pos_size"] / h["entry_price"], 4) if h.get("entry_price") and h["entry_price"] > 0 else "",
                    "Position Value": h.get("pos_size", 10000),
                    "P&L ($)":        round(h.get("pnl", 0), 2),
                    "Return (%)":     round(h.get("pnl_pct", 0), 2),
                    "Score":          round(score_data.get("adj_composite", score_data.get("composite", 0)), 1),
                    "Momentum":       round(score_data.get("momentum", 0), 1),
                    "Quality":        round(score_data.get("quality", 0), 1),
                    "Volume":         round(score_data.get("volume", 0), 1),
                    "Value":          round(score_data.get("value", 0), 1),
                    "Sentiment":      round(score_data.get("sentiment", 0), 1),
                    "Signal":         score_data.get("adj_action", score_data.get("action", "")),
                })
            headers = ["Ticker","Entry Date","Entry Price","Current Price","Shares","Position Value","P&L ($)","Return (%)","Score","Momentum","Quality","Volume","Value","Sentiment","Signal"]
            xl = _make_excel(export_rows, headers, "My Portfolio")
            st.download_button(
                label="⬇ Export to Excel",
                data=xl,
                file_name="qntm_my_portfolio.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="port_export"
            )
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# ALERTS PAGE
# ══════════════════════════════════════════════════════════════════════════════
def page_simulator():
    page_summary(
        "🧮", "Portfolio Simulator",
        "Build a hypothetical portfolio from current HIGH conviction signals. "
        "Requires a universe scan — hit Rescan if scores look stale.",
    )
    st.markdown('<div style="padding:0 32px;">', unsafe_allow_html=True)

    if not is_pro():
        st.markdown(
            '<div style="background:rgba(212,168,67,.07);border:1px solid rgba(212,168,67,.25);'
            'border-radius:10px;padding:28px 24px;text-align:center;margin:24px 0;">'
            '<div style="font-size:28px;margin-bottom:12px;">🧮</div>'
            '<div style="font-family:Syne,sans-serif;font-size:18px;font-weight:700;color:#d4a843;margin-bottom:8px;">Portfolio Simulator</div>'
            '<div style="font-size:14px;color:#94a3b8;margin-bottom:20px;">'
            'Build a hypothetical portfolio from current HIGH conviction signals.</div>'
            '<div style="font-size:13px;color:#64748b;">Pro feature — upgrade to access</div>'
            '</div>', unsafe_allow_html=True)
        st.markdown(_cta_gold("Upgrade to Pro — $29/mo →", "?nav=register"), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        return

    # Rescan buttons — right here so users don't have to go back to Screener
    _s1, _s2 = st.columns(2)
    with _s1:
        if st.button("🔄 Rescan", key="sim_rescan", use_container_width=True):
            st.session_state.scan_results = None
            # Run the scan immediately (same as screener auto-load)
            from model_engine import fetch_macro_overlay, apply_macro_overlay, run_full_scan
            from model_engine import SECTORS as _SIM_SECTORS
            with st.spinner("Rescanning universe..."):
                _raw = run_full_scan(use_live_prices=False)
                _mac = fetch_macro_overlay()
                for _r in _raw:
                    if not _r.get("sector") or _r.get("sector") == "Unknown":
                        _r["sector"] = _SIM_SECTORS.get(_r["ticker"], "Unknown")
                _scored = apply_macro_overlay(_raw, _mac)
                from db import get_signal_snapshot as _gss
                st.session_state.scan_results = _scored
                st.session_state.macro_data = _mac
            st.rerun()

    scan = st.session_state.get("scan_results") or []
    all_buys = sorted(
        [r for r in scan if r.get("adj_action", r.get("action")) == "BUY"],
        key=lambda x: x.get("adj_composite", x.get("composite", 0)), reverse=True
    )
    ticker_map = {r["ticker"]: r for r in scan}

    if not all_buys:
        st.info("No HIGH conviction signals loaded. Hit 🔄 Rescan Universe above to load scores.")
        st.markdown('</div>', unsafe_allow_html=True)
        return

    def profile_tickers(profile):
        if profile == "HIGH":
            ranked = sorted(all_buys, key=lambda x: x.get("momentum", 0), reverse=True)
        elif profile == "LOW":
            ranked = sorted(all_buys, key=lambda x: (x.get("quality", 0) + x.get("value", 0)) / 2, reverse=True)
        else:
            ranked = all_buys
        return [r["ticker"] for r in ranked[:20]]

    if "sim_profile" not in st.session_state:
        st.session_state.sim_profile = "MEDIUM"
    if "sim_selected" not in st.session_state or st.session_state.get("sim_profile_applied") != st.session_state.sim_profile:
        st.session_state.sim_selected = profile_tickers(st.session_state.sim_profile)
        st.session_state.sim_weights  = {}
        st.session_state.sim_profile_applied = st.session_state.sim_profile

    available = set(ticker_map.keys())
    st.session_state.sim_selected = [t for t in st.session_state.sim_selected if t in available]

    sim_amount = st.number_input("Investment Amount ($)", min_value=1000, max_value=10000000,
                                  value=50000, step=1000, format="%d", key="sim_amount")
    equal_weight = st.toggle("Equal weight", value=True, key="sim_equal")

    PROFILES = {
        "HIGH":   ("🔥 High Risk",   "Top 20 by momentum. Higher volatility, higher potential return."),
        "MEDIUM": ("⚖️ Medium Risk", "Top 20 by conviction score. Balanced. Model default."),
        "LOW":    ("🛡 Low Risk",    "Top 20 by quality + value. More defensive positioning."),
    }
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
    st.markdown('<div style="font-family:DM Mono,monospace;font-size:11px;color:#64748b;letter-spacing:.08em;margin-bottom:10px;">RISK PROFILE</div>', unsafe_allow_html=True)

    p_cols = st.columns(3)
    for col, (pk, (plbl, pdesc)) in zip(p_cols, PROFILES.items()):
        with col:
            active = st.session_state.sim_profile == pk
            bg     = "rgba(212,168,67,.12)" if pk=="HIGH" else "rgba(0,255,135,.10)" if pk=="LOW" else "rgba(255,255,255,.06)"
            border = "rgba(212,168,67,.6)"  if pk=="HIGH" else "rgba(0,255,135,.5)"  if pk=="LOW" else "rgba(148,163,184,.35)"
            tc     = "#d4a843" if pk=="HIGH" else "#00ff87" if pk=="LOW" else "#94a3b8"
            if active:
                bg = bg.replace(",.12",",.2").replace(",.10",",.18").replace(",.06",",.12")
            st.markdown(
                f'<div style="background:{bg};border:1px solid {border};border-radius:8px;'
                f'padding:10px 8px;text-align:center;margin-bottom:4px;">'
                f'<div style="font-size:13px;font-weight:700;color:{tc};">{plbl}</div>'
                f'<div style="font-size:10px;color:#64748b;margin-top:3px;line-height:1.3;">{pdesc[:55]}</div>'
                f'</div>', unsafe_allow_html=True)
            if st.button("✓ Selected" if active else "Select", key=f"prof_{pk}", use_container_width=True):
                st.session_state.sim_profile = pk
                st.session_state.sim_selected = profile_tickers(pk)
                st.session_state.sim_weights  = {}
                st.session_state.sim_profile_applied = pk
                st.rerun()

    st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)
    st.markdown('<div style="font-family:DM Mono,monospace;font-size:11px;color:#64748b;letter-spacing:.08em;margin-bottom:6px;">ADD POSITION</div>', unsafe_allow_html=True)
    add_query = st.text_input("Search ticker or company", key="sim_add_query",
                               placeholder="e.g. NVDA, Apple…", label_visibility="collapsed")
    if add_query and add_query.strip():
        q = add_query.strip().upper()
        matches = sorted(
            [r for r in scan if r["ticker"].startswith(q) or q in r["ticker"]],
            key=lambda x: x.get("adj_composite", x.get("composite", 0)), reverse=True
        )[:8]
        if matches:
            for r in matches:
                tk    = r["ticker"]
                score = r.get("adj_composite", r.get("composite", 0))
                already = tk in st.session_state.sim_selected
                if st.button(f"{"✓ In portfolio" if already else "+ Add"}  {tk} · score {score:.0f}",
                              key=f"simadd_{tk}", use_container_width=True, disabled=already):
                    st.session_state.sim_selected.append(tk)
                    st.rerun()
        else:
            st.caption("No matches in current scan.")

    selected_rows = [ticker_map[t] for t in st.session_state.sim_selected if t in ticker_map]
    n_sel = len(selected_rows)

    if n_sel == 0:
        st.info("No positions — select a risk profile or search for a ticker above.")
        st.markdown('</div>', unsafe_allow_html=True)
        return

    weight_map = {r["ticker"]: 100.0 / n_sel for r in selected_rows} if equal_weight else {
        r["ticker"]: st.session_state.sim_weights.get(r["ticker"], 100.0 / n_sel) for r in selected_rows
    }
    if not equal_weight:
        total_w = sum(weight_map.values())
        weight_map = {tk: v / total_w * 100 for tk, v in weight_map.items()} if total_w > 0 else weight_map

    alloc = []
    for r in selected_rows:
        tk    = r["ticker"]
        score = r.get("adj_composite", r.get("composite", 0))
        price = r.get("price")
        pct   = weight_map[tk]
        w_dollar = sim_amount * pct / 100
        shares   = round(w_dollar / price, 4) if price and price > 0 else None
        alloc.append({"ticker": tk, "score": score, "price": price, "allocation": w_dollar,
                       "pct": pct, "shares": shares, "sector": r.get("sector", "Unknown"),
                       "momentum": r.get("momentum", 50), "quality": r.get("quality", 50),
                       "volume": r.get("volume", 50), "value": r.get("value", 50),
                       "sentiment": r.get("sentiment", 50)})

    weighted_score = sum(a["pct"] * a["score"] for a in alloc) / 100
    sc_col = "#00ff87" if weighted_score >= 70 else "#fbbf24" if weighted_score >= 55 else "#ef4444"

    st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)
    st.markdown(
        f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:16px;">'
        f'<div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);border-radius:8px;padding:12px;text-align:center;">'
        f'<div style="font-family:DM Mono,monospace;font-size:10px;color:#64748b;letter-spacing:.08em;margin-bottom:4px;">INVESTED</div>'
        f'<div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:#d4a843;">${sim_amount:,.0f}</div></div>'
        f'<div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);border-radius:8px;padding:12px;text-align:center;">'
        f'<div style="font-family:DM Mono,monospace;font-size:10px;color:#64748b;letter-spacing:.08em;margin-bottom:4px;">POSITIONS</div>'
        f'<div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:#cbd5e1;">{n_sel}</div></div>'
        f'<div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);border-radius:8px;padding:12px;text-align:center;">'
        f'<div style="font-family:DM Mono,monospace;font-size:10px;color:#64748b;letter-spacing:.08em;margin-bottom:4px;">AVG SCORE</div>'
        f'<div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:{sc_col};">{weighted_score:.1f}</div></div>'
        f'</div>', unsafe_allow_html=True)

    sector_totals = {}
    for a in alloc:
        sector_totals[a["sector"]] = sector_totals.get(a["sector"], 0) + a["allocation"]
    bars_html = ""
    for sec, val in sorted(sector_totals.items(), key=lambda x: x[1], reverse=True)[:6]:
        pct = val / sim_amount * 100
        bars_html += (f'<div style="margin-bottom:8px;"><div style="display:flex;justify-content:space-between;margin-bottom:3px;">'
                      f'<span style="font-size:12px;color:#94a3b8;">{sec}</span>'
                      f'<span style="font-family:DM Mono,monospace;font-size:12px;color:#cbd5e1;">{pct:.1f}%</span></div>'
                      f'<div style="background:rgba(255,255,255,.06);border-radius:3px;height:5px;">'
                      f'<div style="width:{min(pct,100):.1f}%;height:100%;background:#d4a843;border-radius:3px;"></div></div></div>')
    st.markdown(
        f'<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);'
        f'border-radius:8px;padding:16px 20px;margin-bottom:16px;">'
        f'<div style="font-family:DM Mono,monospace;font-size:11px;color:#64748b;letter-spacing:.08em;margin-bottom:12px;">SECTOR EXPOSURE</div>'
        f'{bars_html}</div>', unsafe_allow_html=True)

    st.markdown('<div style="font-family:DM Mono,monospace;font-size:11px;color:#64748b;letter-spacing:.08em;margin-bottom:8px;">POSITIONS</div>', unsafe_allow_html=True)

    def pill_bar(v):
        c = "#00ff87" if v >= 60 else ("#f59e0b" if v >= 45 else "#ef4444")
        return (f'<div style="height:4px;border-radius:2px;background:rgba(255,255,255,.08);margin:1px 0;">'
                f'<div style="width:{max(4,int(v))}%;height:100%;background:{c};border-radius:2px;"></div></div>')

    for a in sorted(alloc, key=lambda x: x["score"], reverse=True):
        sc_color  = "#00ff87" if a["score"] >= 70 else "#fbbf24" if a["score"] >= 55 else "#ef4444"
        price_str = f'${a["price"]:,.2f}' if a["price"] else "—"
        shares_str = f'{a["shares"]:,.3f}' if a["shares"] else "—"
        with st.expander(f'{a["ticker"]}  ·  ${a["allocation"]:,.0f} ({a["pct"]:.1f}%)  ·  score {a["score"]:.0f}', expanded=False):
            st.markdown(
                f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px;">'
                f'<div style="background:rgba(255,255,255,.04);border-radius:6px;padding:10px;text-align:center;">'
                f'<div style="font-size:10px;color:#64748b;margin-bottom:3px;">PRICE</div>'
                f'<div style="font-family:DM Mono,monospace;font-size:15px;color:#cbd5e1;">{price_str}</div></div>'
                f'<div style="background:rgba(255,255,255,.04);border-radius:6px;padding:10px;text-align:center;">'
                f'<div style="font-size:10px;color:#64748b;margin-bottom:3px;">SHARES</div>'
                f'<div style="font-family:DM Mono,monospace;font-size:15px;color:#94a3b8;">{shares_str}</div></div>'
                f'<div style="background:rgba(255,255,255,.04);border-radius:6px;padding:10px;text-align:center;">'
                f'<div style="font-size:10px;color:#64748b;margin-bottom:3px;">CONVICTION</div>'
                f'<div style="font-family:Syne,sans-serif;font-size:16px;font-weight:800;color:{sc_color};">{a["score"]:.0f}</div></div>'
                f'</div>', unsafe_allow_html=True)
            st.markdown(
                f'<div style="margin-bottom:10px;">'
                f'<div style="font-size:10px;color:#64748b;margin-bottom:1px;">MOM {a["momentum"]:.0f}</div>{pill_bar(a["momentum"])}'
                f'<div style="font-size:10px;color:#64748b;margin-top:4px;margin-bottom:1px;">QUAL {a["quality"]:.0f}</div>{pill_bar(a["quality"])}'
                f'<div style="font-size:10px;color:#64748b;margin-top:4px;margin-bottom:1px;">VOL {a["volume"]:.0f}</div>{pill_bar(a["volume"])}'
                f'<div style="font-size:10px;color:#64748b;margin-top:4px;margin-bottom:1px;">VAL {a["value"]:.0f}</div>{pill_bar(a["value"])}'
                f'<div style="font-size:10px;color:#64748b;margin-top:4px;margin-bottom:1px;">SENT {a["sentiment"]:.0f}</div>{pill_bar(a["sentiment"])}'
                f'</div>', unsafe_allow_html=True)
            st.markdown(f'<div style="font-size:12px;color:#475569;margin-bottom:8px;">{a["sector"]}</div>', unsafe_allow_html=True)
            if not equal_weight:
                raw_pct = st.session_state.sim_weights.get(a["ticker"], round(100.0 / n_sel, 1))
                new_pct = st.slider(f"Weight % for {a['ticker']}", min_value=0.5, max_value=50.0,
                                     value=float(raw_pct), step=0.5, key=f"sim_w_{a['ticker']}",
                                     help="Normalised to 100% across all positions")
                if new_pct != raw_pct:
                    st.session_state.sim_weights[a["ticker"]] = new_pct
                    st.rerun()
            if st.button(f"✕ Remove {a['ticker']}", key=f"sim_rm_{a['ticker']}", use_container_width=True):
                st.session_state.sim_selected.remove(a["ticker"])
                st.session_state.sim_weights.pop(a["ticker"], None)
                st.rerun()

    st.markdown(
        f'<div style="font-size:11px;color:#475569;padding-top:12px;margin-top:8px;'
        f'border-top:1px solid rgba(255,255,255,.05);">'
        f'{"Equal weight" if equal_weight else "Custom weight (normalised)"} · ${sim_amount:,.0f} across {n_sel} positions · '
        f'Shares at last scan price · Hypothetical — not investment advice.</div>',
        unsafe_allow_html=True)

    # ── Export to Excel ───────────────────────────────────────────────────────
    try:
        export_rows = [{
            "Ticker":       a["ticker"],
            "Sector":       a["sector"],
            "Price":        a["price"] or "",
            "Allocation ($)": round(a["allocation"], 2),
            "Weight (%)":   round(a["pct"], 2),
            "Shares":       a["shares"] or "",
            "Score":        round(a["score"], 1),
            "Momentum":     round(a["momentum"], 1),
            "Quality":      round(a["quality"], 1),
            "Volume":       round(a["volume"], 1),
            "Value":        round(a["value"], 1),
            "Sentiment":    round(a["sentiment"], 1),
        } for a in sorted(alloc, key=lambda x: x["score"], reverse=True)]
        headers = ["Ticker","Sector","Price","Allocation ($)","Weight (%)","Shares","Score","Momentum","Quality","Volume","Value","Sentiment"]
        xl = _make_excel(export_rows, headers, "Simulator")
        st.download_button(
            label="⬇ Export to Excel",
            data=xl,
            file_name="qntm_simulator.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="sim_export"
        )
    except Exception:
        pass
    st.markdown('</div>', unsafe_allow_html=True)


def page_alerts():
    user = st.session_state.user or {}
    plan = user.get("plan", "free")
    has_alerts = plan_limit(plan, "notifications")

    page_summary(
        "🔔", "Alerts",
        "Signal changes on your holdings — the moment the model issues a HIGH or LOW conviction signal, you'll know. "
        "Macro regime shifts (war, oil spikes, rate changes) trigger alerts too. "
        "Pro members get email notifications on every signal change across their portfolio.",

    )
    st.markdown('<div style="padding:0 32px;">', unsafe_allow_html=True)

    # ── Free tier gate ─────────────────────────────────────────────────────────
    if not has_alerts:
        st.markdown("""
        <div style="background:rgba(212,168,67,.04);border:1px solid rgba(212,168,67,.2);
             border-radius:12px;padding:48px;text-align:center;margin-bottom:24px;">
          <div style="font-size:52px;margin-bottom:16px;">🔔</div>
          <div style="font-family:'Syne',sans-serif;font-size:24px;font-weight:800;
               color:#d4a843;margin-bottom:12px;">Pro Feature — Signal Alerts</div>
          <div style="color:#64748b;max-width:520px;margin:0 auto;line-height:1.8;margin-bottom:32px;">
            Get notified the moment the model issues a BUY or SELL signal on any of
            your holdings. Macro regime changes, hidden gem alerts, and weekly
            performance summaries all included.
          </div>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;max-width:480px;
               margin:0 auto 32px;text-align:center;">
            <div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);
                 border-radius:6px;padding:14px 10px;">
              <div style="font-size:20px;margin-bottom:6px;">📈</div>
              <div style="font-size:13px;color:#94a3b8;line-height:1.5;">BUY / SELL<br>signal alerts</div>
            </div>
            <div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);
                 border-radius:6px;padding:14px 10px;">
              <div style="font-size:20px;margin-bottom:6px;">⚡</div>
              <div style="font-size:13px;color:#94a3b8;line-height:1.5;">Macro regime<br>change alerts</div>
            </div>
            <div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);
                 border-radius:6px;padding:14px 10px;">
              <div style="font-size:20px;margin-bottom:6px;">💎</div>
              <div style="font-size:13px;color:#94a3b8;line-height:1.5;">Hidden gem<br>detection</div>
            </div>
          </div>
          <div style="font-family:'DM Mono',monospace;font-size:13px;color:#d4a843;margin-bottom:8px;">
            PRO PLAN — $29/MO · FOUNDING MEMBER — FREE (FIRST 50)
          </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(_cta_gold("Upgrade to Pro — Unlock Alerts", "?nav=register"), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        return

    # ── Pro user — show notifications ──────────────────────────────────────────
    notifs = get_notifications(uid())
    unread = sum(1 for n in notifs if not n.get("is_read"))

    # Action bar
    ac1, ac2, ac3 = st.columns([2, 1, 1])
    with ac1:
        st.markdown(f"""
        <div style="padding:8px 0;font-size:13px;color:#94a3b8;">
          {len(notifs)} notifications
          {'· <span style="color:#00ff87;">' + str(unread) + ' unread</span>' if unread else ''}
        </div>
        """, unsafe_allow_html=True)
    with ac2:
        if unread > 0 and st.button("✓ Read", key="mark_read", use_container_width=True):
            mark_notifications_read(uid())
            st.rerun()
    with ac3:
        filter_type = st.selectbox("Filter", ["All","HIGH","LOW","Macro","Gems"], key="notif_filter", label_visibility="collapsed")

    st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)

    if not notifs:
        st.markdown("""
        <div style="text-align:center;padding:48px 24px;max-width:440px;margin:0 auto;">
          <div style="font-size:48px;margin-bottom:16px;">🔔</div>
          <div style="font-family:Syne,sans-serif;font-size:20px;font-weight:800;color:#e2e8f0;margin-bottom:10px;">
            No alerts yet
          </div>
          <div style="font-size:13px;color:#64748b;line-height:1.8;margin-bottom:20px;">
            Alerts fire when the model issues a signal change on one of your holdings,
            or when a macro regime shift affects the market. Add positions in Portfolio
            and the model will watch them every scan.
          </div>
          <div style="font-size:13px;color:#94a3b8;">Macro alerts are always active — portfolio alerts require holdings</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        icon_map = {
            "buy_signal":  ("▲", "#00ff87"),
            "sell_signal": ("▼", "#ef4444"),
            "hold_alert":  ("─", "#fbbf24"),
            "hidden_gem":  ("💎", "#00ff87"),
            "macro_alert": ("⚡", "#d4a843"),
            "system":      ("ℹ", "#475569"),
        }
        type_filter_map = {
            "All": None,
            "HIGH": "buy_signal",
            "LOW": "sell_signal",
            "Macro": "macro_alert",
            "Gems": "hidden_gem",
        }
        filter_val = type_filter_map.get(filter_type)

        shown = 0
        for n in notifs[:50]:
            ntype = n.get("notification_type", "system")
            if filter_val and ntype != filter_val:
                continue
            shown += 1
            icon, icolor = icon_map.get(ntype, ("ℹ", "#475569"))
            is_read = n.get("is_read", False)
            bg  = "rgba(255,255,255,.015)" if is_read else "rgba(255,255,255,.03)"
            brd = "rgba(255,255,255,.05)"  if is_read else f"{icolor}33"
            opacity = "opacity:.65;" if is_read else ""
            created = str(n.get("created_at", ""))[:16].replace("T", " ")

            st.markdown(f"""
            <div style="background:{bg};border:1px solid {brd};border-left:3px solid {icolor};
                 border-radius:6px;padding:14px 16px;margin-bottom:8px;{opacity}">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;">
                <div style="display:flex;align-items:flex-start;gap:10px;flex:1;">
                  <span style="font-size:14px;color:{icolor};flex-shrink:0;margin-top:1px;">{icon}</span>
                  <div>
                    <div style="font-family:'Syne',sans-serif;font-size:13px;font-weight:600;
                         color:{'#e2e8f0' if not is_read else '#94a3b8'};">
                      {n.get('title','').replace('BUY','High Conviction').replace('SELL','Low Conviction').replace('HOLD','Moderate Conviction')}
                    </div>
                    <div style="font-size:13px;color:#94a3b8;margin-top:3px;line-height:1.5;">
                      {n.get('body','').replace('BUY','High Conviction').replace('SELL','Low Conviction').replace('HOLD','Moderate Conviction')}
                    </div>
                  </div>
                </div>
                <div style="font-family:'DM Mono',monospace;font-size:13px;color:#64748b;
                     flex-shrink:0;white-space:nowrap;">{created}</div>
              </div>
            </div>
            """, unsafe_allow_html=True)

        if shown == 0:
            st.markdown(f'<div style="color:#64748b;padding:24px;text-align:center;font-size:13px;">No {filter_type.lower()} alerts</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# ACCOUNT PAGE
# ══════════════════════════════════════════════════════════════════════════════
def page_account():
    from db import disable_mfa, upgrade_plan, plan_limit
    user = st.session_state.user or {}
    plan = user.get("plan", "free")

    page_summary(
        "⚙️", "Account",
        "Manage your profile, secure your account with two-factor authentication, and upgrade your plan. "
        "Founding Member gives you full Pro access free — unlimited holdings, Hidden Gems, and signal alerts — "
        "locked in for the first 50 users.",
    )
    st.markdown('<div style="padding:0 32px;">', unsafe_allow_html=True)

    tab_profile, tab_security, tab_plan, tab_notifs = st.tabs([
        "Profile", "Security & MFA", "Plan & Billing", "Notification Prefs"
    ])

    # ── PROFILE ───────────────────────────────────────────────────────────────
    with tab_profile:
        st.markdown('<div style="height:16px;"></div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            new_name = st.text_input("Full name", value=user.get("full_name",""), key="acc_name")
            st.text_input("Email address", value=user.get("email",""), disabled=True,
                          help="Email cannot be changed. Contact support if needed.")
            st.text_input("Member since",
                          value=str(user.get("created_at",""))[:10] or "—",
                          disabled=True)
            plan_display = plan.upper()
            plan_c = "#d4a843" if plan in ("pro","institutional") else "#475569"
            st.markdown(f"""
            <div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);
                 border-radius:4px;padding:10px 14px;margin:8px 0;">
              <span style="font-size:13px;color:#64748b;letter-spacing:.1em;">PLAN </span>
              <span style="font-family:'Syne',sans-serif;font-weight:700;color:{plan_c};">
                {plan_display}
              </span>
            </div>
            """, unsafe_allow_html=True)
            st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)
            if st.button("Save Profile", key="acc_save"):
                if new_name.strip():
                    from db import encrypt_field
                    ok = update_preferences(uid(), {"full_name_enc": encrypt_field(new_name.strip())})
                    if ok:
                        st.session_state.user["full_name"] = new_name.strip()
                        st.success("Profile saved")
                    else:
                        st.error("Save failed — try again")
                else:
                    st.error("Name cannot be blank")

    # ── SECURITY & MFA ────────────────────────────────────────────────────────
    with tab_security:
        st.markdown('<div style="height:16px;"></div>', unsafe_allow_html=True)
        mfa_data = get_user_mfa(uid())
        mfa_on   = mfa_data.get("mfa_enabled", False)

        if mfa_on:
            st.markdown("""
            <div style="background:rgba(0,255,135,.06);border:1px solid rgba(0,255,135,.25);
                 border-radius:8px;padding:18px 20px;margin-bottom:20px;
                 display:flex;align-items:center;gap:12px;">
              <span style="font-size:20px;color:#00ff87;">✓</span>
              <div>
                <div style="font-family:'Syne',sans-serif;font-size:14px;font-weight:700;color:#00ff87;">
                  Two-factor authentication is enabled
                </div>
                <div style="font-size:14px;color:#94a3b8;margin-top:2px;">
                  Your account is protected with TOTP (Google Authenticator / Authy)
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Disable MFA", key="dis_mfa"):
                if disable_mfa(uid()):
                    st.session_state.user["mfa_enabled"] = False
                    st.success("MFA disabled")
                    st.rerun()
                else:
                    st.error("Failed to disable MFA")
        else:
            st.markdown("""
            <div style="background:rgba(239,68,68,.05);border:1px solid rgba(239,68,68,.2);
                 border-radius:8px;padding:18px 20px;margin-bottom:20px;">
              <div style="font-family:'Syne',sans-serif;font-size:14px;font-weight:700;
                   color:#ef4444;margin-bottom:4px;">⚠ Two-factor authentication is off</div>
              <div style="font-size:14px;color:#94a3b8;">
                We strongly recommend enabling MFA to protect your account.
                Use Google Authenticator, Authy, or any TOTP app.
              </div>
            </div>
            """, unsafe_allow_html=True)

            if st.button("Enable MFA →", key="en_mfa"):
                st.session_state.show_mfa_setup = True

            if st.session_state.get("show_mfa_setup"):
                st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)
                if not st.session_state.get("totp_secret_temp"):
                    result = generate_totp_secret(user.get("email", "user"))
                    st.session_state.totp_secret_temp   = result["secret"]
                    st.session_state.totp_qr_bytes_temp = result["qr_bytes"]

                st.markdown("""
                <div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);
                     border-radius:8px;padding:24px;margin-bottom:16px;">
                  <div style="font-family:'Syne',sans-serif;font-size:13px;font-weight:700;
                       color:#e2e8f0;margin-bottom:16px;">Set up two-factor authentication</div>
                """, unsafe_allow_html=True)

                col_qr, col_inst = st.columns([1, 2])
                with col_qr:
                    st.image(st.session_state.totp_qr_bytes_temp, width=160)
                with col_inst:
                    st.markdown("""
                    <div style="font-size:13px;color:#94a3b8;line-height:1.8;">
                      <strong style="color:#e2e8f0;">Step 1</strong><br>
                      Open Google Authenticator, Authy, or any TOTP app.<br><br>
                      <strong style="color:#e2e8f0;">Step 2</strong><br>
                      Tap + → Scan QR code, or enter the manual key below.<br><br>
                      <strong style="color:#e2e8f0;">Step 3</strong><br>
                      Enter the 6-digit code your app shows to confirm.
                    </div>
                    """, unsafe_allow_html=True)
                    st.code(st.session_state.totp_secret_temp, language=None)

                st.markdown('</div>', unsafe_allow_html=True)

                mfa_code = st.text_input(
                    "Enter 6-digit code from your app",
                    max_chars=6, placeholder="000000", key="mfa_confirm_acc"
                )
                col_confirm, col_cancel = st.columns([1, 1])
                with col_confirm:
                    if st.button("Confirm & Enable MFA", key="confirm_mfa_acc", use_container_width=True):
                        if mfa_code and len(mfa_code) == 6:
                            if verify_totp(st.session_state.totp_secret_temp, mfa_code):
                                enable_mfa(uid(), st.session_state.totp_secret_temp)
                                st.session_state.show_mfa_setup   = False
                                st.session_state.totp_secret_temp = None
                                st.session_state.user["mfa_enabled"] = True
                                st.success("MFA enabled — your account is now protected")
                                st.rerun()
                            else:
                                st.error("Invalid code — check your authenticator app and try again")
                        else:
                            st.warning("Enter the 6-digit code")
                with col_cancel:
                    if st.button("Cancel", key="cancel_mfa_acc", use_container_width=True):
                        st.session_state.show_mfa_setup   = False
                        st.session_state.totp_secret_temp = None
                        st.rerun()

        st.markdown('<div style="height:20px;"></div>', unsafe_allow_html=True)
        st.markdown("""
        <div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);
             border-radius:8px;padding:18px 20px;">
          <div style="font-family:'DM Mono',monospace;font-size:13px;color:#94a3b8;
               letter-spacing:.12em;margin-bottom:10px;">DATA SECURITY</div>
          <div style="font-size:12px;color:#64748b;line-height:1.8;">
            Your email and personal data are stored encrypted using AES-256-GCM
            (Fernet). Passwords are hashed with bcrypt (cost 12) and never stored
            in plaintext. TOTP secrets are encrypted before storage. No sensitive
            data is ever logged or transmitted in plain text.
          </div>
        </div>
        """, unsafe_allow_html=True)

    # ── PLAN & BILLING ────────────────────────────────────────────────────────
    with tab_plan:
        st.markdown('<div style="height:16px;"></div>', unsafe_allow_html=True)
        plan_color = "#d4a843" if plan in ("pro","institutional") else "#64748b"

        st.markdown(f"""
        <div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.08);
             border-left:3px solid {plan_color};border-radius:8px;padding:20px 24px;margin-bottom:24px;">
          <div style="font-family:'DM Mono',monospace;font-size:14px;color:#94a3b8;
               letter-spacing:.12em;margin-bottom:8px;">CURRENT PLAN</div>
          <div style="font-family:'Syne',sans-serif;font-size:30px;font-weight:800;
               color:{plan_color};">{plan.upper()}</div>
          <div style="font-size:13px;color:#94a3b8;margin-top:6px;">
            {"Unlimited holdings · Hidden Gems · Signal alerts · Email notifications"
             if plan in ('pro','institutional')
             else "10 holdings · Market screener · HIGH/MODERATE/LOW conviction signals · 5-yr backtest"}
          </div>
        </div>
        """, unsafe_allow_html=True)

        if plan == "free":
            # Comparison table
            st.markdown("""
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px;">

              <div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);
                   border-radius:10px;padding:24px;">
                <div style="font-family:'Syne',sans-serif;font-size:13px;font-weight:700;
                     color:#64748b;letter-spacing:.08em;margin-bottom:6px;">FREE</div>
                <div style="font-family:'Syne',sans-serif;font-size:36px;font-weight:800;
                     color:#e2e4f0;line-height:1;margin-bottom:4px;">$0</div>
                <div style="font-size:13px;color:#94a3b8;margin-bottom:18px;">forever</div>
                <div style="font-size:13px;color:#94a3b8;line-height:2;">
                  ✓ Full market screener (61 stocks)<br>
                  ✓ HIGH / MODERATE / LOW conviction signals<br>
                  ✓ 5-pillar factor breakdown<br>
                  ✓ Up to 10 portfolio positions<br>
                  ✓ 5-year backtest data<br>
                  ✗ Hidden Gems<br>
                  ✗ Signal alerts<br>
                  ✗ Notifications
                </div>
              </div>

              <div style="background:rgba(212,168,67,.04);border:2px solid rgba(212,168,67,.45);
                   border-radius:10px;padding:24px;position:relative;">
                <div style="position:absolute;top:-12px;left:20px;background:#d4a843;color:#000;
                     font-family:'Syne',sans-serif;font-size:13px;font-weight:700;
                     letter-spacing:.1em;padding:3px 12px;border-radius:3px;">RECOMMENDED</div>
                <div style="font-family:'Syne',sans-serif;font-size:13px;font-weight:700;
                     color:#d4a843;letter-spacing:.08em;margin-bottom:6px;">FOUNDING MEMBER</div>
                <div style="font-family:'Syne',sans-serif;font-size:36px;font-weight:800;
                     color:#d4a843;line-height:1;margin-bottom:4px;">$0</div>
                <div style="font-size:13px;color:#94a3b8;margin-bottom:18px;">
                  first 50 users · then $29/mo
                </div>
                <div style="font-size:13px;color:#94a3b8;line-height:2;">
                  ✓ Everything in Free<br>
                  ✓ Unlimited portfolio positions<br>
                  ✓ 💎 Hidden Gem alerts<br>
                  ✓ Real-time signal notifications<br>
                  ✓ Macro regime change alerts<br>
                  ✓ Email signal summaries<br>
                  ✓ Founding member badge<br>
                  ✓ Priority support
                </div>
              </div>

            </div>
            """, unsafe_allow_html=True)

            st.markdown('</div>', unsafe_allow_html=True)

            st.markdown('<div class="land-btn-primary">', unsafe_allow_html=True)
            if st.button("Join Founding Members — Claim Free Spot", key="upgrade_btn", use_container_width=True):
                ok = upgrade_plan(uid(), "pro")
                # Force plan into session state immediately
                if st.session_state.get("user"):
                    st.session_state.user["plan"] = "pro"
                # Rewrite localStorage token with updated plan so nav restores correctly
                _write_localstorage_token(uid(), "pro")
                if ok:
                    st.success("✓ Founding Member activated! Navigate to Hidden Gems via the menu.")
                    st.balloons()
                else:
                    st.warning("Could not write to DB — contact hello@qntm.app")
            st.markdown('</div>', unsafe_allow_html=True)

        elif plan in ("pro","institutional"):
            st.markdown("""
            <div style="background:rgba(0,255,135,.04);border:1px solid rgba(0,255,135,.15);
                 border-radius:8px;padding:16px 20px;font-size:13px;color:#4ade80;">
              ✓ You have full Pro access. All features are enabled.
              Contact hello@qntm.app for billing questions or to upgrade to Institutional.
            </div>
            """, unsafe_allow_html=True)

    # ── NOTIFICATION PREFS ────────────────────────────────────────────────────
    with tab_notifs:
        st.markdown('<div style="height:16px;"></div>', unsafe_allow_html=True)
        if not plan_limit(plan, "notifications"):
            st.markdown("""
            <div style="background:rgba(251,191,36,.05);border:1px solid rgba(251,191,36,.2);
                 border-radius:6px;padding:14px 18px;font-size:13px;color:#fbbf24;margin-bottom:16px;">
              Notification preferences require a Pro or Founding Member plan.
            </div>
            """, unsafe_allow_html=True)
        else:
            prefs = user.get("notifications") or {}
            e_on = st.toggle("Email signal summaries (weekly digest)",
                             value=prefs.get("email", False), key="pref_email")
            s_on = st.toggle("In-app signal change alerts",
                             value=prefs.get("signals", True), key="pref_sig")
            a_on = st.toggle("Macro regime change alerts",
                             value=prefs.get("alerts", True), key="pref_alert")

            st.markdown('<div style="height:12px;"></div>', unsafe_allow_html=True)
            if st.button("Save Notification Preferences", key="save_prefs"):
                new_prefs = {"email": e_on, "signals": s_on, "alerts": a_on}
                if update_preferences(uid(), {"notifications": new_prefs}):
                    st.session_state.user["notifications"] = new_prefs
                    st.success("Preferences saved")
                else:
                    st.error("Save failed — try again")

    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PLATFORM SHELL
# ══════════════════════════════════════════════════════════════════════════════
def page_model_portfolio():
    """
    QNTM Model Portfolio — top 20 BUY signals tracked from today's entry.
    Entry date sourced from model_portfolio_positions (seeded 2026-05-19).
    Exits when conviction score drops below 45. Reinvests into next highest conviction signal.
    """
    from data_refresh import _get_supabase
    import datetime

    page_summary(
        "🏆", "Model Portfolio",
        "50 High Conviction positions built across May 19–23, 2026 — all HIGH signals on Monday, "
        "topped up daily with new HIGH conviction stocks until reaching 50. 30% sector cap enforced. "
        "Equal-weighted at $2K per position ($100K total). Exits when conviction score drops below 45, "
        "reinvests into next highest conviction stock available.",
    )

    sb = _get_supabase()

    # ── Load positions from Supabase ──────────────────────────────────────────
    positions = []
    if sb:
        try:
            resp = sb.table("model_portfolio_positions") \
                .select("*") \
                .eq("is_active", True) \
                .order("entry_date", desc=False) \
                .execute()
            positions = resp.data or []
        except Exception as e:
            st.warning(f"Could not load positions: {e}")

    scan = st.session_state.get("scan_results") or []
    score_map = {r["ticker"]: r for r in scan}

    # ── Pull latest prices + scores from signal_log (no scan required) ────────
    if sb:
        try:
            tickers = [p["ticker"] for p in positions]
            sig_resp = sb.table("signal_log")                 .select("ticker,price,adj_composite,composite,signal,momentum,quality,volume,value,sentiment,is_hidden_gem")                 .in_("ticker", tickers)                 .order("signal_date", desc=True)                 .limit(len(tickers) * 3)                 .execute()
            # Take most recent row per ticker
            seen = set()
            for row in (sig_resp.data or []):
                tk = row["ticker"]
                if tk not in seen:
                    seen.add(tk)
                    # Merge into score_map — signal_log wins over stale session state
                    if tk not in score_map:
                        score_map[tk] = {}
                    for field in ["price","adj_composite","composite","signal","momentum","quality","volume","value","sentiment","is_hidden_gem","hidden_gem_reason"]:
                        if row.get(field) is not None:
                            score_map[tk][field] = row[field]
        except Exception:
            pass  # fall back to session state if query fails

    if not positions:
        # No positions yet — show what would be entered today
        st.markdown(
            '<div style="background:rgba(212,168,67,.06);border:1px solid rgba(212,168,67,.2);'
            'border-radius:8px;padding:20px 24px;margin-bottom:24px;font-size:13px;color:#d4a843;">'
            '⚡ Model portfolio initializes tonight at 2 AM UTC when the nightly cron runs. '
            'Run a Rescan on the Screener first to seed today\'s signals.</div>',
            unsafe_allow_html=True)

        # Preview what would be entered
        buys = sorted(
            [r for r in scan if r.get("adj_composite", r.get("composite", 0)) >= 60],
            key=lambda x: x.get("adj_composite", x.get("composite", 0)),
            reverse=True
        )[:20]

        if buys:
            st.markdown('<div style="font-family:DM Mono,monospace;font-size:12px;color:#64748b;'
                        'letter-spacing:.1em;margin-bottom:12px;">TONIGHT\'S ENTRIES (PREVIEW)</div>',
                        unsafe_allow_html=True)
            for i, r in enumerate(buys):
                bg = "rgba(255,255,255,.02)" if i % 2 == 0 else "rgba(255,255,255,.008)"
                price_str = f'${r["price"]:,.2f}' if r.get("price") else "—"
                st.markdown(
                    f'<div style="display:grid;grid-template-columns:80px 1fr 80px 60px;'
                    f'gap:4px;padding:8px 12px;background:{bg};'
                    f'border:1px solid rgba(255,255,255,.04);border-radius:4px;margin-bottom:2px;">'
                    f'<div style="font-family:Syne,sans-serif;font-size:13px;font-weight:800;color:#e2e8f0;">{r["ticker"]}</div>'
                    f'<div style="font-size:12px;color:#64748b;">Entry today</div>'
                    f'<div style="font-family:DM Mono,monospace;font-size:12px;color:#94a3b8;">{price_str}</div>'
                    f'<div style="font-family:DM Mono,monospace;font-size:13px;font-weight:700;color:#00ff87;">{r.get("adj_composite", 0):.0f}</div>'
                    f'</div>', unsafe_allow_html=True)
        return

    # ── Fetch live prices via yfinance for all positions ─────────────────────
    live_prices = {}
    tickers_to_fetch = [p["ticker"] for p in positions]
    if tickers_to_fetch:
        try:
            import yfinance as yf
            with st.spinner("Fetching live prices..."):
                hist = yf.download(
                    tickers_to_fetch, period="1d",
                    auto_adjust=True, progress=False, threads=True
                )
                if not hist.empty:
                    close = hist["Close"]
                    if hasattr(close, "columns"):
                        # MultiIndex — multiple tickers
                        for tk in tickers_to_fetch:
                            if tk in close.columns:
                                val = close[tk].dropna()
                                if not val.empty:
                                    live_prices[tk] = float(val.iloc[-1])
                    else:
                        # Single ticker
                        val = close.dropna()
                        if not val.empty and len(tickers_to_fetch) == 1:
                            live_prices[tickers_to_fetch[0]] = float(val.iloc[-1])
        except Exception:
            pass  # fall back to signal_log prices

    # ── Calculate portfolio metrics ───────────────────────────────────────────
    today = datetime.date.today().isoformat()
    holdings = []
    total_invested = 0
    total_current  = 0

    for pos in positions:
        tk           = pos["ticker"]
        entry_price  = pos.get("entry_price")
        pos_size     = pos.get("position_size", 2000)
        current_data = score_map.get(tk, {})
        # Prefer live yfinance price, fall back to signal_log
        current_price = live_prices.get(tk) or current_data.get("price")

        if entry_price and current_price and entry_price > 0:
            shares      = pos_size / entry_price
            current_val = shares * current_price
            pnl         = current_val - pos_size
            pnl_pct     = (current_val / pos_size - 1) * 100
        else:
            shares      = None
            current_val = pos_size
            pnl         = 0
            pnl_pct     = 0

        total_invested += pos_size
        total_current  += current_val

        holdings.append({
            "ticker":        tk,
            "entry_date":    pos.get("entry_date", today),
            "entry_price":   entry_price,
            "entry_score":   pos.get("entry_score", 50),
            "current_price": current_price,
            "current_score": current_data.get("adj_composite", current_data.get("composite", pos.get("entry_score", 50))),
            "momentum":      current_data.get("momentum", 50),
            "quality":       current_data.get("quality",  50),
            "volume":        current_data.get("volume",   50),
            "value":         current_data.get("value",    50),
            "sentiment":     current_data.get("sentiment",50),
            "pos_size":      pos_size,
            "current_val":   current_val,
            "pnl":           pnl,
            "pnl_pct":       pnl_pct,
            "is_gem":        current_data.get("is_hidden_gem", False),
        })

    port_return = (total_current / total_invested - 1) * 100 if total_invested > 0 else 0
    port_pnl    = total_current - total_invested
    sign        = "+" if port_return >= 0 else ""
    ret_color   = "#00ff87" if port_return >= 0 else "#ef4444"

    # ── SPY benchmark comparison ──────────────────────────────────────────────
    # Per-position SPY comparison (each position vs SPY over its own holding window)
    spy_return = 0.0
    spy_pnl    = 0.0
    try:
        import yfinance as yf
        from datetime import date as _dt
        spy_hist = yf.download("SPY", start="2026-05-19", progress=False, auto_adjust=True)
        if not spy_hist.empty:
            spy_close = spy_hist["Close"]
            if hasattr(spy_close, "columns"): spy_close = spy_close.iloc[:,0]
            spy_close = spy_close.squeeze().dropna()
            spy_now = float(spy_close.iloc[-1])
            spy_rets = []
            for pos in positions:
                try:
                    ed = _dt.fromisoformat(str(pos.get("entry_date",""))[:10])
                    w  = spy_close[spy_close.index.date >= ed]
                    if not w.empty:
                        spy_rets.append((spy_now - float(w.iloc[0])) / float(w.iloc[0]) * 100)
                except Exception:
                    pass
            if spy_rets:
                spy_return = sum(spy_rets) / len(spy_rets)
                spy_pnl    = total_invested * (spy_return / 100)
    except Exception:
        pass

    vs_spy_pct = port_return - spy_return
    vs_spy_pnl = port_pnl - spy_pnl
    vs_color   = "#00ff87" if vs_spy_pct >= 0 else "#ef4444"
    vs_sign    = "+" if vs_spy_pct >= 0 else ""



    # ── Methodology banner ────────────────────────────────────────────────────
    st.markdown(
        '<div style="background:rgba(212,168,67,.04);border:1px solid rgba(212,168,67,.15);'
        'border-radius:8px;padding:16px 20px;margin-bottom:20px;">'
        '<div style="font-family:DM Mono,monospace;font-size:11px;color:#d4a843;'
        'letter-spacing:.1em;margin-bottom:8px;">⚡ INVESTMENT METHODOLOGY</div>'
        '<div style="font-size:13px;color:#94a3b8;line-height:1.7;">'
        'Built across <strong style="color:#cbd5e1;">May 19–23, 2026</strong> — '
        '~10 highest conviction signals entered each trading day until reaching 50 positions. '
        'Entry threshold: blended conviction score '
        '<strong style="color:#00ff87;">≥ 60</strong> across 5 factors + macro overlay. '
        'Equal-weighted at <strong style="color:#cbd5e1;">$2,000 per position</strong> ($100K total).'
        '<br><br>'
        '<strong style="color:#cbd5e1;">Exit discipline:</strong> Positions are held until conviction '
        'drops below <strong style="color:#ef4444;">45</strong>. Capital redeploys into the next '
        'highest conviction signal not already held. No discretionary overrides.'
        '</div></div>',
        unsafe_allow_html=True
    )

    # ── Summary strip — CSS grid wraps to 2-3 cols on mobile ────────────────
    ss = "background:#0d1117;border:1px solid rgba(255,255,255,.07);border-radius:6px;padding:14px 16px;text-align:center;"
    ls = "font-family:DM Mono,monospace;font-size:10px;color:#64748b;letter-spacing:.08em;margin-bottom:6px;"

    pnl_sign    = "+" if port_pnl >= 0 else ""
    vs_pnl_sign = "+" if vs_spy_pnl >= 0 else ""

    st.markdown(f"""
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin-bottom:20px;">
      <div style="{ss}"><div style="{ls}">PORTFOLIO VALUE</div>
        <div style="font-size:18px;font-weight:700;color:#d4a843;">${total_current:,.0f}</div></div>
      <div style="{ss}"><div style="{ls}">$ CHANGE</div>
        <div style="font-size:18px;font-weight:700;color:{ret_color};">{pnl_sign}${port_pnl:,.0f}</div></div>
      <div style="{ss}"><div style="{ls}">% RETURN</div>
        <div style="font-size:18px;font-weight:700;color:{ret_color};">{sign}{port_return:.1f}%</div></div>
      <div style="{ss}"><div style="{ls}">$ vs SPY</div>
        <div style="font-size:18px;font-weight:700;color:{vs_color};">{vs_pnl_sign}${vs_spy_pnl:,.0f}</div></div>
      <div style="{ss}"><div style="{ls}">% vs SPY</div>
        <div style="font-size:18px;font-weight:700;color:{vs_color};">{vs_sign}{vs_spy_pct:.1f}%</div></div>
    </div>
    """, unsafe_allow_html=True)

    # ── Holdings table ────────────────────────────────────────────────────────
    st.markdown('<div style="font-family:DM Mono,monospace;font-size:12px;color:#d4a843;'
                'letter-spacing:.1em;margin-bottom:8px;">▲ ACTIVE POSITIONS</div>',
                unsafe_allow_html=True)

    # ── Detect current hidden gems ────────────────────────────────────────────
    port_gem_tickers = set()
    # First try signal_log.is_hidden_gem (no scan required)
    if sb:
        try:
            tickers_in_port = [h["ticker"] for h in holdings]
            gem_resp = sb.table("signal_log")                 .select("ticker,is_hidden_gem")                 .in_("ticker", tickers_in_port)                 .eq("is_hidden_gem", True)                 .order("signal_date", desc=True)                 .limit(len(tickers_in_port) * 2)                 .execute()
            port_gem_tickers = {row["ticker"] for row in (gem_resp.data or [])}
        except Exception:
            pass
    # Fallback: detect from session scan if available
    if not port_gem_tickers and scan:
        try:
            port_gems = detect_hidden_gems(scan, macro_data=st.session_state.get("macro_data"))
            port_gem_tickers = {g["ticker"] for g in port_gems}
        except Exception:
            pass

    for i, h in enumerate(sorted(holdings, key=lambda x: x["pnl_pct"], reverse=True)):
        bg       = "rgba(255,255,255,.025)" if i % 2 == 0 else "rgba(255,255,255,.01)"
        rc       = "#00ff87" if h["pnl_pct"] >= 0 else "#ef4444"
        sg       = "+" if h["pnl_pct"] >= 0 else ""
        entry_str = f'${h["entry_price"]:,.2f}'  if h["entry_price"]   else "—"
        cur_str   = f'${h["current_price"]:,.2f}' if h["current_price"] else "—"
        pnl_str   = f'{sg}${abs(h["pnl"]):,.0f}' if h["entry_price"] and h["current_price"] else "—"
        ret_str   = f'{sg}{h["pnl_pct"]:.2f}%'   if h["entry_price"] and h["current_price"] else "—"
        shares    = (h["pos_size"] / h["entry_price"]) if h.get("entry_price") and h["entry_price"] > 0 else None
        shares_str = f'{shares:,.1f} sh' if shares else "—"
        score     = h["current_score"]
        score_col = "#00ff87" if score >= 70 else ("#fbbf24" if score >= 55 else "#ef4444")
        gem_badge = "💎 " if h["ticker"] in port_gem_tickers else ""

        # Company name + sector from score_map
        sd       = score_map.get(h["ticker"], {})
        ci       = get_company_info(h["ticker"])
        co_name  = (ci.get("name","") if ci else "")[:28] or h["ticker"]
        from model_engine import SECTORS as _MP_SECTORS
        sector   = sd.get("sector","") or _MP_SECTORS.get(h["ticker"],"") or "—"
        sec_short = sector[:18] + "…" if len(sector) > 18 else sector

        # Left border accent by return
        border_c = "#00ff87" if h["pnl_pct"] >= 0 else "#ef4444"

        st.markdown(
            # Desktop row (hidden on mobile via CSS class)
            f'<div class="mp-row" style="display:grid;grid-template-columns:120px 1fr 110px 80px 70px 60px;'
            f'gap:8px;padding:8px 16px;background:{bg};margin-bottom:1px;'
            f'border-left:3px solid {border_c};align-items:center;">'
            # Ticker + name
            f'<div>'
            f'<div style="font-family:Syne,sans-serif;font-size:13px;font-weight:800;color:#e2e8f0;line-height:1;">{gem_badge}{h["ticker"]}</div>'
            f'<div style="font-size:10px;color:#64748b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:1px;">{co_name}</div>'
            f'</div>'
            # Sector + entry date
            f'<div style="font-size:11px;color:#475569;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{sec_short} · {h["entry_date"]}</div>'
            # Entry → current
            f'<div style="font-family:DM Mono,monospace;font-size:11px;color:#94a3b8;text-align:right;white-space:nowrap;">{entry_str}→{cur_str}</div>'
            # Shares
            f'<div style="font-family:DM Mono,monospace;font-size:11px;color:#64748b;text-align:right;">{shares_str}</div>'
            # P&L
            f'<div style="font-family:DM Mono,monospace;font-size:12px;font-weight:600;color:{rc};text-align:right;">{pnl_str}</div>'
            # Return + score
            f'<div style="text-align:right;">'
            f'<div style="font-family:DM Mono,monospace;font-size:13px;font-weight:700;color:{rc};">{ret_str}</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:11px;color:{score_col};">s:{score:.0f}</div>'
            f'</div>'
            f'</div>'
            # Mobile card (shown on mobile via CSS class)
            f'<div class="mp-card" style="display:none;padding:12px 16px;background:{bg};margin-bottom:1px;'
            f'border-left:3px solid {border_c};">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;">'
            f'<div>'
            f'<div style="font-family:Syne,sans-serif;font-size:15px;font-weight:800;color:#e2e8f0;">{gem_badge}{h["ticker"]}</div>'
            f'<div style="font-size:11px;color:#64748b;">{co_name}</div>'
            f'<div style="font-size:10px;color:#475569;margin-top:2px;">{sec_short} · {h["entry_date"]}</div>'
            f'</div>'
            f'<div style="text-align:right;">'
            f'<div style="font-family:DM Mono,monospace;font-size:16px;font-weight:700;color:{rc};">{ret_str}</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:12px;color:{rc};">{pnl_str}</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:11px;color:{score_col};">score: {score:.0f}</div>'
            f'</div>'
            f'</div>'
            f'<div style="display:flex;gap:12px;flex-wrap:wrap;">'
            f'<div><div style="font-size:10px;color:#475569;letter-spacing:.06em;">ENTRY</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:12px;color:#94a3b8;">{entry_str}</div></div>'
            f'<div><div style="font-size:10px;color:#475569;letter-spacing:.06em;">CURRENT</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:12px;color:#94a3b8;">{cur_str}</div></div>'
            f'<div><div style="font-size:10px;color:#475569;letter-spacing:.06em;">SHARES</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:12px;color:#64748b;">{shares_str}</div></div>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True)

    st.markdown(
        '<div style="font-size:10px;color:#475569;padding:6px 8px;background:#050a0f;'
        'border:1px solid rgba(255,255,255,.07);border-radius:0 0 6px 6px;margin-bottom:8px;">'
        '$10K/position · Equal weighted · Auto-exit score < 45</div>',
        unsafe_allow_html=True)

    # ── Export to Excel ───────────────────────────────────────────────────────
    try:
        export_rows = []
        for h in sorted(holdings, key=lambda x: x["pnl_pct"], reverse=True):
            shares = (h["pos_size"] / h["entry_price"]) if h.get("entry_price") and h["entry_price"] > 0 else ""
            export_rows.append({
                "Ticker":        h["ticker"],
                "Entry Date":    h["entry_date"],
                "Entry Price":   h.get("entry_price", ""),
                "Current Price": h.get("current_price", ""),
                "Shares":        round(shares, 4) if shares else "",
                "Position ($)":  h["pos_size"],
                "Current Value": round(h["current_val"], 2),
                "P&L ($)":       round(h["pnl"], 2),
                "Return (%)":    round(h["pnl_pct"], 2),
                "Score":         round(h["current_score"], 1),
                "Momentum":      round(h["momentum"], 1),
                "Quality":       round(h["quality"], 1),
                "Volume":        round(h["volume"], 1),
                "Value":         round(h["value"], 1),
                "Sentiment":     round(h["sentiment"], 1),
                "Gem":           "💎" if h.get("is_gem") else "",
            })
        headers = ["Ticker","Entry Date","Entry Price","Current Price","Shares","Position ($)","Current Value","P&L ($)","Return (%)","Score","Momentum","Quality","Volume","Value","Sentiment","Gem"]
        xl = _make_excel(export_rows, headers, "Model Portfolio")
        st.download_button(
            label="⬇ Export to Excel",
            data=xl,
            file_name="qntm_model_portfolio.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="model_port_export"
        )
    except Exception:
        pass



    # ── Exit history ──────────────────────────────────────────────────────────
    if sb:
        try:
            exits = sb.table("model_portfolio_positions") \
                .select("ticker,entry_date,entry_price,exit_date,exit_price,exit_score,exit_reason") \
                .eq("is_active", False) \
                .order("exit_date", desc=True) \
                .limit(20) \
                .execute()
            # Filter out reseeded entries — only show genuine exits
            real_exits = [e for e in (exits.data or [])
                          if e.get("exit_reason","") not in ("reseeded","")]
            if real_exits:
                st.markdown('<div style="height:24px;"></div>', unsafe_allow_html=True)
                st.markdown('<div style="font-family:DM Mono,monospace;font-size:12px;color:#64748b;'
                            'letter-spacing:.1em;margin-bottom:12px;">RECENT EXITS</div>',
                            unsafe_allow_html=True)
                for ex in real_exits:
                    ep = ex.get("entry_price")
                    xp = ex.get("exit_price")
                    if ep and xp and ep > 0:
                        ret = (xp / ep - 1) * 100
                        rc  = "#00ff87" if ret >= 0 else "#ef4444"
                        sg  = "+" if ret >= 0 else ""
                        ret_str = f'{sg}{ret:.1f}%'
                    else:
                        rc = "#64748b"
                        ret_str = "—"
                    st.markdown(
                        f'<div style="display:flex;gap:16px;padding:6px 12px;'
                        f'border-bottom:1px solid rgba(255,255,255,.04);font-size:12px;">'
                        f'<span style="font-family:Syne,sans-serif;font-weight:800;color:#94a3b8;width:60px;">{ex["ticker"]}</span>'
                        f'<span style="color:#475569;">{ex.get("exit_date","")} · {ex.get("exit_reason","")}</span>'
                        f'<span style="font-family:DM Mono,monospace;color:{rc};margin-left:auto;">{ret_str}</span>'
                        f'</div>', unsafe_allow_html=True)
        except Exception:
            pass

    st.markdown(
        '<div style="font-size:12px;color:#475569;padding:16px 0;margin-top:16px;'
        'border-top:1px solid rgba(255,255,255,.05);">'
        '⚠ Model portfolio is hypothetical. $10K equal weight per position. '
        'Does not account for slippage, taxes, or transaction costs. For informational purposes only.</div>',
        unsafe_allow_html=True)


def page_methodology():
    """How QNTM Works — methodology, factor logic, disclaimers."""
    page_summary("📖", "How QNTM Works",
        "Transparent methodology — what the model does, how it scores stocks, and what it doesn't do.")
    st.markdown('<div style="padding:0 32px;">', unsafe_allow_html=True)

    sections = [
        ("The Universe", "#00ff87",
         "QNTM covers 834 stocks drawn from the S&P 500 and Russell 1000, cleaned of delisted and "
         "illiquid tickers. This represents the investable large/mid-cap US equity universe that "
         "most retail investors already hold or consider."),

        ("The Factor Model", "#00ff87",
         "Each stock receives a composite score (0–100) built from five weighted pillars:\n\n"
         "• Momentum (30%) — price trend, relative strength, rate of change\n"
         "• Quality (25%) — earnings consistency, return on equity, balance sheet strength\n"
         "• Volume (20%) — institutional flow signals, volume trend confirmation\n"
         "• Value (15%) — price-to-earnings, price-to-book relative to sector\n"
         "• Sentiment (10%) — analyst revision trend, news flow\n\n"
         "Scores are cross-sectional — a score of 75 means stronger than 75% of the universe, not an absolute value."),

        ("Conviction Thresholds", "#00ff87",
         "• High Conviction: composite score ≥ 60 — signal is in the top 40% of the universe\n"
         "• Moderate Conviction: score 45–59 — neutral, monitor for movement\n"
         "• Low Conviction: score < 45 — signal weakening, elevated risk profile\n\n"
         "These are quantitative signal categories, not investment advice."),

        ("Macro Overlay", "#d4a843",
         "The model applies a macro regime overlay that adjusts composite scores based on current "
         "market conditions — VIX level, commodity prices, news sentiment across 70+ live headlines.\n\n"
         "Weighting: 75% quantitative model, 25% macro regime adjustment (max). "
         "In Risk-Off regimes, macro dampening reduces scores to reflect elevated market risk."),

        ("Backtest Methodology", "#d4a843",
         "Walk-forward backtest across Q2 2020 – Q1 2025 (20 quarters). "
         "124 tickers per quarter, 10bps transaction costs assumed. No look-ahead bias — each quarter "
         "is scored using only data available at that point in time.\n\n"
         "Results: +307% adjusted cumulative vs SPY +131% · Sharpe 1.72 · Max drawdown 6.5%\n"
         "Past model performance does not guarantee future results."),

        ("What QNTM Does NOT Do", "#ef4444",
         "• QNTM does not provide personalized investment advice\n"
         "• QNTM does not account for your individual tax situation, risk tolerance, or financial goals\n"
         "• QNTM does not predict short-term price movements\n"
         "• QNTM is not a registered investment adviser under the Investment Advisers Act of 1940\n"
         "• Conviction scores are quantitative outputs — not buy or sell recommendations\n\n"
         "Always consult a qualified financial adviser before making investment decisions."),
    ]

    for title, color, body in sections:
        st.markdown(
            f'<div style="border-left:3px solid {color};padding:16px 20px;margin-bottom:16px;"'
            f'background:rgba(255,255,255,.02);border-radius:0 8px 8px 0;">'
            f'<div style="font-family:Syne,sans-serif;font-size:14px;font-weight:700;color:{color};"'
            f'letter-spacing:.06em;margin-bottom:8px;">{title}</div>'
            f'<div style="font-size:13px;color:#94a3b8;line-height:1.8;white-space:pre-line;">{body}</div>'
            f'</div>',
            unsafe_allow_html=True
        )

    st.markdown('</div>', unsafe_allow_html=True)


def page_platform():
    # ── Force MFA setup on first login ─────────────────────────────────────────
    if st.session_state.get("force_mfa_setup"):
        user = st.session_state.user or {}
        mfa  = get_user_mfa(uid())
        if not mfa.get("mfa_enabled"):
            # Show as a clean centered page — no fixed overlays that cover buttons
            _, mc, _ = st.columns([1, 2, 1])
            with mc:
                st.markdown(
                    '<div style="background:#0d1117;border:1px solid rgba(212,168,67,.4);border-radius:12px;padding:28px 24px;text-align:center;">'
                    '<div style="font-size:28px;margin-bottom:12px;">🔒</div>'
                    '<div style="font-family:Syne,sans-serif;font-size:18px;font-weight:700;color:#d4a843;margin-bottom:12px;">Secure Your Account</div>'
                    '<div style="font-size:13px;color:#94a3b8;line-height:1.7;">'
                    'QNTM holds your portfolio data. We <strong style="color:#e2e8f0;">strongly recommend</strong> enabling 2FA before continuing. Takes 60 seconds.'
                    '</div></div>',
                    unsafe_allow_html=True
                )
                st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
                b1, b2 = st.columns(2)
                with b1:
                    if st.button("⚡ Enable 2FA", key="force_mfa_yes", use_container_width=True):
                        st.session_state.force_mfa_setup = False
                        nav("account")
                        st.session_state.show_mfa_setup = True
                with b2:
                    if st.button("Skip", key="force_mfa_skip", use_container_width=True):
                        st.session_state.force_mfa_setup = False
                        st.rerun()
            return
        else:
            st.session_state.force_mfa_setup = False

            st.session_state.force_mfa_setup = False

    if "last_refresh" not in st.session_state:
        st.session_state.last_refresh = 0
    import time as _time
    now = int(_time.time())
    # Never clear scan_results while a live refresh is in progress
    if not st.session_state.get("live_refresh_running"):
        if now - st.session_state.last_refresh >= 60:
            st.session_state.last_refresh = now
            # Don't wipe scan if on gems — button clicks would trigger 4-min rescan
            if st.session_state.get("nav") != "gems":
                st.session_state.scan_results = None
    platform_nav()
    show_onboarding()


    nav_map = {
        "screener":        page_screener,
        "watchlist":       page_watchlist,
        "gems":            page_gems,
        "backtest":       page_backtest,
        "portfolio":      page_portfolio,
        "simulator":      page_simulator,
        "model_portfolio": page_model_portfolio,
        "methodology":     page_methodology,
        "alerts":         page_alerts,
        "account":        page_account,
    }
    nav_map.get(st.session_state.nav, page_screener)()

    # ── Persistent disclaimer footer ────────────────────────────────────
    st.markdown(
        '<div style="margin:32px 32px 8px;padding:12px 16px;"'
        'background:rgba(255,255,255,.02);border-top:1px solid rgba(255,255,255,.05);"'
        'border-radius:6px;font-size:11px;color:#334155;line-height:1.6;text-align:center;">'
        'QNTM provides quantitative signal analysis for informational and educational purposes only. '
        'Conviction scores are model outputs — not personalized investment advice. '
        'Past model performance does not guarantee future results. '
        'Not a registered investment adviser.'
        '</div>',
        unsafe_allow_html=True
    )

    # Platform footer
    st.markdown("""
    <div style="padding:24px 32px;border-top:1px solid rgba(255,255,255,.05);margin-top:40px;">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
        <div style="font-size:13px;color:#475569;">
          QNTM · Quantitative research platform · Not investment advice
        </div>
        <div style="font-size:13px;color:#475569;">
          <a href="#" style="color:#94a3b8;">Privacy</a> ·
          <a href="#" style="color:#94a3b8;">Terms</a> ·
          <a href="#" style="color:#94a3b8;">Disclaimer</a>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)
    cookie_banner()


# ══════════════════════════════════════════════════════════════════════════════
# ROUTER
# ══════════════════════════════════════════════════════════════════════════════
def main():
    # ── Legal page via footer links ───────────────────────────────────────────
    if st.query_params.get("legal") in ("privacy","terms","cookies","disclaimer"):
        st.session_state.legal_doc = st.query_params.get("legal")
        st.session_state.page = "legal"

    # ── Nav link routing ──────────────────────────────────────────────────────
    if st.query_params.get("nav") == "signin":
        st.session_state.auth_tab = "signin"
        st.session_state.page = "auth"
        st.query_params.pop("nav", None)
    if st.query_params.get("nav") == "register":
        st.session_state.auth_tab = "register"
        st.session_state.page = "auth"
        st.query_params.pop("nav", None)



    # ── Watchlist add/remove via URL action (used by gems page links) ────────
    _wl_action = st.query_params.get("wl_action", "")
    _wl_ticker = st.query_params.get("wl_ticker", "")
    if _wl_action and _wl_ticker and st.session_state.get("logged_in"):
        if _wl_action == "add":
            add_to_watchlist(uid(), _wl_ticker)
        elif _wl_action == "remove":
            remove_from_watchlist(uid(), _wl_ticker)
        st.query_params.pop("wl_action", None)
        st.query_params.pop("wl_ticker", None)
    _VALID_TABS = {"screener","watchlist","gems","backtest","portfolio","simulator",
                   "model_portfolio","alerts","account","methodology"}
    _qnav = st.query_params.get("qnav","")
    if _qnav in _VALID_TABS:
        st.session_state.nav  = _qnav
        st.session_state.page = "platform"
        st.query_params.pop("qnav", None)
    if st.query_params.get("qnav") == "signout":
        for k in ["logged_in","user","mfa_verified","scan_results",
                  "macro_data","mfa_recovery_mode","live_refresh_running"]:
            st.session_state[k] = False if k == "logged_in" else None
        st.session_state.signed_out = True
        st.query_params.clear()
        _clear_localstorage_token()
        go("landing")
    if st.query_params.get("ck") == "1":
        st.session_state.cookies_accepted = True

    # Handle nav button side effects — re-route if needed
    if st.session_state.page == "landing" and st.session_state.logged_in:
        st.session_state.page = "platform"

    route = st.session_state.page
    if   route == "landing":
        page_landing()
        if not st.session_state.get("cookies_accepted"):
            _cookie_banner()
    elif route == "auth":     page_auth()
    elif route == "mfa":      page_mfa()
    elif route == "model":    go("landing")  # page removed
    elif route == "platform": page_platform()
    elif route == "legal":    page_legal(st.session_state.get("legal_doc","privacy"))
    else:                     page_landing()

main()
