"""
QNTM — Conviction Factor Model Platform
Futuristic dark design · Financial green · Full platform
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, date
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

st.set_page_config(
    page_title="QNTM — Conviction Factor Model",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

from db import (register_user, login_user, get_holdings, upsert_holding,
                delete_holding, get_notifications, create_notification,
                mark_notifications_read, generate_totp_secret, verify_totp,
                enable_mfa, disable_mfa, get_user_mfa, update_preferences,
                upgrade_plan, plan_limit, PLAN_LIMITS,
                check_and_notify_signal_changes, save_signal_snapshot,
                get_signal_snapshot, get_unread_count)
from model_engine import (run_full_scan, detect_hidden_gems, BACKTEST_DATA,
                           ENTRY_THRESHOLD, EXIT_THRESHOLD, SECTORS,
                           fetch_macro_overlay, apply_macro_overlay)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Mono:wght@400;500&family=Outfit:wght@300;400;500;600&display=swap');

*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}

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
}
.main .block-container,
[data-testid="stMainBlockContainer"] {
  padding: 0 !important;
  max-width: 100% !important;
  background: #0a0b14 !important;
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

/* Animations */
@keyframes fadeUp{from{opacity:0;transform:translateY(24px)}to{opacity:1;transform:translateY(0)}}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.3}}
@keyframes glow{0%,100%{box-shadow:0 0 8px rgba(0,255,135,.25)}50%{box-shadow:0 0 28px rgba(0,255,135,.55)}}
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
  background: linear-gradient(135deg,#0d1f18 0%,#0a1a12 50%,#0d1f18 100%) !important;
  color: #00ff87 !important;
  border: 1px solid rgba(0,255,135,.35) !important;
  border-radius: 6px !important;
  font-family: 'Syne', sans-serif !important;
  font-weight: 700 !important;
  font-size: 11px !important;
  letter-spacing: .14em !important;
  padding: 10px 26px !important;
  text-transform: uppercase !important;
  cursor: pointer !important;
  position: relative !important;
  overflow: hidden !important;
  transition: border-color .2s, box-shadow .2s, transform .15s !important;
  box-shadow: 0 0 0 0 rgba(0,255,135,0), inset 0 1px 0 rgba(0,255,135,.12) !important;
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
  border-color: rgba(0,255,135,.75) !important;
  box-shadow: 0 0 20px rgba(0,255,135,.18), 0 4px 16px rgba(0,0,0,.4),
              inset 0 1px 0 rgba(0,255,135,.2) !important;
  transform: translateY(-2px) !important;
  background: linear-gradient(135deg,#0f2a1e 0%,#0c2018 50%,#0f2a1e 100%) !important;
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
  color:#475569;font-family:'Syne',sans-serif;font-size:12px;
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
.qntm-tip .tip-box {
    visibility: hidden;
    opacity: 0;
    position: fixed;
    background: #0d1117;
    border: 1px solid rgba(212,168,67,.3);
    border-radius: 8px;
    padding: 12px 16px;
    width: 280px;
    max-width: 85vw;
    z-index: 99999;
    transition: opacity .15s;
    pointer-events: none;
    box-shadow: 0 12px 40px rgba(0,0,0,.8);
    top: 0; left: 0;
}
.qntm-tip .tip-box .tip-title {
    font-family: 'Syne', sans-serif;
    font-size: 12px;
    font-weight: 700;
    color: #d4a843;
    margin-bottom: 6px;
}
.qntm-tip .tip-box .tip-body {
    font-size: 12px;
    color: #94a3b8;
    line-height: 1.6;
}
.qntm-tip .tip-box .tip-weight {
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    color: #475569;
    margin-top: 6px;
}
.qntm-tip:hover .tip-box {
    visibility: visible;
    opacity: 1;
}

/* Metrics */
[data-testid="metric-container"]{
  background:rgba(255,255,255,.03)!important;
  border:1px solid rgba(255,255,255,.07)!important;
  border-radius:4px!important;padding:1rem!important;
}
[data-testid="stMetricValue"]{color:#00ff87!important;font-family:'DM Mono',monospace!important;}
[data-testid="stMetricLabel"]{color:#475569!important;font-size:11px!important;}
[data-testid="stMetricDelta"]{font-family:'DM Mono',monospace!important;}

/* Dataframe */
[data-testid="stDataFrame"]{border:1px solid rgba(255,255,255,.07)!important;border-radius:4px!important;}
.stDataFrame th{background:#050a0f!important;color:#475569!important;font-size:10px!important;letter-spacing:.1em!important;}
.stDataFrame td{color:#94a3b8!important;font-size:12px!important;}

/* Checkboxes & toggles */
.stCheckbox label{color:#94a3b8!important;font-size:13px!important;}
.stToggle label{color:#94a3b8!important;}

/* Expander */
.streamlit-expanderHeader{
  background:rgba(255,255,255,.03)!important;
  border:1px solid rgba(255,255,255,.07)!important;
  border-radius:4px!important;color:#94a3b8!important;
}

/* Alert / info boxes */
.stAlert{background:rgba(0,255,135,.06)!important;border:1px solid rgba(0,255,135,.2)!important;border-radius:4px!important;color:#94a3b8!important;}

/* Forms */
.stForm{border:1px solid rgba(255,255,255,.07)!important;border-radius:6px!important;padding:1.5rem!important;background:rgba(255,255,255,.02)!important;}

/* Divider */
hr{border-color:rgba(255,255,255,.07)!important;}

/* Number input arrows */
.stNumberInput [data-baseweb="input"]{background:rgba(255,255,255,.04)!important;}

/* ── MOBILE RESPONSIVE ── */
@media (max-width: 768px) {
    /* Full-width layout on mobile */
    .main .block-container,[data-testid="stMainBlockContainer"]{
        padding:0!important;max-width:100%!important;
    }
    /* Stack columns vertically */
    [data-testid="stHorizontalBlock"]{
        flex-direction:column!important;
        gap:8px!important;
    }
    [data-testid="stHorizontalBlock"] > div {
        min-width:100%!important;width:100%!important;
        flex:none!important;
    }
    /* Larger touch targets */
    .stButton>button {
        padding:14px 20px!important;
        font-size:14px!important;
        min-height:48px!important;
    }
    /* Readable text */
    .stTextInput input,[data-baseweb="input"] input {
        font-size:16px!important;  /* prevents iOS zoom */
        padding:14px!important;
    }
    /* Nav tabs stack */
    .platform-nav-tabs { flex-wrap:wrap!important; gap:4px!important; }
    /* Landing hero */
    h1 { font-size:36px!important; }
    /* Cards stack full-width */
    div[style*="grid-template-columns"] {
        grid-template-columns:1fr!important;
    }
}
@media (max-width: 480px) {
    h1 { font-size:28px!important; }
    [data-testid="stHorizontalBlock"] { gap:6px!important; }
}
/* Viewport meta (Streamlit adds this but ensure scale=1) */
</style>
<script>
// Ensure proper mobile viewport
if (!document.querySelector('meta[name="viewport"]')) {
    var m=document.createElement('meta');
    m.name='viewport';
    m.content='width=device-width,initial-scale=1,maximum-scale=1';
    document.head.appendChild(m);
}
</script>
<style>
/* dummy — following script tag */
</style>
<script>
document.addEventListener("mouseover",function(e){
  var tip=e.target.closest(".qntm-tip");
  if(!tip)return;
  var box=tip.querySelector(".tip-box");
  if(!box)return;
  var rect=tip.getBoundingClientRect();
  var bw=280,m=10;
  var top=rect.top-200-m;
  var left=rect.left+rect.width/2-bw/2;
  if(top<8)top=rect.bottom+m;
  if(left<8)left=8;
  if(left+bw>window.innerWidth-8)left=window.innerWidth-bw-8;
  box.style.top=top+"px";
  box.style.left=left+"px";
  box.style.bottom="auto";
  box.style.transform="none";
});
</script>
""", unsafe_allow_html=True)

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
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── PERSISTENT LOGIN (remember me) ───────────────────────────────────────────
# Streamlit doesn't have real cookies, but we can use query params as a
# signed token to auto-restore sessions within the same browser.
# For production, use st.experimental_get_query_params with a signed JWT.
if not st.session_state.logged_in:
    params = st.query_params
    if "uid" in params and "plan" in params:
        # Restore session from URL param token (simple version)
        try:
            from db import get_user_by_id
            saved_uid = params["uid"]
            saved_plan = params["plan"]
            user = get_user_by_id(saved_uid)
            if user and user.get("plan") == saved_plan:
                st.session_state.logged_in    = True
                st.session_state.user         = user
                st.session_state.mfa_verified = True
                st.session_state.page         = "platform"
        except Exception:
            pass

# ── HELPERS ───────────────────────────────────────────────────────────────────
def uid():
    return (st.session_state.user or {}).get("id", "demo")

def is_pro():
    return (st.session_state.user or {}).get("plan", "free") in ("pro", "institutional")

def go(page):
    st.session_state.page = page
    st.rerun()

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

def tip_html(label: str, tip_dict: dict) -> str:
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
    return f'<span style="color:{c};background:{bg};border:1px solid {c}44;padding:2px 10px;border-radius:3px;font-size:11px;font-weight:600;letter-spacing:.08em;{font_style}">{action}</span>'

def score_bar_html(val, width=80):
    col = "#00ff87" if val>=65 else "#fbbf24" if val>=50 else "#ef4444"
    return f'<div style="width:{width}px;height:4px;background:rgba(255,255,255,.06);border-radius:2px;overflow:hidden;"><div style="width:{val}%;height:100%;background:{col};border-radius:2px;"></div></div>'

def macro_regime_banner_html(macro: dict) -> str:
    """Renders the macro regime banner with live stats from macro_data."""
    regime = macro.get("regime","NEUTRAL")
    events = macro.get("active_events",[])
    source = macro.get("source","estimated")

    cfg = {
        "RISK-ON":          ("#1D9E75","rgba(29,158,117,.08)","rgba(29,158,117,.25)","●","Macro overlay amplifying high-conviction signals"),
        "MILDLY BULLISH":   ("#4ade80","rgba(74,222,128,.06)","rgba(74,222,128,.2)","◕","Mildly bullish environment — quant signals favoured"),
        "NEUTRAL":          ("#d4a843","rgba(212,168,67,.07)","rgba(212,168,67,.2)","◐","Macro overlay at baseline — quant signals unmodified"),
        "RISK-OFF":         ("#ef4444","rgba(239,68,68,.07)","rgba(239,68,68,.2)","●","Macro dampening active — signals reduced by 25% overlay"),
        "HIGH VOLATILITY":  ("#f97316","rgba(249,115,22,.07)","rgba(249,115,22,.2)","⚡","High volatility — macro overlay at maximum dampening"),
    }.get(regime, ("#d4a843","rgba(212,168,67,.07)","rgba(212,168,67,.2)","◐","Macro overlay at baseline"))

    color, bg, border, icon, desc = cfg

    events_html = ""
    if events:
        nice = {"tariff_broad":"Tariff Headwinds","tariff_relief":"Tariff Relief",
                "fed_hawkish":"Fed Hawkish","fed_dovish":"Fed Dovish",
                "recession_signal":"Recession Signal","war_escalation":"War Escalation",
                "chip_export_ban":"Chip Export Ban","oil_spike":"Oil Spike"}
        for e in events[:3]:
            events_html += f'<span style="background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:3px;padding:2px 8px;font-size:10px;color:#94a3b8;margin-right:6px;">{nice.get(e,e.replace("_"," ").title())}</span>'

    src_badge = (f'<span style="font-size:10px;color:#1D9E75;margin-left:8px;">⚡ Live</span>'
                 if source=="live"
                 else '<span style="font-size:10px;color:#475569;margin-left:8px;">Est.</span>')

    return (
        f'<div style="background:{bg};border:1px solid {border};border-radius:8px;'
        f'padding:14px 20px;margin-bottom:16px;">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">'
        f'<div style="display:flex;align-items:center;gap:10px;">'
        f'<span style="color:{color};font-size:10px;animation:pulse 2s infinite;">{icon}</span>'
        f'<div>'
        f'<div style="display:flex;align-items:center;gap:6px;">'
        f'<span style="font-family:Syne,sans-serif;font-size:13px;font-weight:700;'
        f'color:{color};letter-spacing:.1em;">MACRO REGIME: {regime}</span>'
        f'{src_badge}</div>'
        f'<div style="font-size:13px;color:#64748b;margin-top:2px;">{desc}</div>'
        f'<div style="margin-top:6px;">{events_html}</div>'
        f'</div></div>'
        f'<div style="display:flex;gap:20px;flex-wrap:wrap;">'
        f'<div style="text-align:center;">'
        f'<div style="font-size:16px;font-weight:500;color:#e2e8f0;">75%</div>'
        f'<div style="font-size:11px;color:#475569;">Quant weight</div></div>'
        f'<div style="text-align:center;">'
        f'<div style="font-size:16px;font-weight:500;color:{color};">25%</div>'
        f'<div style="font-size:11px;color:#475569;">Macro weight</div></div>'
        f'<div style="text-align:center;">'
        f'<div style="font-size:16px;font-weight:500;color:#e2e8f0;">{len(events)}</div>'
        f'<div style="font-size:11px;color:#475569;">Active events</div></div>'
        f'</div></div>'
        f'</div>'
    )


def factor_panel_html(r: dict, is_gem: bool = False) -> str:
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

    gem_badge = '<span style="font-size:11px;margin-left:6px;">💎</span>' if is_gem else ""
    action_arrow = "▲" if act=="BUY" else "▼" if act=="SELL" else "─"

    # Build HTML as a variable first — no comments, no risk of comment stripping
    html_parts = [
        f'<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);'
        f'border-left:{left_border};border-radius:8px;padding:16px 18px;margin-bottom:8px;">',

        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;">',
        f'<div style="display:flex;align-items:center;gap:10px;">',
        f'<span style="font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:#e2e8f0;">'
        f'{r["ticker"]}{gem_badge}</span>',
        f'<span style="font-family:Syne,sans-serif;font-size:11px;font-weight:700;color:{act_c};'
        f'background:{act_bg};border:1px solid {act_brd};padding:3px 10px;border-radius:3px;'
        f'letter-spacing:.1em;">{action_arrow} {act}</span>',
        f'<span style="font-size:11px;color:#475569;">{r.get("sector","")[:16]}</span>',
        f'</div>',
        f'<div style="text-align:right;">',
        f'<div style="font-family:DM Mono,monospace;font-size:26px;font-weight:500;color:{act_c};">{score:.0f}</div>',
        f'<div style="font-size:12px;color:#475569;margin-top:2px;">blended score</div>',
        f'</div></div>',

        f'<div style="display:flex;gap:10px;margin-bottom:12px;">{pillar_bars}</div>',

        f'<div style="display:flex;gap:8px;flex-wrap:wrap;padding-top:10px;border-top:1px solid rgba(255,255,255,.05);">',
        f'<div style="background:rgba(255,255,255,.04);border-radius:4px;padding:7px 12px;flex:1;min-width:70px;">'
        f'<div style="font-size:11px;color:#475569;letter-spacing:.07em;margin-bottom:4px;">QUANT</div>'
        f'<div style="font-family:DM Mono,monospace;font-size:16px;color:#94a3b8;font-weight:500;">{quant:.1f}</div></div>',
        f'<div style="background:rgba(255,255,255,.04);border-radius:4px;padding:7px 12px;flex:1;min-width:70px;">'
        f'<div style="font-size:11px;color:#475569;letter-spacing:.07em;margin-bottom:4px;">MACRO</div>'
        f'<div style="font-family:DM Mono,monospace;font-size:16px;color:{delta_c};font-weight:500;">{delta_str}</div></div>',
        f'<div style="background:rgba(255,255,255,.04);border-radius:4px;padding:7px 12px;flex:1;min-width:70px;">'
        f'<div style="font-size:11px;color:#475569;letter-spacing:.07em;margin-bottom:4px;">BLEND</div>'
        f'<div style="font-family:DM Mono,monospace;font-size:16px;color:#d4a843;font-weight:500;">75/25</div></div>',
        f'<div style="background:rgba(255,255,255,.04);border-radius:4px;padding:7px 12px;flex:1;min-width:70px;">'
        f'<div style="font-size:11px;color:#475569;letter-spacing:.07em;margin-bottom:4px;">RANK</div>'
        f'<div style="font-family:DM Mono,monospace;font-size:16px;color:#94a3b8;font-weight:500;">{r.get("pct_rank",50):.0f}th</div></div>',
        f'</div></div>',
    ]
    return "".join(html_parts)

# ── COOKIE BANNER ─────────────────────────────────────────────────────────────
def cookie_banner():
    """No-op — cookie consent is now handled as a dedicated page in the router."""
    pass

# ── DISCLAIMER ────────────────────────────────────────────────────────────────
DISCLAIMER = """<div style="background:rgba(251,191,36,.05);border:1px solid rgba(251,191,36,.2);
border-radius:4px;padding:12px 16px;font-size:11px;color:#64748b;line-height:1.7;margin:1rem 0;">
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

**No Investment Advice:** Model BUY, HOLD, and SELL signals are algorithmic outputs based on
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
    .legal-body th { font-size:12px;color:#475569;text-align:left;padding:8px 12px;
                     border-bottom:1px solid rgba(255,255,255,.08); }
    .legal-body td { font-size:13px;color:#94a3b8;padding:8px 12px;
                     border-bottom:1px solid rgba(255,255,255,.04); }
    </style>
    """, unsafe_allow_html=True)

    bc1, bc2 = st.columns([1, 8])
    with bc1:
        if st.button("← Back", key="legal_back"):
            go("landing")

    st.markdown('<div class="legal-body">', unsafe_allow_html=True)
    st.markdown(text)
    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# COOKIE CONSENT PAGE — full page, 100% reliable buttons
# ══════════════════════════════════════════════════════════════════════════════
def page_cookie_consent():
    """Full-page cookie consent — all Streamlit native, no large HTML blocks."""
    st.markdown(
        "<style>"
        "html,body,[data-testid='stAppViewContainer'],[data-testid='stMain'],"
        "[data-testid='stMainBlockContainer'],.main{background:#08090f!important;}"
        ".main .block-container{padding:0!important;max-width:100%!important;}"
        "#MainMenu,header,footer,[data-testid='stHeader']{display:none!important;}"
        "</style>",
        unsafe_allow_html=True
    )
    st.markdown("<div style='height:5vh'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div style='text-align:center;font-family:Syne,sans-serif;font-size:30px;"
        "font-weight:800;color:#e2e4f0;margin-bottom:4px;'>Q"
        "<span style='color:#d4a843;'>NTM</span></div>"
        "<div style='text-align:center;font-size:11px;color:#475569;"
        "letter-spacing:.2em;margin-bottom:28px;'>CONVICTION FACTOR MODEL</div>",
        unsafe_allow_html=True
    )

    # Card border only — no content inside HTML
    st.markdown(
        "<div style='max-width:580px;margin:0 auto;border:1px solid rgba(212,168,67,.4);"
        "border-radius:12px;padding:32px 36px 24px;background:#0d1117;'>",
        unsafe_allow_html=True
    )

    st.markdown("## 🍪 Cookie & Privacy Notice")
    st.markdown(
        "QNTM uses **essential cookies** for login and session management "
        "and **analytical cookies** to improve the platform. "
        "We never sell your data or use cookies for advertising.\n\n"
        "By continuing you agree to our **Privacy Policy**, **Cookie Policy**, "
        "and **Terms of Service**. QNTM is a quantitative research tool — *not investment advice*."
    )
    st.info(
        "**Essential cookies** — login session, security. Required, cannot be disabled.  \n"
        "**Analytical cookies** — anonymous usage stats. Can be declined below."
    )

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("✓  Accept All Cookies", key="ck_accept", use_container_width=True):
            st.session_state.cookies_accepted = True
            st.rerun()
    with col2:
        if st.button("Essential Only", key="ck_essential", use_container_width=True):
            st.session_state.cookies_accepted = True
            st.rerun()

    st.markdown(
        "<div style='text-align:center;margin-top:10px;font-size:11px;color:#334155;'>"
        "Your choice is saved for this session.</div>",
        unsafe_allow_html=True
    )


def page_landing():
    bt = BACKTEST_DATA

    # ── Global landing CSS — overrides Streamlit defaults completely ─────────────
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Mono:wght@400;500&family=Outfit:wght@300;400;500;600&display=swap');

    /* ── Hard reset Streamlit to dark theme ── */
    html, body, [class*="css"], .main, .block-container,
    [data-testid="stAppViewContainer"], [data-testid="stMain"],
    [data-testid="stMainBlockContainer"] {
        background-color: #0a0b14 !important;
        color: #e2e4f0 !important;
        font-family: 'Outfit', sans-serif !important;
    }
    [data-testid="stAppViewContainer"] > section > div {
        background-color: #0a0b14 !important;
    }
    /* Remove Streamlit default padding */
    .main .block-container {
        padding: 0 !important;
        max-width: 100% !important;
    }
    /* Hide hamburger, header, footer */
    #MainMenu, header[data-testid="stHeader"], footer { display: none !important; }

    /* ── Layout helpers ── */
    .land-section { padding: 72px 48px; max-width: 1200px; margin: 0 auto; }
    .land-divider  { border-top: 1px solid rgba(255,255,255,.06); }

    /* ── Animations ── */
    @keyframes land-pulse  { 0%,100%{opacity:1} 50%{opacity:.3} }
    @keyframes land-ticker { 0%{transform:translateX(0)} 100%{transform:translateX(-50%)} }

    /* ── Streamlit columns on landing ── */
    section[data-testid="stMain"] [data-testid="stHorizontalBlock"] {
        gap: 6px !important;
        background: transparent !important;
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
        padding: 0 48px;
        height: 60px;
        display: flex;
        align-items: center;
        justify-content: space-between;
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

    # Real Streamlit buttons — positioned by CSS to appear in nav
    # We use a columns row right below the nav HTML
    st.markdown("""
    <style>
    /* Float the nav button row up into the sticky nav bar */
    div[data-testid="stHorizontalBlock"]:has(button[data-testid*="nav_signin"]),
    div[data-testid="stHorizontalBlock"]:has(button[key="nav_signin"]) {
        position: fixed !important;
        top: 10px !important;
        right: 48px !important;
        z-index: 1000 !important;
        width: auto !important;
        display: flex !important;
        gap: 8px !important;
        background: transparent !important;
    }
    </style>
    """, unsafe_allow_html=True)

    _, nav_r1, nav_r2 = st.columns([7, 1, 1])
    with nav_r1:
        st.markdown('<div class="land-btn-ghost">', unsafe_allow_html=True)
        if st.button("Sign In", key="nav_signin", use_container_width=True):
            st.session_state.auth_tab = "signin"
            go("auth")
        st.markdown('</div>', unsafe_allow_html=True)
    with nav_r2:
        st.markdown('<div class="land-btn-primary">', unsafe_allow_html=True)
        if st.button("Get Started", key="nav_register", use_container_width=True):
            st.session_state.auth_tab = "register"
            go("auth")
        st.markdown('</div>', unsafe_allow_html=True)

    # ── HERO ──────────────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="padding:80px 48px 60px;max-width:1200px;margin:0 auto;
         background:radial-gradient(ellipse 80% 50% at 50% -10%,rgba(212,168,67,.08) 0%,transparent 70%);">

      <div style="display:inline-flex;align-items:center;gap:10px;
           background:rgba(212,168,67,.08);border:1px solid rgba(212,168,67,.25);
           border-radius:100px;padding:6px 16px;margin-bottom:28px;">
        <div style="width:7px;height:7px;background:#00ff87;border-radius:50%;
             animation:land-pulse 2s infinite;flex-shrink:0;"></div>
        <span style="font-family:'DM Mono',monospace;font-size:11px;color:#d4a843;letter-spacing:.1em;">
          MODEL LIVE &middot; 5-YR VALIDATED &middot; 963 STOCKS &middot; RISK-OFF REGIME
        </span>
      </div>

      <h1 style="font-family:'Syne',sans-serif;font-size:clamp(44px,7vw,84px);
           font-weight:800;line-height:.95;letter-spacing:-.02em;color:#ffffff;margin-bottom:22px;">
        Institutional-grade quant signals.<br>
        <span style="color:#d4a843;">Built for retail investors.</span>
      </h1>

      <p style="font-size:18px;color:#94a3b8;max-width:540px;line-height:1.75;margin-bottom:40px;">
        Institutional-grade factor model for retail investors. Know exactly what to buy,
        when to hold, and &mdash; critically &mdash; what to avoid.
      </p>
    </div>
    """, unsafe_allow_html=True)

    # Hero CTA buttons — real Streamlit, work immediately
    hero_gap, hero_b1, hero_b2, _ = st.columns([3, 1, 1, 4])
    with hero_b1:
        st.markdown('<div class="land-btn-primary">', unsafe_allow_html=True)
        if st.button("⚡ Get Started Free", key="hero_register", use_container_width=True):
            st.session_state.auth_tab = "register"
            go("auth")
        st.markdown('</div>', unsafe_allow_html=True)
    with hero_b2:
        st.markdown('<div class="land-btn-ghost">', unsafe_allow_html=True)
        if st.button("Sign In →", key="hero_signin", use_container_width=True):
            st.session_state.auth_tab = "signin"
            go("auth")
        st.markdown('</div>', unsafe_allow_html=True)

    # ── TICKER TAPE ───────────────────────────────────────────────────────────
    st.markdown("""
    <div style="overflow:hidden;background:rgba(0,255,135,.04);
         border-top:1px solid rgba(0,255,135,.12);border-bottom:1px solid rgba(0,255,135,.12);
         padding:13px 0;margin-top:8px;">
      <div style="display:inline-flex;animation:land-ticker 45s linear infinite;white-space:nowrap;">
        <span style="font-family:'DM Mono',monospace;font-size:12px;padding:0 24px;">
          <span style="color:#00ff87;">NVDA BUY</span> &middot;
          <span style="color:#00ff87;">META BUY</span> &middot;
          <span style="color:#00ff87;">AVGO BUY</span> &middot;
          <span style="color:#E24B4A;">UNH SELL</span> &middot;
          <span style="color:#00ff87;">JPM BUY</span> &middot;
          <span style="color:#E24B4A;">SNAP SELL</span> &middot;
          <span style="color:#00ff87;">NFLX BUY</span> &middot;
          <span style="color:#E24B4A;">NKE SELL</span> &middot;
          <span style="color:#00ff87;">COST BUY</span> &middot;
          <span style="color:#00ff87;">GS BUY</span> &middot;
          <span style="color:#E24B4A;">TSLA SELL</span> &middot;
          <span style="color:#00ff87;">WMT BUY</span> &middot;
          <span style="color:#00ff87;">MA BUY</span> &middot;
          <span style="color:#E24B4A;">PFE SELL</span> &middot;
          <span style="color:#00ff87;">MSFT BUY</span> &middot;
          <span style="color:#00ff87;">NVDA BUY</span> &middot;
          <span style="color:#00ff87;">META BUY</span> &middot;
          <span style="color:#00ff87;">AVGO BUY</span> &middot;
          <span style="color:#E24B4A;">UNH SELL</span> &middot;
          <span style="color:#00ff87;">JPM BUY</span> &middot;
          <span style="color:#E24B4A;">SNAP SELL</span> &middot;
          <span style="color:#00ff87;">NFLX BUY</span>
        </span>
        <span style="font-family:'DM Mono',monospace;font-size:12px;padding:0 24px;">
          <span style="color:#00ff87;">NVDA BUY</span> &middot;
          <span style="color:#00ff87;">META BUY</span> &middot;
          <span style="color:#00ff87;">AVGO BUY</span> &middot;
          <span style="color:#E24B4A;">UNH SELL</span> &middot;
          <span style="color:#00ff87;">JPM BUY</span> &middot;
          <span style="color:#E24B4A;">SNAP SELL</span> &middot;
          <span style="color:#00ff87;">NFLX BUY</span>
        </span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── PERFORMANCE SECTION ───────────────────────────────────────────────────
    st.markdown("""
    <div class="land-divider"></div>
    <div class="land-section">
      <div style="font-family:'DM Mono',monospace;font-size:11px;color:#d4a843;letter-spacing:.2em;margin-bottom:14px;">&mdash; PERFORMANCE</div>
      <h2 style="font-family:'Syne',sans-serif;font-size:clamp(28px,4vw,42px);font-weight:800;
           color:#fff;margin-bottom:10px;line-height:1.1;">
        5 years. 6 regimes.<br><span style="color:#d4a843;">Proven in every market.</span>
      </h2>
      <p style="color:#94a3b8;margin-bottom:40px;">Real data. Same rules every year. No tuning.</p>
    </div>
    """, unsafe_allow_html=True)

    # Big 4 stats
    p1, p2, p3, p4 = st.columns(4)
    for col, label, val, sub, color in [
        (p1, "MODEL 5-YR TOTAL",  f"+{bt['model_total_ret']:.1f}%", f"${bt['model_final_100k']:,} from $100K", "#d4a843"),
        (p2, "SPY SAME PERIOD",   f"+{bt['spy_total_ret']:.1f}%",   f"${bt['spy_final_100k']:,} from $100K",   "#64748b"),
        (p3, "MODEL CAGR",        f"+{bt['model_cagr']:.1f}%",      f"vs SPY +{bt['spy_cagr']:.1f}%",          "#d4a843"),
        (p4, "5-YR ADVANTAGE",    f"+${bt['model_advantage_usd']:,}","on $100,000 invested",                     "#1D9E75"),
    ]:
        with col:
            st.markdown(f"""
            <div style="background:#0e0f1a;border:1px solid rgba(255,255,255,.07);
                 border-radius:8px;padding:22px 18px;margin:0 24px 16px;">
              <div style="font-family:'DM Mono',monospace;font-size:10px;color:#94a3b8;
                   letter-spacing:.12em;margin-bottom:10px;">{label}</div>
              <div style="font-family:'Syne',sans-serif;font-size:34px;font-weight:800;
                   color:{color};line-height:1;">{val}</div>
              <div style="font-size:12px;color:#94a3b8;margin-top:8px;">{sub}</div>
            </div>
            """, unsafe_allow_html=True)

    # Regime cards
    st.markdown('<div style="padding:0 24px;font-size:13px;color:#94a3b8;margin-bottom:14px;">Same rules every year — no tuning between regimes:</div>', unsafe_allow_html=True)
    rc = st.columns(6)
    for col, p in zip(rc, bt["periods"]):
        beat = p["beat"]
        bc   = "rgba(29,158,117,.35)" if beat else "rgba(226,75,74,.25)"
        ic   = "#1D9E75" if beat else "#E24B4A"
        mc   = "#1D9E75" if p["model_ret"] >= 0 else "#E24B4A"
        sc_c = "#4ade80" if p["spy_ret"] >= 0 else "#E24B4A"
        with col:
            st.markdown(f"""
            <div style="background:#0e0f1a;border:1px solid {bc};border-radius:8px;padding:14px 10px;margin:0 0 0 24px;">
              <div style="font-family:'DM Mono',monospace;font-size:10px;color:#94a3b8;margin-bottom:4px;">{p['key']}</div>
              <div style="font-family:'Syne',sans-serif;font-size:11px;font-weight:700;color:#94a3b8;margin-bottom:8px;line-height:1.3;">{p['label']}</div>
              <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:{ic};">{'&#10003;' if beat else '&#10007;'}</div>
              <div style="margin-top:6px;">
                <div style="font-family:'DM Mono',monospace;font-size:12px;color:{mc};font-weight:500;">QNTM {p['model_ret']:+.1f}%</div>
                <div style="font-family:'DM Mono',monospace;font-size:11px;color:{sc_c};margin-top:2px;">SPY {p['spy_ret']:+.1f}%</div>
              </div>
            </div>
            """, unsafe_allow_html=True)

    # Risk metrics row
    st.markdown('<div style="height:16px;"></div>', unsafe_allow_html=True)
    rm = st.columns(6)
    for col, (label, val, sub) in zip(rm, [
        ("SHARPE",    "1.51",  ">1.0 excellent"),
        ("SORTINO",   "2.52",  ">1.5 strong"),
        ("INFO RATIO","1.75",  ">0.5 signal"),
        ("MAX DD",    "-4.8%", "SPY hit -18.2%"),
        ("WIN RATE",  "83.3%", "5 of 6 regimes"),
        ("CAGR ALPHA","+27.3pp","/yr vs index"),
    ]):
        with col:
            st.markdown(f"""
            <div style="background:rgba(212,168,67,.05);border:1px solid rgba(212,168,67,.15);
                 border-radius:6px;padding:14px;text-align:center;margin:0 0 0 24px;">
              <div style="font-family:'DM Mono',monospace;font-size:9px;color:#94a3b8;
                   letter-spacing:.1em;margin-bottom:6px;">{label}</div>
              <div style="font-family:'Syne',sans-serif;font-size:20px;font-weight:800;color:#d4a843;">{val}</div>
              <div style="font-size:10px;color:#94a3b8;margin-top:4px;">{sub}</div>
            </div>
            """, unsafe_allow_html=True)

    # ── THE MODEL ─────────────────────────────────────────────────────────────
    st.markdown("""
    <div class="land-divider" style="margin-top:32px;"></div>
    <div class="land-section">
      <div style="font-family:'DM Mono',monospace;font-size:11px;color:#d4a843;letter-spacing:.2em;margin-bottom:14px;">&mdash; THE MODEL</div>
      <h2 style="font-family:'Syne',sans-serif;font-size:clamp(28px,4vw,42px);font-weight:800;
           color:#fff;margin-bottom:12px;line-height:1.1;">
        Five pillars.<br><span style="color:#d4a843;">One conviction score.</span>
      </h2>
      <p style="color:#94a3b8;max-width:520px;margin-bottom:36px;line-height:1.7;">
        36 factors scored weekly across 5 research-backed pillars — plus a 75/25 macro overlay.
        The model tells you exactly what to buy, hold, or exit. And why.
      </p>
    </div>
    """, unsafe_allow_html=True)

    mc = st.columns(5)
    for col, (name, weight, desc, color) in zip(mc, [
        ("Momentum",  "30%", "Price trend, RSI, MACD, MA crossovers, 52-week proximity",      "#d4a843"),
        ("Quality",   "25%", "ROE, profit margin, revenue growth, EPS beat rate, FCF yield",   "#1D9E75"),
        ("Volume",    "20%", "Relative volume, OBV, Chaikin Money Flow, accumulation/dist.",   "#00ff87"),
        ("Value",     "15%", "Forward P/E, PEG ratio, EV/EBITDA, Price-to-Sales, FCF yield",  "#f59e0b"),
        ("Sentiment", "10%", "Short interest, insider buy ratio, institutional ownership",      "#f97316"),
    ]):
        with col:
            st.markdown(f"""
            <div style="background:#0e0f1a;border:1px solid rgba(255,255,255,.07);border-radius:8px;
                 padding:18px 14px;margin:0 0 0 24px;">
              <div style="font-family:'Syne',sans-serif;font-size:26px;font-weight:800;
                   color:{color};margin-bottom:4px;">{weight}</div>
              <div style="font-family:'Syne',sans-serif;font-size:13px;font-weight:700;
                   color:#e2e4f0;margin-bottom:8px;">{name}</div>
              <div style="font-size:11px;color:#94a3b8;line-height:1.6;">{desc}</div>
            </div>
            """, unsafe_allow_html=True)

    # Signal boxes
    st.markdown('<div style="height:16px;"></div>', unsafe_allow_html=True)
    sig1, sig2, sig3 = st.columns(3)
    for col, (label, score, desc, color, brd) in zip([sig1,sig2,sig3], [
        ("▲ BUY SIGNAL",   "Score ≥ 60", "Enter position. Hold until exit signal fires. Designed for LTCG tax treatment — 12+ month holds.", "#1D9E75", "rgba(29,158,117,.3)"),
        ("─ HOLD",         "Score 45–59","Maintain existing positions. No new capital deployed. Monitor for further deterioration.",            "#f59e0b", "rgba(245,158,11,.25)"),
        ("▼ EXIT SIGNAL",  "Score < 45", "Exit or reduce. This caught UNH at month 3 — avoided the −49% full-year drawdown.",                  "#E24B4A", "rgba(226,75,74,.25)"),
    ]):
        with col:
            st.markdown(f"""
            <div style="background:#0e0f1a;border:1px solid {brd};border-radius:8px;
                 padding:22px;margin:0 0 0 24px;">
              <div style="font-family:'Syne',sans-serif;font-size:12px;font-weight:700;
                   color:{color};letter-spacing:.1em;margin-bottom:8px;">{label}</div>
              <div style="font-family:'DM Mono',monospace;font-size:22px;font-weight:500;
                   color:{color};margin-bottom:10px;">{score}</div>
              <div style="font-size:13px;color:#94a3b8;line-height:1.7;">{desc}</div>
            </div>
            """, unsafe_allow_html=True)

    # ── PRICING ───────────────────────────────────────────────────────────────
    st.markdown("""
    <div class="land-divider" style="margin-top:32px;"></div>
    <div class="land-section">
      <div style="font-family:'DM Mono',monospace;font-size:11px;color:#d4a843;letter-spacing:.2em;margin-bottom:14px;">&mdash; PRICING</div>
      <h2 style="font-family:'Syne',sans-serif;font-size:clamp(28px,4vw,42px);font-weight:800;
           color:#fff;margin-bottom:10px;line-height:1.1;">
        Two tiers.<br><span style="color:#d4a843;">Both built for serious investors.</span>
      </h2>
      <p style="color:#94a3b8;margin-bottom:36px;">First 50 users get Founding Member access free — unlimited everything.</p>
    </div>
    """, unsafe_allow_html=True)

    pr1, pr2, pr3 = st.columns(3)

    def feat_row(text, highlight=False):
        dot  = "●" if highlight else "○"
        dc   = "#1D9E75" if highlight else "#475569"
        tc   = "#e2e4f0" if highlight else "#64748b"
        return f'<div style="display:flex;align-items:flex-start;gap:10px;padding:5px 0;font-size:13px;"><span style="color:{dc};flex-shrink:0;">{dot}</span><span style="color:{tc};">{text}</span></div>'

    with pr1:
        st.markdown(f"""
        <div style="background:#0e0f1a;border:1px solid rgba(255,255,255,.07);
             border-radius:10px;padding:26px 22px;margin:0 0 0 24px;">
          <div style="font-family:'Syne',sans-serif;font-size:12px;font-weight:700;
               color:#94a3b8;letter-spacing:.08em;margin-bottom:10px;">FREE</div>
          <div style="font-family:'Syne',sans-serif;font-size:36px;font-weight:800;
               color:#e2e4f0;line-height:1;">$0</div>
          <div style="font-size:11px;color:#94a3b8;margin-bottom:20px;margin-top:4px;">forever</div>
          <div style="border-top:1px solid rgba(255,255,255,.06);padding-top:16px;">
            {feat_row("963-stock universe screener")}
            {feat_row("BUY / HOLD / SELL signals with factor breakdown")}
            {feat_row("5 pillar scores: Momentum, Quality, Volume, Value, Sentiment")}
            {feat_row("75/25 quant/macro blend")}
            {feat_row("Portfolio tracker — up to 10 positions")}
            {feat_row("5-year validated backtest (+505% CAGR)")}
            {feat_row("Macro regime indicator (3 active events)")}
            {feat_row("Search any ticker for instant model score")}
          </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)
        st.markdown('<div class="land-btn-ghost" style="padding:0 0 0 24px;">', unsafe_allow_html=True)
        if st.button("Get Started Free", key="price_free", use_container_width=True):
            st.session_state.auth_tab = "register"
            go("auth")
        st.markdown('</div>', unsafe_allow_html=True)

    with pr2:
        st.markdown(f"""
        <div style="background:rgba(212,168,67,.04);border:2px solid rgba(212,168,67,.5);
             border-radius:10px;padding:26px 22px;margin:0 0 0 8px;">
          <div style="background:#d4a843;color:#000;font-family:'Syne',sans-serif;font-size:10px;
               font-weight:700;letter-spacing:.1em;padding:3px 10px;border-radius:2px;
               display:inline-block;margin-bottom:10px;">MOST POPULAR</div>
          <div style="font-family:'Syne',sans-serif;font-size:12px;font-weight:700;
               color:#94a3b8;letter-spacing:.08em;margin-bottom:10px;">FOUNDING MEMBER</div>
          <div style="font-family:'Syne',sans-serif;font-size:36px;font-weight:800;
               color:#d4a843;line-height:1;">$0</div>
          <div style="font-size:11px;color:#94a3b8;margin-bottom:20px;margin-top:4px;">
            first 50 users &middot; then $29/mo
          </div>
          <div style="border-top:1px solid rgba(255,255,255,.06);padding-top:16px;">
            {feat_row("Everything in Free", True)}
            {feat_row("Unlimited portfolio positions", True)}
            {feat_row("💎 Hidden Gem detection across 963 stocks", True)}
            {feat_row("Real-time BUY/SELL signal alerts on your holdings", True)}
            {feat_row("Macro regime change alerts (war, oil, tariffs)", True)}
            {feat_row("Portfolio value tracker with period toggles", True)}
            {feat_row("Email signal notifications", True)}
            {feat_row("Founding member badge — locked in at $0", True)}
          </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)
        st.markdown('<div class="land-btn-primary" style="padding:0 0 0 8px;">', unsafe_allow_html=True)
        if st.button("Join Free — 50 Spots", key="price_founding", use_container_width=True):
            st.session_state.auth_tab = "register"
            st.session_state.auto_upgrade = True   # flag to upgrade after registration
            go("auth")
        st.markdown('</div>', unsafe_allow_html=True)

    with pr3:
        st.markdown(f"""
        <div style="background:#0e0f1a;border:1px solid rgba(255,255,255,.07);
             border-radius:10px;padding:26px 22px;margin:0 0 0 8px;">
          <div style="font-family:'Syne',sans-serif;font-size:12px;font-weight:700;
               color:#94a3b8;letter-spacing:.08em;margin-bottom:10px;">INSTITUTIONAL</div>
          <div style="font-family:'Syne',sans-serif;font-size:36px;font-weight:800;
               color:#e2e4f0;line-height:1;">Custom</div>
          <div style="font-size:11px;color:#94a3b8;margin-bottom:20px;margin-top:4px;">contact us</div>
          <div style="border-top:1px solid rgba(255,255,255,.06);padding-top:16px;">
            {feat_row("Everything in Pro", True)}
            {feat_row("Raw API access to all model scores", True)}
            {feat_row("Custom stock universe upload", True)}
            {feat_row("White-label branding option", True)}
            {feat_row("Dedicated support & SLA guarantee", True)}
            {feat_row("Multi-user team accounts", True)}
          </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)
        st.markdown('<div class="land-btn-ghost" style="padding:0 0 0 8px;">', unsafe_allow_html=True)
        if st.button("Contact Us", key="price_inst", use_container_width=True):
            st.markdown('<script>window.location.href="mailto:hello@qntm.app"</script>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # ── FOOTER ────────────────────────────────────────────────────────────────
    st.markdown("""
    <div class="land-divider" style="margin-top:32px;"></div>
    <div style="background:#080910;padding:48px 48px 40px;">
      <div style="max-width:1200px;margin:0 auto;display:flex;justify-content:space-between;
           align-items:flex-start;flex-wrap:wrap;gap:32px;margin-bottom:32px;">
        <div>
          <div style="font-family:'Syne',sans-serif;font-size:20px;font-weight:800;
               color:#e2e4f0;margin-bottom:6px;">Q<span style="color:#d4a843;">NTM</span></div>
          <div style="font-size:12px;color:#475569;line-height:1.7;max-width:280px;">
            Quantitative conviction factor model platform.<br>
            Institutional-grade research for retail investors.
          </div>
        </div>
        <div style="display:flex;gap:48px;flex-wrap:wrap;">
          <div>
            <div style="font-family:'DM Mono',monospace;font-size:10px;color:#64748b;letter-spacing:.12em;margin-bottom:12px;">LEGAL</div>
            <div style="font-size:13px;color:#475569;line-height:2.2;">
              <span style="color:#94a3b8;cursor:pointer;" id="lnk_privacy">Privacy Policy</span><br>
              <span style="color:#94a3b8;cursor:pointer;" id="lnk_terms">Terms of Service</span><br>
              <span style="color:#94a3b8;cursor:pointer;" id="lnk_cookies">Cookie Policy</span>
            </div>
          </div>
          <div>
            <div style="font-family:'DM Mono',monospace;font-size:10px;color:#64748b;letter-spacing:.12em;margin-bottom:12px;">CONTACT</div>
            <div style="font-size:13px;color:#475569;line-height:2.2;">
              <a href="mailto:hello@qntm.app" style="color:#94a3b8;text-decoration:none;display:block;">hello@qntm.app</a>
            </div>
          </div>
        </div>
      </div>
      <div style="background:rgba(212,168,67,.05);border:1px solid rgba(212,168,67,.15);
           border-radius:8px;padding:18px 22px;margin-bottom:28px;max-width:1200px;margin-left:auto;margin-right:auto;">
        <div style="font-family:'DM Mono',monospace;font-size:10px;color:#d4a843;letter-spacing:.12em;margin-bottom:8px;">IMPORTANT DISCLAIMER</div>
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
        <div style="font-size:11px;color:#334155;">&copy; 2025 QNTM. All rights reserved.</div>
        <div style="font-size:11px;color:#334155;">
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
          <div style="font-size:11px;color:#334155;letter-spacing:.2em;margin-top:6px;">
            CONVICTION FACTOR MODEL
          </div>
        </div>
        """, unsafe_allow_html=True)

        # Tab selection — stored in session so it survives reruns
        if "auth_tab" not in st.session_state:
            st.session_state.auth_tab = "signin"

        tab_signin, tab_register = st.tabs(["Sign In", "Create Free Account"])

        # ── SIGN IN ───────────────────────────────────────────────────────────
        with tab_signin:
            st.markdown('<div style="height:12px;"></div>', unsafe_allow_html=True)

            si_email = st.text_input("Email address", key="si_email",
                                     placeholder="you@example.com")
            si_pass  = st.text_input("Password", type="password", key="si_pass",
                                     placeholder="••••••••")
            st.markdown('<div style="height:10px;"></div>', unsafe_allow_html=True)

            si_remember = st.checkbox("Remember me on this device", key="si_remember", value=False)
            st.markdown('<div style="height:6px;"></div>', unsafe_allow_html=True)

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
                            st.session_state.remember_me        = si_remember
                            go("mfa")
                        else:
                            st.session_state.logged_in    = True
                            st.session_state.user         = user
                            st.session_state.mfa_verified = True
                            st.session_state.scan_results = None
                            # Force MFA setup on first login if not yet configured
                            st.session_state.force_mfa_setup = True
                            if si_remember:
                                # Persist session via query params
                                st.query_params["uid"]  = user["id"]
                                st.query_params["plan"] = user.get("plan","free")
                            go("platform")
                    else:
                        st.error(res.get("error", "Invalid email or password"))

            st.markdown("""
            <div style="text-align:center;margin-top:20px;">
              <span style="font-size:12px;color:#334155;">
                Don't have an account? Use the <strong style="color:#00ff87;">Create Free Account</strong> tab above.
              </span>
            </div>
            """, unsafe_allow_html=True)

        # ── REGISTER ──────────────────────────────────────────────────────────
        with tab_register:
            st.markdown('<div style="height:12px;"></div>', unsafe_allow_html=True)

            # Plan selection
            st.markdown("""
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:20px;">
              <div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.08);
                   border-radius:6px;padding:14px;text-align:center;">
                <div style="font-family:'Syne',sans-serif;font-size:12px;font-weight:700;
                     color:#94a3b8;letter-spacing:.08em;margin-bottom:4px;">FREE</div>
                <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:#e2e4f0;">$0</div>
                <div style="font-size:10px;color:#334155;margin-top:4px;">forever</div>
                <div style="font-size:11px;color:#475569;margin-top:8px;line-height:1.6;">
                  Screener · BUY/HOLD/SELL signals<br>Up to 10 portfolio positions<br>5-yr backtest data
                </div>
              </div>
              <div style="background:rgba(212,168,67,.05);border:1px solid rgba(212,168,67,.4);
                   border-radius:6px;padding:14px;text-align:center;">
                <div style="background:#d4a843;color:#000;font-size:9px;font-weight:700;
                     letter-spacing:.1em;padding:2px 8px;border-radius:2px;display:inline-block;
                     margin-bottom:4px;">FOUNDING MEMBER</div>
                <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:#d4a843;">$0</div>
                <div style="font-size:10px;color:#94a3b8;margin-top:4px;">first 50 users · then $29/mo</div>
                <div style="font-size:11px;color:#94a3b8;margin-top:8px;line-height:1.6;">
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

            if st.button("Create Free Account", key="rg_btn", use_container_width=True):
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
                          {'<div style="font-size:11px;color:#d4a843;margin-top:4px;">' + tag + ' — unlimited holdings, hidden gems &amp; alerts are live.</div>' if tag else ''}
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.error(res.get("error", "Registration failed — please try again"))

        st.markdown('<div style="height:24px;"></div>', unsafe_allow_html=True)
        st.markdown(DISCLAIMER, unsafe_allow_html=True)

    # Legal navigation buttons (invisible layout, activated by clicking links)
    lc1, lc2, lc3, lc4 = st.columns(4)
    for col, doc, label in [
        (lc1,"privacy","Privacy Policy"),
        (lc2,"terms","Terms of Service"),
        (lc3,"disclaimer","Investment Disclaimer"),
        (lc4,"cookies","Cookie Policy"),
    ]:
        with col:
            if st.button(label, key=f"legal_{doc}"):
                st.session_state.legal_doc = doc
                go("legal")

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
          <p style="color:#64748b;margin-top:8px;">Enter the 6-digit code from your authenticator app</p>
        </div>
        """, unsafe_allow_html=True)
        code = st.text_input("Authentication Code", max_chars=6, placeholder="000000", key="mfa_code")
        if st.button("Verify & Enter →", key="mfa_verify", use_container_width=True):
            if verify_totp(st.session_state.pending_mfa_secret, code):
                st.session_state.logged_in    = True
                st.session_state.user         = st.session_state.pending_mfa_user
                st.session_state.mfa_verified  = True
                go("platform")
            else:
                st.error("Invalid code — check your app and try again")
        if st.button("← Back to sign in", key="mfa_back"):
            go("auth")


# ══════════════════════════════════════════════════════════════════════════════
# PLATFORM — TOP NAV
# ══════════════════════════════════════════════════════════════════════════════
def platform_nav():
    user  = st.session_state.user or {}
    plan  = user.get("plan","free")
    n_count = get_unread_count(uid()) if plan in ("pro","institutional") else 0
    plan_color = "#00ff87" if plan in ("pro","institutional") else "#475569"
    plan_rgb = "0,255,135" if plan=="pro" else "249,115,22" if plan=="institutional" else "71,85,105"
    # Pre-compute display name — never inline in f-string
    display_name = (user.get("full_name") or "").split()[0] if user.get("full_name") else ""
    if not display_name:
        em = user.get("email","")
        display_name = em[:20] + ("…" if len(em) > 20 else "")
    # Notification badge — build as plain string, not conditional in f-string
    notif_html = (
        f'<span style="background:rgba(239,68,68,.15);color:#ef4444;border-radius:50%;'
        f'width:22px;height:22px;display:inline-flex;align-items:center;justify-content:center;'
        f'font-size:11px;font-weight:700;">{n_count}</span>'
    ) if n_count > 0 else ""

    st.markdown(
        f'<div style="background:rgba(2,4,8,.97);backdrop-filter:blur(12px);'
        f'border-bottom:1px solid rgba(255,255,255,.06);'
        f'padding:0 32px;height:56px;display:flex;align-items:center;'
        f'justify-content:space-between;position:sticky;top:0;z-index:999;">'
        f'<div style="font-family:Syne,sans-serif;font-size:20px;font-weight:800;letter-spacing:.15em;">'
        f'Q<span style="color:#00ff87;">NTM</span></div>'
        f'<div style="display:flex;align-items:center;gap:16px;">'
        f'<span style="background:rgba({plan_rgb},.15);color:{plan_color};'
        f'border:1px solid {plan_color}44;border-radius:3px;padding:3px 10px;'
        f'font-size:10px;font-weight:700;letter-spacing:.12em;font-family:Syne,sans-serif;">'
        f'{plan.upper()}</span>'
        f'{notif_html}'
        f'<span style="font-size:13px;color:#64748b;font-family:DM Mono,monospace;">{display_name}</span>'
        f'</div></div>',
        unsafe_allow_html=True
    )

    # Nav tabs row
    nav_options = ["📊 Screener","💎 Hidden Gems","📈 Backtest","💼 Portfolio","🔔 Alerts","⚙️ Account"]
    nav_keys    = ["screener","gems","backtest","portfolio","alerts","account"]

    tabs = st.columns(len(nav_options) + 2)
    for i,(label,key) in enumerate(zip(nav_options,nav_keys)):
        with tabs[i+1]:
            active = st.session_state.nav == key
            border = "border-bottom:2px solid #00ff87;" if active else "border-bottom:2px solid transparent;"
            color  = "#00ff87" if active else "#475569"
            st.markdown(f"""
            <div style="{border}padding:8px 0;cursor:pointer;" id="nav_{key}">
              <span style="font-family:'Syne',sans-serif;font-size:11px;letter-spacing:.08em;color:{color};">{label}</span>
            </div>
            """, unsafe_allow_html=True)
            if st.button(label, key=f"nav_{key}_btn", use_container_width=True):
                nav(key)

    with tabs[-1]:
        if st.button("Sign Out", key="signout"):
            for k in ["logged_in","user","mfa_verified","scan_results"]:
                st.session_state[k] = False if k=="logged_in" else None
            go("landing")


# ══════════════════════════════════════════════════════════════════════════════
# SCREENER PAGE
# ══════════════════════════════════════════════════════════════════════════════
def page_screener():
    from model_engine import (MACRO_EVENT_INFO, score_stock, fetch_price_data,
                               SECTORS as ALL_SECTORS, fetch_macro_overlay, apply_macro_overlay)
    try:
        from data_refresh import cache_is_fresh
        cache_fresh = cache_is_fresh()
    except Exception:
        cache_fresh = False
    data_badge  = (
        '<span style="font-size:10px;color:#00ff87;margin-left:8px;">⚡ Live Data</span>'
        if cache_fresh else
        '<span style="font-size:10px;color:#475569;margin-left:8px;">Est. Data · Run refresh for live</span>'
    )
    st.markdown(f"""
    <div style="padding:32px 32px 0;">
      <h1 style="font-family:'Syne',sans-serif;font-size:28px;font-weight:800;">
        Market Screener{data_badge}
      </h1>
      <p style="color:#475569;margin-top:4px;font-size:13px;">
        S&P 500 + Russell 1000 universe · 5 pillars · 75/25 quant/macro blend
      </p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown('<div style="padding:0 32px;">', unsafe_allow_html=True)

    # ── Stock search box ──────────────────────────────────────────────────────
    st.markdown('<div style="font-family:DM Mono,monospace;font-size:11px;color:#475569;letter-spacing:.1em;margin-bottom:6px;">SEARCH ANY STOCK</div>', unsafe_allow_html=True)
    search_col, _ = st.columns([2, 5])
    with search_col:
        search_ticker = st.text_input(
            "", placeholder="e.g. AAPL, TSLA, PLTR...",
            key="screener_search", label_visibility="collapsed"
        ).strip().upper()

    if search_ticker:
        st.markdown(f'<div style="font-family:DM Mono,monospace;font-size:11px;color:#d4a843;letter-spacing:.1em;margin:12px 0 8px;">SCORE FOR {search_ticker}</div>', unsafe_allow_html=True)
        with st.spinner(f"Scoring {search_ticker}..."):
            try:
                price_data = fetch_price_data([search_ticker], period="1y")
                hist = price_data.get(search_ticker, [])
                scored = score_stock(search_ticker, hist)
                macro = st.session_state.get("macro_data") or fetch_macro_overlay(use_live_feeds=True)
                scored_list = apply_macro_overlay([scored], macro)
                sr = scored_list[0]
                sr["pct_rank"] = 50  # unknown rank for ad-hoc search
                is_gem = False
                st.markdown(factor_panel_html(sr, is_gem), unsafe_allow_html=True)
                if search_ticker not in ALL_SECTORS:
                    st.markdown('<div style="font-size:12px;color:#475569;margin-bottom:16px;">⚠ Ticker scored from live price data — not in core universe. Fundamental data may be limited.</div>', unsafe_allow_html=True)
            except Exception as e:
                st.markdown(f'<div style="background:rgba(239,68,68,.06);border:1px solid rgba(239,68,68,.2);border-radius:6px;padding:12px 16px;font-size:13px;color:#ef4444;">Could not score {search_ticker}: {e}</div>', unsafe_allow_html=True)
        st.markdown('<div style="height:8px;border-bottom:1px solid rgba(255,255,255,.06);margin-bottom:20px;"></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    if st.session_state.scan_results is None:
        with st.spinner("Loading universe scores..."):
            raw   = run_full_scan(use_live_prices=False)
            macro = fetch_macro_overlay()
            st.session_state.scan_results = apply_macro_overlay(raw, macro)
            st.session_state.macro_data   = macro

    results = st.session_state.scan_results
    macro   = st.session_state.get("macro_data", {})
    gems = detect_hidden_gems(results)
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
                    f'<div style="font-size:11px;color:#ef4444;letter-spacing:.08em;margin-bottom:4px;">HEADWINDS</div>'
                    f'<div style="font-size:13px;color:#94a3b8;">{info["impact"]}</div></div>'
                    f'<div style="flex:1;min-width:200px;background:rgba(0,255,135,.04);border:1px solid rgba(0,255,135,.15);border-radius:6px;padding:10px 14px;">'
                    f'<div style="font-size:11px;color:#00ff87;letter-spacing:.08em;margin-bottom:4px;">TAILWINDS</div>'
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
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,rgba(212,168,67,.05) 0%,rgba(29,158,117,.05) 100%);
         border:1px solid rgba(212,168,67,.18);border-radius:10px;
         padding:18px 22px;margin-bottom:20px;
         display:flex;gap:24px;align-items:center;flex-wrap:wrap;">
      <div style="flex:1;min-width:220px;">
        <div style="font-family:'DM Mono',monospace;font-size:10px;color:#d4a843;
             letter-spacing:.12em;margin-bottom:6px;">⚡ WHY QNTM IS DIFFERENT</div>
        <div style="font-size:13px;color:#64748b;line-height:1.7;">
          Most screeners give you a score.
          <strong style="color:#94a3b8;">QNTM shows you the reasoning.</strong>
          Every BUY, HOLD, or SELL names the exact factors that moved the needle —
          and shows how the 75/25 macro blend shifted conviction.
        </div>
      </div>
      <div style="display:flex;gap:20px;flex-wrap:wrap;flex-shrink:0;">
        <div style="text-align:center;">
          <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:#d4a843;">5</div>
          <div style="font-size:10px;color:#334155;text-transform:uppercase;letter-spacing:.08em;">Pillars</div>
        </div>
        <div style="text-align:center;">
          <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:#d4a843;">75/25</div>
          <div style="font-size:10px;color:#334155;text-transform:uppercase;letter-spacing:.08em;">Quant/Macro</div>
        </div>
        <div style="text-align:center;">
          <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:#1D9E75;">+40%</div>
          <div style="font-size:10px;color:#334155;text-transform:uppercase;letter-spacing:.08em;">vs SPY 5yr</div>
        </div>
        <div style="text-align:center;">
          <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:#1D9E75;">2.1×</div>
          <div style="font-size:10px;color:#334155;text-transform:uppercase;letter-spacing:.08em;">Sharpe vs SPY</div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(DISCLAIMER, unsafe_allow_html=True)

    # Summary strip
    buys  = sum(1 for r in results if r.get("adj_action",r.get("action"))=="BUY")
    holds = sum(1 for r in results if r.get("adj_action",r.get("action"))=="HOLD")
    sells = sum(1 for r in results if r.get("adj_action",r.get("action"))=="SELL")

    m1,m2,m3,m4,m5 = st.columns(5)
    for col,label,val,color in [
        (m1,"BUY Signals",str(buys),"#00ff87"),
        (m2,"HOLD",str(holds),"#fbbf24"),
        (m3,"SELL Signals",str(sells),"#ef4444"),
        (m4,"Hidden Gems",str(len(gems)),"#00ff87"),
        (m5,"Universe",f"{len(results)} stocks","#475569"),
    ]:
        with col:
            st.markdown(f"""
            <div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);
                 border-radius:4px;padding:14px 16px;margin-bottom:16px;">
              <div style="font-family:'DM Mono',monospace;font-size:10px;color:#475569;letter-spacing:.1em;margin-bottom:6px;">{label}</div>
              <div style="font-family:'Syne',sans-serif;font-size:24px;font-weight:800;color:{color};">{val}</div>
            </div>
            """, unsafe_allow_html=True)

    # ── Screener tabs: Top 10 / Full Universe / Sector Breakdown ──────────────
    buys_ranked  = sorted([r for r in results if r.get("adj_action",r.get("action"))=="BUY"],
                          key=lambda x: x.get("adj_composite",x.get("composite",0)), reverse=True)
    sells_ranked = sorted([r for r in results if r.get("adj_action",r.get("action"))=="SELL"],
                          key=lambda x: x.get("adj_composite",x.get("composite",100)))

    scr_tab1, scr_tab2, scr_tab3 = st.tabs(["📊 Top 10 Summary", "🔍 Full Universe", "📈 Sector Breakdown"])

    # ── TAB 1: TOP 10 ──────────────────────────────────────────────────────────
    with scr_tab1:
        col_b, col_s = st.columns(2)
        for col, label, color, ranked, action_lbl, act_c, act_bg in [
            (col_b, "▲ TOP 10 BUY SIGNALS",  "#00ff87", buys_ranked[:10],  "▲ BUY",  "#00ff87", "rgba(0,255,135,.12)"),
            (col_s, "▼ TOP 10 SELL / EXIT",  "#ef4444", sells_ranked[:10], "▼ SELL", "#ef4444", "rgba(239,68,68,.12)"),
        ]:
            with col:
                count = len(buys_ranked) if action_lbl=="▲ BUY" else len(sells_ranked)
                st.markdown(
                    f'<div style="font-family:DM Mono,monospace;font-size:12px;color:{color};'
                    f'letter-spacing:.1em;margin:16px 0 10px;">{label}</div>',
                    unsafe_allow_html=True)
                st.markdown(
                    '<div style="display:grid;grid-template-columns:70px 1fr 54px 54px 70px;'
                    'gap:6px;padding:8px 12px;background:#050a0f;border-radius:6px 6px 0 0;'
                    'border:1px solid rgba(255,255,255,.07);">'
                    '<div style="font-size:10px;color:#334155;letter-spacing:.08em;">TICKER</div>'
                    '<div style="font-size:10px;color:#334155;letter-spacing:.08em;">SECTOR</div>'
                    '<div style="font-size:10px;color:#334155;letter-spacing:.08em;">SCORE</div>'
                    '<div style="font-size:10px;color:#334155;letter-spacing:.08em;">RANK</div>'
                    '<div style="font-size:10px;color:#334155;letter-spacing:.08em;">SIGNAL</div>'
                    '</div>', unsafe_allow_html=True)
                for i, r in enumerate(ranked):
                    score = r.get("adj_composite", r.get("composite",0))
                    rank  = r.get("pct_rank", 50)
                    gem   = " 💎" if r["ticker"] in gem_tickers else ""
                    bg    = f"rgba(255,255,255,.02)" if i%2==0 else "rgba(255,255,255,.008)"
                    st.markdown(
                        f'<div style="display:grid;grid-template-columns:70px 1fr 54px 54px 70px;'
                        f'gap:6px;padding:10px 12px;background:{bg};'
                        f'border-left:1px solid rgba(255,255,255,.04);border-right:1px solid rgba(255,255,255,.04);'
                        f'border-bottom:1px solid rgba(255,255,255,.04);align-items:center;">'
                        f'<div style="font-family:Syne,sans-serif;font-size:15px;font-weight:800;color:#e2e8f0;">{r["ticker"]}{gem}</div>'
                        f'<div style="font-size:11px;color:#475569;">{r.get("sector","")[:13]}</div>'
                        f'<div style="font-family:DM Mono,monospace;font-size:16px;color:{color};font-weight:700;">{score:.0f}</div>'
                        f'<div style="font-size:12px;color:#334155;">{rank:.0f}th</div>'
                        f'<div><span style="font-size:10px;font-weight:700;color:{act_c};background:{act_bg};'
                        f'border:1px solid {act_c}44;padding:2px 8px;border-radius:3px;">{action_lbl}</span></div>'
                        f'</div>',
                        unsafe_allow_html=True)
                st.markdown(
                    f'<div style="padding:6px 12px;background:#050a0f;border:1px solid rgba(255,255,255,.07);'
                    f'border-radius:0 0 6px 6px;font-size:10px;color:#334155;">'
                    f'{count} total signals in universe</div>',
                    unsafe_allow_html=True)

    # ── TAB 2: FULL UNIVERSE ───────────────────────────────────────────────────
    with scr_tab2:
        fc1, fc2, fc3, fc4, fc5 = st.columns([2,2,2,1,1])
        with fc1:
            filter_sec = st.selectbox("Sector", ["All"]+sorted(set(SECTORS.values())), key="f_sec")
        with fc2:
            filter_act = st.selectbox("Action", ["All","BUY","HOLD","SELL"], key="f_act")
        with fc3:
            filter_sig = st.selectbox("Signal Strength", ["All","STRONG ALIGN","HIGH ALIGN","MODERATE","LOW ALIGN","WEAK/NEG"], key="f_sig")
        with fc4:
            st.markdown('<div style="height:28px;"></div>', unsafe_allow_html=True)
            if st.button("🔄 Rescan", key="rescan"):
                st.session_state.scan_results = None
                st.rerun()
        with fc5:
            st.markdown('<div style="height:28px;"></div>', unsafe_allow_html=True)
            if st.button("⚡ Live Refresh", key="live_refresh"):
                st.session_state.live_refresh_running = True
                st.rerun()

        # ── Live Refresh Pipeline ──────────────────────────────────────────────
        if st.session_state.get("live_refresh_running"):
            st.markdown("""
            <div style="background:rgba(0,255,135,.04);border:1px solid rgba(0,255,135,.2);
                 border-radius:8px;padding:16px 20px;margin:12px 0;">
              <div style="font-family:Syne,sans-serif;font-size:13px;font-weight:700;
                   color:#00ff87;letter-spacing:.08em;margin-bottom:6px;">
                ⚡ LIVE DATA REFRESH
              </div>
              <div style="font-size:12px;color:#64748b;margin-bottom:12px;">
                Fetching live fundamentals from market data for all 963 tickers.
                This runs once per day and takes 3–4 minutes. All users benefit from the result.
              </div>
            </div>
            """, unsafe_allow_html=True)

            progress_bar  = st.progress(0, text="Starting live data refresh...")
            status_text   = st.empty()

            try:
                from data_refresh import fetch_ticker_fundamentals, write_fundamentals_cache
                from data_refresh import write_signal_snapshot
                from universe_data import SECTORS as ALL_SECTORS, FUNDAMENTALS
                import time as _time

                tickers    = list(ALL_SECTORS.keys())
                total      = len(tickers)
                live_data  = {}
                static_ct  = 0

                for i, ticker in enumerate(tickers):
                    pct = int((i / total) * 80)  # first 80% = fetching
                    progress_bar.progress(pct, text=f"Fetching {ticker} ({i+1}/{total})...")

                    data = fetch_ticker_fundamentals(ticker)
                    if data:
                        static_f = FUNDAMENTALS.get(ticker, {})
                        live_data[ticker] = {**static_f, **data}
                    else:
                        live_data[ticker] = FUNDAMENTALS.get(ticker, {})
                        static_ct += 1

                    _time.sleep(0.25)

                status_text.markdown(
                    '<div style="font-size:12px;color:#64748b;">Writing to cache...</div>',
                    unsafe_allow_html=True)
                progress_bar.progress(82, text="Writing fundamentals to Supabase...")
                write_fundamentals_cache(live_data)

                # Score with live data
                progress_bar.progress(86, text="Scoring universe with live data...")
                from model_engine import score_stock, apply_macro_overlay, fetch_macro_overlay
                scores = []
                for i, ticker in enumerate(tickers):
                    f         = live_data.get(ticker, {})
                    vol_ratio = f.get("vol_ratio")
                    s         = score_stock(ticker, [], live_fundamentals=f, vol_ratio=vol_ratio)
                    s["has_live_price"] = bool(f.get("price"))
                    scores.append(s)

                composites = [s["composite"] for s in scores]
                for s in scores:
                    rank = sum(1 for c in composites if c <= s["composite"]) / len(composites) * 100
                    s["pct_rank"] = round(rank, 1)
                scores.sort(key=lambda x: x["composite"], reverse=True)

                progress_bar.progress(93, text="Applying macro overlay...")
                macro  = fetch_macro_overlay()
                scored = apply_macro_overlay(scores, macro)

                progress_bar.progress(97, text="Saving signal snapshot...")
                write_signal_snapshot(scored)

                st.session_state.scan_results          = scored
                st.session_state.macro_data            = macro
                st.session_state.live_refresh_running  = False

                progress_bar.progress(100, text="✓ Live refresh complete!")
                live_ct = total - static_ct
                st.success(f"✓ Refreshed {live_ct} tickers live · {static_ct} used model estimates · Macro: {macro.get('regime','—')} ({macro.get('source','—')})")
                _time.sleep(1.5)
                st.rerun()

            except Exception as e:
                st.session_state.live_refresh_running = False
                st.error(f"Live refresh failed: {e}")
                st.rerun()


        filtered = results
        if filter_sig != "All": filtered = [r for r in filtered if r["signal"]==filter_sig]
        if filter_sec != "All": filtered = [r for r in filtered if r["sector"]==filter_sec]
        if filter_act != "All":
            filtered = [r for r in filtered if r.get("adj_action",r.get("action"))==filter_act]

        st.markdown(
            f'<div style="font-family:DM Mono,monospace;font-size:10px;color:#334155;'
            f'letter-spacing:.1em;margin:8px 0 12px;">{len(filtered)} STOCKS · 💎 = HIDDEN GEM</div>',
            unsafe_allow_html=True)
        for r in filtered:
            st.markdown(factor_panel_html(r, r["ticker"] in gem_tickers), unsafe_allow_html=True)

    # ── TAB 3: SECTOR BREAKDOWN ────────────────────────────────────────────────
    with scr_tab3:
        sector_counts = {}
        for r in results:
            sec = r.get("sector","Other")
            act = r.get("adj_action", r.get("action","HOLD"))
            if sec not in sector_counts:
                sector_counts[sec] = {"BUY":0,"HOLD":0,"SELL":0}
            sector_counts[sec][act] = sector_counts[sec].get(act,0)+1

        st.markdown('<div style="font-family:DM Mono,monospace;font-size:11px;color:#475569;letter-spacing:.1em;margin:16px 0 10px;">SIGNAL BREAKDOWN BY SECTOR</div>', unsafe_allow_html=True)
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
                f'<div style="font-size:12px;color:#475569;width:130px;flex-shrink:0;">'
                f'<span style="color:#00ff87;">{b} BUY</span> '
                f'<span style="color:#fbbf24;">{h} HOLD</span> '
                f'<span style="color:#ef4444;">{s} SELL</span>'
                f'</div></div>',
                unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

def page_gems():
    st.markdown("""
    <div style="padding:32px;">
      <h1 style="font-family:'Syne',sans-serif;font-size:28px;font-weight:800;">
        💎 Hidden Gems
      </h1>
      <p style="color:#475569;margin-top:4px;font-size:13px;">
        Mid-cap stocks with strong factor alignment and low analyst coverage.
        Under the radar. Not in every portfolio.
      </p>
    </div>
    """, unsafe_allow_html=True)

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
        _, c, _ = st.columns([1,2,1])
        with c:
            if st.button("Join Free — First 50 Spots Get Full Access", key="gems_upgrade"):
                st.info("Founding member upgrades coming soon — you're on the list!")
        return

    if st.session_state.scan_results is None:
        st.session_state.scan_results = run_full_scan(use_live_prices=False)

    gems = detect_hidden_gems(st.session_state.scan_results)
    st.markdown(DISCLAIMER, unsafe_allow_html=True)

    if not gems:
        st.markdown('<div style="padding:0 32px;"><div style="color:#475569;padding:40px;text-align:center;">No hidden gems detected in current scan.</div></div>', unsafe_allow_html=True)
        return

    st.markdown(f'<div style="padding:0 32px;font-size:13px;color:#475569;margin-bottom:16px;">{len(gems)} hidden gems identified</div>', unsafe_allow_html=True)
    g_cols = st.columns(min(len(gems),3))
    for i, g in enumerate(gems):
        with g_cols[i % 3]:
            sig_c = signal_color(g["signal"])
            st.markdown(f"""
            <div style="background:rgba(0,255,135,.04);border:1px solid rgba(0,255,135,.25);
                 border-radius:8px;padding:24px;margin-bottom:16px;
                 animation:glow 4s ease infinite;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
                <div>
                  <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:#fff;">
                    💎 {g['ticker']}
                  </div>
                  <div style="font-size:11px;color:#475569;margin-top:2px;">{g['sector']}</div>
                </div>
                <div style="text-align:right;">
                  <div style="font-family:'DM Mono',monospace;font-size:28px;font-weight:500;color:#00ff87;">
                    {g['composite']:.0f}
                  </div>
                  <div style="font-size:10px;color:#475569;">composite</div>
                </div>
              </div>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:16px;">
                {(lambda items: ''.join(['<div style="background:rgba(255,255,255,.04);border-radius:4px;padding:8px;"><div style="font-family:DM Mono,monospace;font-size:10px;color:#475569;margin-bottom:2px;">' + n + '</div><div style="font-family:DM Mono,monospace;font-size:16px;font-weight:500;color:#00ff87;">' + v + '</div></div>' for n,v in items]))([("MOMENTUM",f"{g['momentum']:.0f}"),("QUALITY",f"{g['quality']:.0f}"),("VOLUME",f"{g['volume']:.0f}"),("SIGNAL",g['signal'][:8])])}
              </div>
              <div style="border-top:1px solid rgba(0,255,135,.15);padding-top:12px;">
                {''.join([f'<div style="font-size:12px;color:#4ade80;padding:3px 0;">✓ {r}</div>' for r in g.get('gem_reasons',[])])}
              </div>
            </div>
            """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# BACKTEST PAGE
# ══════════════════════════════════════════════════════════════════════════════
def page_backtest():
    bt = BACKTEST_DATA
    st.markdown("""
    <div style="padding:32px 32px 0;">
      <h1 style="font-family:'Syne',sans-serif;font-size:28px;font-weight:800;">Backtest Performance</h1>
      <p style="color:#475569;margin-top:4px;font-size:13px;">5-year conviction buy-and-hold · May 2020 – May 2025 · 6 market regimes · 50 stocks</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div style="padding:0 32px;">', unsafe_allow_html=True)
    st.markdown(DISCLAIMER, unsafe_allow_html=True)

    # Hero numbers
    st.markdown("""
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:24px 0;">
    """, unsafe_allow_html=True)
    hero_cols = st.columns(4)
    heroes = [
        (hero_cols[0],"5-Yr Total Return",f"+{bt['model_total_ret']:.1f}%",f"$100K → ${bt['model_final_100k']:,}","#00ff87","qe-card-green"),
        (hero_cols[1],"SPY Same Period",  f"+{bt['spy_total_ret']:.1f}%",  f"$100K → ${bt['spy_final_100k']:,}","#fbbf24",""),
        (hero_cols[2],"Model CAGR",       f"+{bt['model_cagr']:.1f}%",    f"vs SPY +{bt['spy_cagr']:.1f}% CAGR","#00ff87",""),
        (hero_cols[3],"Advantage vs SPY", f"+${bt['model_advantage_usd']:,}","on $100,000 invested","#00ff87",""),
    ]
    for col,label,val,sub,color,_ in heroes:
        with col:
            st.markdown(f"""
            <div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);
                 border-radius:6px;padding:20px;{'border-left:2px solid #00ff87;' if color=='#00ff87' else ''}">
              <div style="font-family:'DM Mono',monospace;font-size:11px;color:#64748b;letter-spacing:.1em;margin-bottom:10px;">{label}</div>
              <div style="font-family:'Syne',sans-serif;font-size:34px;font-weight:800;color:{color};line-height:1;">{val}</div>
              <div style="font-size:13px;color:#475569;margin-top:8px;">{sub}</div>
            </div>
            """, unsafe_allow_html=True)

    # Risk metrics
    st.markdown('<div style="height:16px;"></div>', unsafe_allow_html=True)
    risk_cols = st.columns(6)
    risk_data = [
        ("Sharpe","1.512",">1.0 excellent"),
        ("Sortino","2.519",">1.5 strong"),
        ("Info Ratio","1.746",">0.5 signal"),
        ("Max DD","-4.8%","SPY -18.2%"),
        ("Win Rate","83.3%","5 of 6 regimes"),
        ("CAGR Alpha","+27.3pp","/yr vs index"),
    ]
    for col,(label,val,sub) in zip(risk_cols,risk_data):
        with col:
            st.markdown(
                f'<div style="background:rgba(0,255,135,.04);border:1px solid rgba(0,255,135,.12);'
                f'border-radius:6px;padding:16px;text-align:center;">'
                f'<div style="font-family:DM Mono,monospace;font-size:11px;color:#475569;letter-spacing:.1em;margin-bottom:8px;">{label}</div>'
                f'<div style="font-family:Syne,sans-serif;font-size:26px;font-weight:800;color:#00ff87;">{val}</div>'
                f'<div style="font-size:12px;color:#64748b;margin-top:6px;">{sub}</div>'
                f'</div>',
                unsafe_allow_html=True)

    # Growth chart — Chart.js for full styling control
    import streamlit.components.v1 as _components
    st.markdown('<div style="height:24px;"></div>', unsafe_allow_html=True)
    st.markdown('<div style="font-family:\'DM Mono\',monospace;font-size:11px;color:#475569;letter-spacing:.1em;margin-bottom:8px;">GROWTH OF $100,000 — MAY 2020 TO MAY 2025</div>', unsafe_allow_html=True)
    labels   = bt["growth_labels"]
    qntm_pts = bt["growth_model"]
    spy_pts  = bt["growth_spy"]
    chart_html = f"""<!DOCTYPE html><html>
<head><script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script></head>
<body style="margin:0;background:#0a0b14;padding:0 0 8px;">
<canvas id="gc" style="width:100%;"></canvas>
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
        backgroundColor: 'rgba(212,168,67,0.08)',
        borderWidth: 2.5,
        pointBackgroundColor: '#d4a843',
        pointRadius: 4,
        pointHoverRadius: 7,
        fill: true,
        tension: 0.35,
      }},
      {{
        label: 'S&P 500 (SPY)',
        data: spy,
        borderColor: 'rgba(100,116,139,0.8)',
        backgroundColor: 'rgba(100,116,139,0.04)',
        borderWidth: 1.5,
        pointBackgroundColor: '#64748b',
        pointRadius: 3,
        pointHoverRadius: 5,
        fill: true,
        tension: 0.35,
        borderDash: [4,3],
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
        grid: {{ color: 'rgba(255,255,255,0.04)', drawBorder: false }},
        ticks: {{ color: '#475569', font: {{ family: 'DM Mono, monospace', size: 11 }} }},
        border: {{ color: 'rgba(255,255,255,0.06)' }},
      }},
      y: {{
        grid: {{ color: 'rgba(255,255,255,0.04)', drawBorder: false }},
        ticks: {{
          color: '#475569',
          font: {{ family: 'DM Mono, monospace', size: 11 }},
          callback: v => '$' + (v/1000).toFixed(0) + 'K',
        }},
        border: {{ color: 'rgba(255,255,255,0.06)' }},
      }}
    }}
  }}
}});
// Custom legend
const c = document.createElement('div');
c.style = 'display:flex;gap:20px;padding:8px 0 0 8px;';
c.innerHTML = `
  <span style="display:flex;align-items:center;gap:6px;font-family:DM Mono,monospace;font-size:11px;color:#d4a843;">
    <span style="width:18px;height:2.5px;background:#d4a843;display:inline-block;border-radius:2px;"></span>
    QNTM Model
  </span>
  <span style="display:flex;align-items:center;gap:6px;font-family:DM Mono,monospace;font-size:11px;color:#64748b;">
    <span style="width:18px;height:1.5px;background:#64748b;display:inline-block;border-radius:2px;opacity:0.7;"></span>
    S&P 500 (SPY)
  </span>`;
document.body.prepend(c);
</script>
</body></html>"""
    _components.html(chart_html, height=340)

    # ── Macro Overlay Attribution Section ─────────────────────────────────────
    st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)
    st.markdown("""
    <div style="font-family:'DM Mono',monospace;font-size:11px;color:#d4a843;
         letter-spacing:.1em;margin:20px 0 12px;">
      ⚡ MACRO OVERLAY ATTRIBUTION — PROPER BACKTEST (Q2 2020 – Q2 2025)
    </div>
    <div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);
         border-radius:6px;padding:14px 18px;margin-bottom:14px;font-size:12px;color:#475569;line-height:1.7;">
      Methodology: quarterly equal-weight BUY signals scored by the model, measured against
      real historical stock returns (Yahoo Finance / Macrotrends). Macro regime classifications
      use verified historical VIX (CBOE), 10Y–2Y spread (FRED), and Federal Reserve press releases.
      Universe members without individual price data use sector-beta estimates vs SPY.
    </div>
    """, unsafe_allow_html=True)

    mac_cols = st.columns(4)
    mac_stats = [
        ("75/25 Blended Return",f"+{bt['macro_cumulative_return']:.1f}%",f"${bt['macro_final_100k']:,} from $100K","#d4a843"),
        ("Pure Quant Return",f"+{bt['pure_quant_cumulative']:.1f}%","No macro overlay","#94a3b8"),
        ("Blended vs SPY",f"+{bt['blended_vs_spy_pp']:.0f}pp","Cumulative outperformance","#1D9E75"),
        ("Macro: Drawdown Saved",f"-{bt['macro_drawdown_improvement_pp']:.1f}pp","vs pure quant max DD","#1D9E75"),
    ]
    for col,(label,val,sub,color) in zip(mac_cols,mac_stats):
        with col:
            st.markdown(f"""
            <div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);
                 border-top:2px solid {color};border-radius:6px;padding:16px;text-align:center;">
              <div style="font-family:'DM Mono',monospace;font-size:11px;color:#64748b;
                   letter-spacing:.1em;margin-bottom:10px;">{label}</div>
              <div style="font-family:'Syne',sans-serif;font-size:26px;font-weight:800;
                   color:{color};line-height:1;">{val}</div>
              <div style="font-size:13px;color:#475569;margin-top:8px;">{sub}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown('<div style="height:12px;"></div>', unsafe_allow_html=True)

    # Honest comparison table
    st.markdown("""
    <div style="font-family:'DM Mono',monospace;font-size:11px;color:#475569;
         letter-spacing:.1em;margin:8px 0 8px;">SIDE-BY-SIDE: BLENDED vs PURE QUANT vs SPY</div>
    """, unsafe_allow_html=True)

    comp_cols = st.columns(3)
    comparison = [
        ("75/25 Blended","#d4a843",
         bt['macro_cumulative_return'], bt['macro_annualized_return'],
         bt['macro_sharpe'], bt['macro_sortino'], bt['macro_max_drawdown'], bt['macro_win_rate']),
        ("Pure Quant (no macro)","#94a3b8",
         bt['pure_quant_cumulative'], bt['pure_quant_annualized'],
         bt['pure_quant_sharpe'], None, bt['pure_quant_max_drawdown'], None),
        ("SPY Benchmark","#475569",
         bt['benchmark_cumulative'], bt['benchmark_annualized'],
         bt['benchmark_sharpe'], None, bt['benchmark_max_drawdown'], None),
    ]
    for col,(name,color,cum,ann,sharpe,sortino,mdd,wr) in zip(comp_cols,comparison):
        with col:
            sortino_row = f'<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.05);"><span style="font-size:11px;color:#334155;">Sortino</span><span style="font-family:DM Mono,monospace;font-size:12px;color:#94a3b8;">{sortino:.2f}</span></div>' if sortino else ""
            wr_row = f'<div style="display:flex;justify-content:space-between;padding:6px 0;"><span style="font-size:11px;color:#334155;">Win Rate</span><span style="font-family:DM Mono,monospace;font-size:12px;color:#94a3b8;">{wr:.1f}%</span></div>' if wr else ""
            st.markdown(f"""
            <div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);
                 border-left:3px solid {color};border-radius:6px;padding:14px 16px;">
              <div style="font-family:'Syne',sans-serif;font-size:12px;font-weight:700;
                   color:{color};letter-spacing:.08em;margin-bottom:12px;">{name}</div>
              <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.05);">
                <span style="font-size:11px;color:#334155;">Cumulative</span>
                <span style="font-family:'DM Mono',monospace;font-size:12px;color:{color};">+{cum:.1f}%</span>
              </div>
              <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.05);">
                <span style="font-size:11px;color:#334155;">Annualized</span>
                <span style="font-family:'DM Mono',monospace;font-size:12px;color:{color};">+{ann:.1f}%</span>
              </div>
              <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.05);">
                <span style="font-size:11px;color:#334155;">Sharpe</span>
                <span style="font-family:'DM Mono',monospace;font-size:12px;color:#94a3b8;">{sharpe:.2f}</span>
              </div>
              {sortino_row}
              <div style="display:flex;justify-content:space-between;padding:6px 0;{'border-bottom:1px solid rgba(255,255,255,.05);' if wr else ''}">
                <span style="font-size:11px;color:#334155;">Max Drawdown</span>
                <span style="font-family:'DM Mono',monospace;font-size:12px;color:#ef4444;">-{mdd:.1f}%</span>
              </div>
              {wr_row}
            </div>
            """, unsafe_allow_html=True)

    # Regime breakdown
    st.markdown('<div style="height:12px;"></div>', unsafe_allow_html=True)
    st.markdown("""
    <div style="font-family:'DM Mono',monospace;font-size:11px;color:#475569;
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
          <div style="font-family:'DM Mono',monospace;font-size:11px;color:#94a3b8;width:150px;flex-shrink:0;">
            {label}
          </div>
          <div style="display:flex;gap:24px;flex-wrap:wrap;flex:1;">
            <div>
              <div style="font-size:11px;color:#475569;letter-spacing:.08em;margin-bottom:4px;">BLENDED AVG</div>
              <div style="font-family:'DM Mono',monospace;font-size:17px;font-weight:500;color:{b_col};">{b_pct:+.2f}%</div>
            </div>
            <div>
              <div style="font-size:9px;color:#334155;letter-spacing:.08em;margin-bottom:2px;">PURE QUANT</div>
              <div style="font-family:'DM Mono',monospace;font-size:14px;font-weight:500;color:#94a3b8;">{q_pct:+.2f}%</div>
            </div>
            <div>
              <div style="font-size:11px;color:#475569;letter-spacing:.07em;margin-bottom:4px;">SPY AVG</div>
              <div style="font-family:'DM Mono',monospace;font-size:14px;font-weight:500;color:#475569;">{s_pct:+.2f}%</div>
            </div>
            <div>
              <div style="font-size:13px;color:#475569;letter-spacing:.04em;margin-bottom:4px;">BlendED vs SPY</div>
              <div style="font-family:'DM Mono',monospace;font-size:14px;font-weight:500;color:{a_col};">{b_alpha:+.0f} bps</div>
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("""
    <div style="background:rgba(212,168,67,.05);border:1px solid rgba(212,168,67,.15);
         border-radius:6px;padding:14px 18px;margin-top:12px;font-size:12px;color:#64748b;line-height:1.8;">
      <strong style="color:#d4a843;">What the macro overlay actually does:</strong>
      The 75/25 blend trades raw return for risk reduction. Pure quant returned +615.6% but with a
      -42.3% max drawdown. The macro overlay reduced that to -35.5% — a 6.9pp improvement — while
      still delivering +505.9% cumulative (+358.8pp vs SPY). In RISK_OFF regimes (2022 rate shock,
      2025 tariff shock), the overlay dampened exposure to high-beta tech names, reducing but not
      eliminating drawdown. The model underperformed SPY in 2022-Q1 and 2022-Q2 regardless — the
      portfolio was overweight high-multiple growth going into the fastest rate-hike cycle in 40 years.
      <strong style="color:#94a3b8;">That's the honest result. The alpha is real. The 2022 pain is real too.</strong>
    </div>
    """, unsafe_allow_html=True)

    # Regime grid
    st.markdown('<div style="font-family:\'DM Mono\',monospace;font-size:11px;color:#475569;letter-spacing:.1em;margin:24px 0 12px;">REGIME SCORECARD</div>', unsafe_allow_html=True)
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
              <div style="font-family:'DM Mono',monospace;font-size:10px;color:#475569;margin-bottom:4px;">{p['key']}</div>
              <div style="font-family:'Syne',sans-serif;font-size:12px;font-weight:700;color:#94a3b8;margin-bottom:10px;">{p['label']}</div>
              <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:{ic};">{icon}</div>
              <div style="margin-top:8px;">
                <div style="font-family:'DM Mono',monospace;font-size:13px;color:{mc};font-weight:500;">QNTM {p['model_ret']:+.1f}%</div>
                <div style="font-family:'DM Mono',monospace;font-size:11px;color:{sc};margin-top:2px;">SPY {p['spy_ret']:+.1f}%</div>
                <div style="font-size:10px;color:#334155;margin-top:6px;">{p['char']}</div>
              </div>
            </div>
            """, unsafe_allow_html=True)

    # Holdings table — styled HTML matching platform theme
    st.markdown(
        '<div style="font-family:DM Mono,monospace;font-size:11px;color:#475569;'
        'letter-spacing:.1em;margin:32px 0 12px;">12-MONTH CONVICTION PORTFOLIO — ACTUAL POSITIONS &amp; RETURNS</div>',
        unsafe_allow_html=True)

    # Table header
    st.markdown(
        '<div style="display:grid;grid-template-columns:80px 80px 100px 1fr 110px 90px;'
        'gap:8px;padding:10px 16px;background:#050a0f;border-radius:6px 6px 0 0;'
        'border:1px solid rgba(255,255,255,.07);">'
        '<div style="font-size:11px;color:#334155;letter-spacing:.1em;">TICKER</div>'
        '<div style="font-size:11px;color:#334155;letter-spacing:.1em;">ACTION</div>'
        '<div style="font-size:11px;color:#334155;letter-spacing:.1em;">SCORE</div>'
        '<div style="font-size:11px;color:#334155;letter-spacing:.1em;">HOLD PERIOD</div>'
        '<div style="font-size:11px;color:#334155;letter-spacing:.1em;">12M RETURN</div>'
        '<div style="font-size:11px;color:#334155;letter-spacing:.1em;">RESULT</div>'
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
            f'<div><span style="font-size:11px;font-weight:700;color:{act_c};'
            f'background:{act_c}18;border:1px solid {act_c}44;padding:2px 8px;border-radius:3px;">'
            f'{arrow} {act}</span></div>'
            f'<div style="font-family:DM Mono,monospace;font-size:14px;color:{act_c};font-weight:600;">{h["signal"]}</div>'
            f'<div style="font-size:13px;color:#64748b;">{h["held"]}</div>'
            f'<div style="font-family:DM Mono,monospace;font-size:16px;font-weight:700;color:{ret_c};">{ret:+.1f}%</div>'
            f'<div style="font-size:13px;font-weight:700;color:{result_c};">{result}</div>'
            f'</div>',
            unsafe_allow_html=True)

    st.markdown('<div style="padding:8px 16px;background:#050a0f;border:1px solid rgba(255,255,255,.07);border-radius:0 0 6px 6px;font-size:11px;color:#334155;">Stocks avoided: ' +
                ", ".join([f'{a["ticker"]} ({a["return_pct"]:+.1f}%)' for a in bt["avoided"][:5]]) +
                ' — exited or never entered on signal</div>',
                unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PORTFOLIO PAGE
# ══════════════════════════════════════════════════════════════════════════════
def page_portfolio():
    user = st.session_state.user or {}
    plan = user.get("plan", "free")
    max_h = plan_limit(plan, "max_holdings")
    has_notifs = plan_limit(plan, "notifications")

    st.markdown("""
    <div style="padding:32px 32px 0;">
      <h1 style="font-family:'Syne',sans-serif;font-size:28px;font-weight:800;">My Portfolio</h1>
      <p style="color:#475569;margin-top:4px;font-size:13px;">
        Model signals run against your positions every scan. Signal changes trigger alerts on Pro.
      </p>
    </div>
    """, unsafe_allow_html=True)
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
              <span style="font-size:12px;color:#475569;">Free plan — positions used</span>
              <span style="font-family:'DM Mono',monospace;font-size:12px;color:{bar_c};">
                {n_holdings} / {max_h}
              </span>
            </div>
            <div style="background:rgba(255,255,255,.06);border-radius:3px;height:4px;overflow:hidden;">
              <div style="width:{pct}%;height:100%;background:{bar_c};border-radius:3px;
                   transition:width .3s;"></div>
            </div>
          </div>
          <div style="font-size:11px;color:#334155;flex-shrink:0;">
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
        _, uc, _ = st.columns([4,2,4])
        with uc:
            if st.button("Upgrade to Pro — $29/mo", key="port_upgrade"):
                nav("account")

    st.markdown(DISCLAIMER, unsafe_allow_html=True)

    # ── Check for signal changes (pro users get notifications) ─────────────────
    if holdings and score_map:
        prev_signals = get_signal_snapshot(uid())
        signal_changes = check_and_notify_signal_changes(uid(), plan, score_map, prev_signals)
        save_signal_snapshot(uid(), st.session_state.scan_results)
        if signal_changes:
            for chg in signal_changes:
                if chg["to"] == "SELL":
                    st.markdown(f"""
                    <div style="background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.4);
                         border-radius:6px;padding:12px 16px;margin-bottom:8px;
                         animation:borderAnim 3s ease infinite;">
                      <span style="font-family:'Syne',sans-serif;font-size:12px;font-weight:700;
                            color:#ef4444;letter-spacing:.1em;">▼ EXIT SIGNAL FIRED: {chg['ticker']}</span>
                      <span style="font-size:12px;color:#94a3b8;margin-left:12px;">
                        was {chg['from']} → now SELL
                      </span>
                    </div>
                    """, unsafe_allow_html=True)

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
            f'<span style="font-size:10px;color:#ef4444;">{sc:.0f}</span>'
            f'</span>'
            for tk, sc, sig in exit_signals
        ])
        st.markdown(f"""
        <div style="background:rgba(239,68,68,.07);border:1px solid rgba(239,68,68,.3);
             border-radius:8px;padding:16px 20px;margin-bottom:20px;">
          <div style="font-family:'Syne',sans-serif;font-size:11px;font-weight:700;
               color:#ef4444;letter-spacing:.12em;margin-bottom:10px;">⚠ ACTIVE EXIT SIGNALS</div>
          <div style="display:flex;flex-wrap:wrap;">{ticker_chips}</div>
          <div style="font-size:11px;color:#334155;margin-top:8px;">
            Model score below exit threshold (45). Review these positions.
          </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Add position form ──────────────────────────────────────────────────────
    at_limit = n_holdings >= max_h

    with st.expander("➕ Add Position", expanded=(n_holdings == 0)):
        if at_limit and plan == "free":
            st.markdown("""
            <div style="background:rgba(239,68,68,.06);border:1px solid rgba(239,68,68,.2);
                 border-radius:6px;padding:14px;font-size:13px;color:#ef4444;">
              Free plan limit reached (10 positions). Upgrade to Pro for unlimited holdings.
            </div>
            """, unsafe_allow_html=True)
        else:
            c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 1])
            with c1: new_tk   = st.text_input("Ticker",        key="p_tk",   placeholder="e.g. AAPL")
            with c2: new_sh   = st.number_input("Shares",       key="p_sh",   min_value=0.0, step=1.0, format="%.2f")
            with c3: new_cost = st.number_input("Avg Cost ($)", key="p_cost", min_value=0.0, step=0.01, format="%.2f")
            with c4: new_date = st.date_input("Entry Date",     key="p_date", value=date.today())
            with c5:
                st.markdown('<div style="height:28px;"></div>', unsafe_allow_html=True)
                if st.button("Add", key="p_add", use_container_width=True):
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
                                        f"BUY signal active: {tk_clean}",
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
        <div style="text-align:center;padding:64px 0;color:#334155;">
          <div style="font-size:48px;margin-bottom:16px;">📊</div>
          <div style="font-family:'Syne',sans-serif;font-size:20px;font-weight:700;color:#475569;">
            No positions yet
          </div>
          <div style="font-size:13px;margin-top:8px;color:#334155;">
            Add your first position above — the model will score it immediately
          </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        return

    # ── Portfolio summary strip ────────────────────────────────────────────────
    port_buys  = sum(1 for h in holdings if score_map.get(h["ticker"],{}).get("adj_action", score_map.get(h["ticker"],{}).get("action")) == "BUY")
    port_holds = sum(1 for h in holdings if score_map.get(h["ticker"],{}).get("adj_action", score_map.get(h["ticker"],{}).get("action")) == "HOLD")
    port_sells = sum(1 for h in holdings if score_map.get(h["ticker"],{}).get("adj_action", score_map.get(h["ticker"],{}).get("action")) == "SELL")
    port_na    = n_holdings - port_buys - port_holds - port_sells

    s1, s2, s3, s4 = st.columns(4)
    port_summary_data = [
        (s1, "▲ BUY Signals",     port_buys,  "#00ff87"),
        (s2, "─ Hold",            port_holds, "#fbbf24"),
        (s3, "▼ Sell / Exit",     port_sells, "#ef4444"),
        (s4, "Outside Universe",  port_na,    "#475569"),
    ]
    for col, label, val, color in port_summary_data:
        with col:
            st.markdown(
                '<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);'
                'border-radius:6px;padding:16px;margin-bottom:16px;">'
                f'<div style="font-size:11px;color:#475569;letter-spacing:.08em;margin-bottom:8px;font-family:DM Mono,monospace;">{label}</div>'
                f'<div style="font-size:36px;font-weight:800;color:{color};font-family:Syne,sans-serif;line-height:1;">{int(val)}</div>'
                f'<div style="font-size:12px;color:#334155;margin-top:4px;">position{"s" if val!=1 else ""}</div>'
                '</div>',
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

        # Period toggle row
        st.markdown('<div style="font-family:DM Mono,monospace;font-size:11px;color:#475569;letter-spacing:.1em;margin-bottom:8px;">PORTFOLIO VALUE — SELECT PERIOD</div>', unsafe_allow_html=True)
        period_btn_cols = st.columns(len(PERIOD_DATA))
        for col, (pkey, plbl, pdays) in zip(period_btn_cols, PERIOD_DATA):
            with col:
                if st.button(pkey, key=f"pp_{pkey}", use_container_width=True):
                    st.session_state.port_period = pkey
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

        vc1, vc2, vc3, vc4 = st.columns([3,2,2,2])
        for col, label, value_str, color, sub in [
            (vc1, "TOTAL VALUE",        f"${total_current:,.0f}",              "#e2e8f0", f"Cost basis ${total_cost_basis:,.0f}"),
            (vc2, "$ CHANGE",           f"{arrow} ${abs(total_change):,.0f}",  change_c,  plbl),
            (vc3, "% CHANGE",           f"{arrow} {abs(chg_pct):.1f}%",        change_c,  plbl),
        ]:
            with col:
                st.markdown(
                    f'<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);'
                    f'border-left:3px solid {color};border-radius:8px;padding:16px 18px;margin-bottom:4px;">'
                    f'<div style="font-size:12px;color:#475569;letter-spacing:.08em;margin-bottom:6px;">{label}</div>'
                    f'<div style="font-family:Syne,sans-serif;font-size:32px;font-weight:800;color:{color};line-height:1;">{value_str}</div>'
                    f'<div style="font-size:12px;color:#475569;margin-top:5px;">{sub}</div>'
                    f'</div>',
                    unsafe_allow_html=True)

        with vc4:
            b2    = sum(1 for h in holdings if (score_map.get(h["ticker"],{}) or {}).get("adj_action",(score_map.get(h["ticker"],{}) or {}).get("action","N/A"))=="BUY")
            hold2 = sum(1 for h in holdings if (score_map.get(h["ticker"],{}) or {}).get("adj_action",(score_map.get(h["ticker"],{}) or {}).get("action","N/A"))=="HOLD")
            sell2 = len(holdings) - b2 - hold2
            st.markdown(
                f'<div style="background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);'
                f'border-radius:8px;padding:16px 18px;margin-bottom:4px;">'
                f'<div style="font-size:12px;color:#475569;letter-spacing:.08em;margin-bottom:8px;">SIGNAL MIX</div>'
                f'<div style="display:flex;gap:16px;">'
                f'<div><div style="font-size:26px;font-weight:800;color:#00ff87;font-family:Syne,sans-serif;">{b2}</div>'
                f'<div style="font-size:12px;color:#475569;">BUY</div></div>'
                f'<div><div style="font-size:26px;font-weight:800;color:#fbbf24;font-family:Syne,sans-serif;">{hold2}</div>'
                f'<div style="font-size:12px;color:#475569;">HOLD</div></div>'
                f'<div><div style="font-size:26px;font-weight:800;color:#ef4444;font-family:Syne,sans-serif;">{sell2}</div>'
                f'<div style="font-size:12px;color:#475569;">SELL</div></div>'
                f'</div></div>',
                unsafe_allow_html=True)

        st.markdown('<div style="font-size:11px;color:#334155;margin:4px 0 20px;">Returns estimated from model signal rates. Add live price integration for real-time values.</div>', unsafe_allow_html=True)

    # ── Holdings cards ─────────────────────────────────────────────────────────
    st.markdown('<div style="font-family:DM Mono,monospace;font-size:11px;color:#334155;letter-spacing:.1em;margin-bottom:12px;">YOUR POSITIONS — MODEL SIGNALS APPLIED</div>', unsafe_allow_html=True)

    for h in holdings:
        tk     = h["ticker"]
        sc     = score_map.get(tk)
        cost   = float(h.get("avg_cost", 0) or 0)
        shares = float(h.get("shares", 0) or 0)
        entry  = h.get("entry_date", "")

        if sc:
            comp   = sc.get("adj_composite", sc.get("composite", 50))
            act    = sc.get("adj_action", sc.get("action", "HOLD"))
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
                f'<div style="flex:1;min-width:100px;">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">'
                f'{lbl}'
                f'<div style="font-family:DM Mono,monospace;font-size:16px;color:{c};font-weight:700;">{v:.0f}</div>'
                f'</div>'
                f'<div style="background:rgba(255,255,255,.05);border-radius:3px;height:7px;overflow:hidden;">'
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
        # Pre-compute display strings to avoid f-string format spec crashes
        quant_disp = f"{sc['composite']:.1f}" if sc and sc.get('composite') is not None else "—"
        delta_disp = delta_str if sc else "—"
        sig_disp   = (sig[:10] if sig else "—") if sig else "—"

        st.markdown(f"""
        <div style="background:{act_bg};border:{act_brd};border-radius:10px;padding:20px;margin-bottom:10px;">
          <!-- Header -->
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;">
            <div>
              <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
                <span style="font-family:'Syne',sans-serif;font-size:26px;font-weight:800;color:#e2e8f0;">{tk}</span>
                <span style="font-family:'Syne',sans-serif;font-size:11px;font-weight:700;color:{act_c};
                      background:{act_c}18;border:1px solid {act_c}44;padding:3px 10px;border-radius:3px;
                      letter-spacing:.1em;">{arrow} {act}</span>
                <span style="font-size:13px;color:#475569;">{sector}</span>
              </div>
              <div style="font-size:11px;color:#475569;">{driver}</div>
            </div>
            <div style="text-align:right;">
              <div style="font-family:'DM Mono',monospace;font-size:36px;font-weight:700;color:{act_c};">{comp:.0f}</div>
              <div style="font-size:12px;color:#475569;margin-top:2px;">blended score</div>
              <div style="font-size:11px;color:{delta_c};margin-top:2px;">macro {delta_str}</div>
            </div>
          </div>
          <!-- Position details row -->
          <div style="display:flex;gap:16px;margin-bottom:14px;flex-wrap:wrap;">
            <div style="font-size:14px;color:#64748b;">
              {shares:.2f} shares
            </div>
            {'<div style="font-size:14px;color:#475569;">avg cost <span style="color:#94a3b8;font-family:DM Mono,monospace;">${:.2f}</span></div>'.format(cost) if cost > 0 else ''}
            {'<div style="font-size:14px;color:#475569;">est. value <span style="color:#94a3b8;font-family:DM Mono,monospace;">${:,.0f}</span></div>'.format(cost*shares) if cost > 0 and shares > 0 else ''}
            {'<div style="font-size:14px;color:#475569;">entry <span style="color:#94a3b8;font-family:DM Mono,monospace;">' + str(entry)[:10] + '</span></div>' if entry else ''}
          </div>
          <!-- Pillar bars -->
          <div style="display:flex;gap:8px;margin-bottom:12px;">
            {pillar_html}
          </div>
          <!-- Score chips -->
          <div style="display:flex;gap:6px;padding-top:10px;border-top:1px solid rgba(255,255,255,.05);flex-wrap:wrap;">
            <div style="background:rgba(255,255,255,.04);border-radius:4px;padding:6px 10px;flex:1;min-width:70px;">
              <div style="font-size:13px;color:#475569;letter-spacing:.06em;margin-bottom:4px;">Quant Score</div>
              <div style="font-family:'DM Mono',monospace;font-size:18px;color:#94a3b8;">{quant_disp}</div>
            </div>
            <div style="background:rgba(255,255,255,.04);border-radius:4px;padding:6px 10px;flex:1;min-width:70px;">
              <div style="font-size:13px;color:#475569;letter-spacing:.04em;margin-bottom:4px;">Macro Adj</div>
              <div style="font-family:'DM Mono',monospace;font-size:18px;color:{delta_c};">{delta_disp}</div>
            </div>
            <div style="background:rgba(255,255,255,.04);border-radius:4px;padding:6px 10px;flex:1;min-width:70px;">
              <div style="font-size:13px;color:#475569;letter-spacing:.04em;margin-bottom:4px;">Blend</div>
              <div style="font-family:'DM Mono',monospace;font-size:18px;color:#d4a843;">75/25</div>
            </div>
            <div style="background:rgba(255,255,255,.04);border-radius:4px;padding:6px 10px;flex:1;min-width:70px;">
              <div style="font-size:13px;color:#475569;letter-spacing:.04em;margin-bottom:4px;">Signal</div>
              <div style="font-family:'DM Mono',monospace;font-size:15px;color:#94a3b8;">{sig_disp}</div>
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        col_del, col_edit, _ = st.columns([1, 1, 6])
        with col_del:
            if st.button(f"Remove", key=f"del_{tk}"):
                delete_holding(uid(), tk)
                st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# ALERTS PAGE
# ══════════════════════════════════════════════════════════════════════════════
def page_alerts():
    user = st.session_state.user or {}
    plan = user.get("plan", "free")
    has_alerts = plan_limit(plan, "notifications")

    st.markdown("""
    <div style="padding:32px 32px 0;">
      <h1 style="font-family:'Syne',sans-serif;font-size:28px;font-weight:800;">🔔 Alerts</h1>
      <p style="color:#475569;margin-top:4px;font-size:13px;">
        Signal changes on your holdings and market-wide macro events
      </p>
    </div>
    """, unsafe_allow_html=True)
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
              <div style="font-size:11px;color:#94a3b8;line-height:1.5;">BUY / SELL<br>signal alerts</div>
            </div>
            <div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);
                 border-radius:6px;padding:14px 10px;">
              <div style="font-size:20px;margin-bottom:6px;">⚡</div>
              <div style="font-size:11px;color:#94a3b8;line-height:1.5;">Macro regime<br>change alerts</div>
            </div>
            <div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);
                 border-radius:6px;padding:14px 10px;">
              <div style="font-size:20px;margin-bottom:6px;">💎</div>
              <div style="font-size:11px;color:#94a3b8;line-height:1.5;">Hidden gem<br>detection</div>
            </div>
          </div>
          <div style="font-family:'DM Mono',monospace;font-size:11px;color:#d4a843;margin-bottom:8px;">
            PRO PLAN — $29/MO · FOUNDING MEMBER — FREE (FIRST 50)
          </div>
        </div>
        """, unsafe_allow_html=True)
        _, cc, _ = st.columns([1, 2, 1])
        with cc:
            if st.button("Upgrade to Pro — Unlock Alerts", key="alerts_upgrade", use_container_width=True):
                nav("account")
        st.markdown('</div>', unsafe_allow_html=True)
        return

    # ── Pro user — show notifications ──────────────────────────────────────────
    notifs = get_notifications(uid())
    unread = sum(1 for n in notifs if not n.get("is_read"))

    # Action bar
    ac1, ac2, ac3 = st.columns([2, 1, 1])
    with ac1:
        st.markdown(f"""
        <div style="padding:8px 0;font-size:13px;color:#475569;">
          {len(notifs)} notifications
          {'· <span style="color:#00ff87;">' + str(unread) + ' unread</span>' if unread else ''}
        </div>
        """, unsafe_allow_html=True)
    with ac2:
        if unread > 0 and st.button("Mark All Read", key="mark_read"):
            mark_notifications_read(uid())
            st.rerun()
    with ac3:
        filter_type = st.selectbox("Filter", ["All","BUY","SELL","Macro","Gems"], key="notif_filter", label_visibility="collapsed")

    st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)

    if not notifs:
        st.markdown("""
        <div style="text-align:center;padding:64px;color:#334155;">
          <div style="font-size:40px;margin-bottom:16px;">🔔</div>
          <div style="font-family:'Syne',sans-serif;font-size:18px;font-weight:700;color:#475569;">
            No alerts yet
          </div>
          <div style="font-size:13px;margin-top:8px;">
            Add holdings in Portfolio — the model will alert you when signals change
          </div>
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
            "BUY": "buy_signal",
            "SELL": "sell_signal",
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
                      {n.get('title','')}
                    </div>
                    <div style="font-size:12px;color:#475569;margin-top:3px;line-height:1.5;">
                      {n.get('body','')}
                    </div>
                  </div>
                </div>
                <div style="font-family:'DM Mono',monospace;font-size:10px;color:#334155;
                     flex-shrink:0;white-space:nowrap;">{created}</div>
              </div>
            </div>
            """, unsafe_allow_html=True)

        if shown == 0:
            st.markdown(f'<div style="color:#334155;padding:24px;text-align:center;font-size:13px;">No {filter_type.lower()} alerts</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# ACCOUNT PAGE
# ══════════════════════════════════════════════════════════════════════════════
def page_account():
    from db import disable_mfa, upgrade_plan, plan_limit
    user = st.session_state.user or {}
    plan = user.get("plan", "free")

    st.markdown("""
    <div style="padding:32px 32px 0;">
      <h1 style="font-family:'Syne',sans-serif;font-size:28px;font-weight:800;">Account</h1>
    </div>
    """, unsafe_allow_html=True)
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
              <span style="font-size:11px;color:#334155;letter-spacing:.1em;">PLAN </span>
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
                <div style="font-size:12px;color:#475569;margin-top:2px;">
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
              <div style="font-size:12px;color:#64748b;">
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
          <div style="font-family:'DM Mono',monospace;font-size:10px;color:#475569;
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
          <div style="font-family:'DM Mono',monospace;font-size:9px;color:#475569;
               letter-spacing:.12em;margin-bottom:8px;">CURRENT PLAN</div>
          <div style="font-family:'Syne',sans-serif;font-size:30px;font-weight:800;
               color:{plan_color};">{plan.upper()}</div>
          <div style="font-size:13px;color:#475569;margin-top:6px;">
            {"Unlimited holdings · Hidden Gems · Signal alerts · Email notifications"
             if plan in ('pro','institutional')
             else "10 holdings · Market screener · BUY/HOLD/SELL signals · 5-yr backtest"}
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
                <div style="font-size:11px;color:#475569;margin-bottom:18px;">forever</div>
                <div style="font-size:13px;color:#475569;line-height:2;">
                  ✓ Full market screener (61 stocks)<br>
                  ✓ BUY / HOLD / SELL signals<br>
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
                     font-family:'Syne',sans-serif;font-size:10px;font-weight:700;
                     letter-spacing:.1em;padding:3px 12px;border-radius:3px;">RECOMMENDED</div>
                <div style="font-family:'Syne',sans-serif;font-size:13px;font-weight:700;
                     color:#d4a843;letter-spacing:.08em;margin-bottom:6px;">FOUNDING MEMBER</div>
                <div style="font-family:'Syne',sans-serif;font-size:36px;font-weight:800;
                     color:#d4a843;line-height:1;margin-bottom:4px;">$0</div>
                <div style="font-size:11px;color:#94a3b8;margin-bottom:18px;">
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

            _, bc, _ = st.columns([1, 2, 1])
            with bc:
                if st.button("Join Founding Members — Claim Free Spot", key="upgrade_btn", use_container_width=True):
                    ok = upgrade_plan(uid(), "pro")
                    if ok:
                        st.success("✓ Welcome to Founding Member! Full access is now active — unlimited holdings, Hidden Gems, and signal alerts.")
                        st.balloons()
                        st.rerun()
                    else:
                        st.error("Something went wrong — please try again or contact hello@qntm.app")

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
def page_platform():
    # ── Force MFA setup on first login ─────────────────────────────────────────
    if st.session_state.get("force_mfa_setup"):
        user = st.session_state.user or {}
        mfa  = get_user_mfa(uid())
        if not mfa.get("mfa_enabled"):
            # Show as a clean centered page — no fixed overlays that cover buttons
            st.markdown("<div style='height:8vh'></div>", unsafe_allow_html=True)
            _, mc, _ = st.columns([1, 2, 1])
            with mc:
                st.markdown(
                    "<div style='background:#0d1117;border:1px solid rgba(212,168,67,.4);"
                    "border-radius:12px;padding:36px 40px;text-align:center;'>",
                    unsafe_allow_html=True
                )
                st.markdown("## 🔒 Secure Your Account")
                st.markdown(
                    "QNTM holds your financial data and portfolio positions. "
                    "We **strongly recommend** enabling two-factor authentication before continuing.\n\n"
                    "Takes 60 seconds with Google Authenticator or Authy."
                )
                st.markdown("</div>", unsafe_allow_html=True)
                st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
                b1, b2 = st.columns(2)
                with b1:
                    if st.button("⚡ Enable 2FA Now", key="force_mfa_yes", use_container_width=True):
                        st.session_state.force_mfa_setup = False
                        nav("account")
                        st.session_state.show_mfa_setup = True
                with b2:
                    if st.button("Skip for Now", key="force_mfa_skip", use_container_width=True):
                        st.session_state.force_mfa_setup = False
                        st.rerun()
            return
        else:
            st.session_state.force_mfa_setup = False

            st.session_state.force_mfa_setup = False

    # Auto-refresh every 60 seconds
    st.markdown("""
    <script>
    (function() {
        if (!window._qntm_refresh) {
            window._qntm_refresh = setInterval(function() {
                // Trigger Streamlit rerun by clicking a hidden button
                var btn = window.parent.document.querySelector('[data-testid="stButton"] button');
                if (btn) btn.click();
            }, 60000);
        }
    })();
    </script>
    """, unsafe_allow_html=True)
    # Use Streamlit's built-in auto-rerun
    if "last_refresh" not in st.session_state:
        st.session_state.last_refresh = 0
    import time as _time
    now = int(_time.time())
    if now - st.session_state.last_refresh >= 60:
        st.session_state.last_refresh = now
        st.session_state.scan_results = None  # force rescan
    platform_nav()

    nav_map = {
        "screener":  page_screener,
        "gems":      page_gems,
        "backtest":  page_backtest,
        "portfolio": page_portfolio,
        "alerts":    page_alerts,
        "account":   page_account,
    }
    nav_map.get(st.session_state.nav, page_screener)()

    # Platform footer
    st.markdown("""
    <div style="padding:24px 32px;border-top:1px solid rgba(255,255,255,.05);margin-top:40px;">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
        <div style="font-size:11px;color:#1e2a3a;">
          QNTM · Quantitative research platform · Not investment advice
        </div>
        <div style="font-size:11px;color:#1e2a3a;">
          <a href="#" style="color:#334155;">Privacy</a> ·
          <a href="#" style="color:#334155;">Terms</a> ·
          <a href="#" style="color:#334155;">Disclaimer</a>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)
    cookie_banner()


# ══════════════════════════════════════════════════════════════════════════════
# ROUTER
# ══════════════════════════════════════════════════════════════════════════════
def main():
    # ── Cookie consent gate — must happen before ANYTHING else ────────────────
    if not st.session_state.cookies_accepted:
        page_cookie_consent()
        return   # st.stop() not needed — return exits main() cleanly

    # Handle nav button side effects — re-route if needed
    if st.session_state.page == "landing" and st.session_state.logged_in:
        st.session_state.page = "platform"

    route = st.session_state.page
    if   route == "landing":  page_landing()
    elif route == "auth":     page_auth()
    elif route == "mfa":      page_mfa()
    elif route == "platform": page_platform()
    elif route == "legal":    page_legal(st.session_state.get("legal_doc","privacy"))
    else:                     page_landing()

main()
