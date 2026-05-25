# QNTM Platform — Handoff Summary
*Updated: May 24, 2026 (end of full day session)*

## What It Is
QNTM is a quantitative conviction factor model platform for retail investors. Bloomberg terminal aesthetic, dark theme.

**Deployments:**
- Prod: `qntmmvp.streamlit.app` (main branch)
- Dev v2: `qntm-v2-dev.streamlit.app` (v2 branch) ← **active**
- **GitHub:** `andymcalister/QNTM`

**Standard push:**
```bash
git add app.py && git commit -m "message" && git push origin v2
```

---

## Tech Stack
- **Frontend:** Streamlit (Python), custom HTML/CSS
- **Database:** Supabase (PostgreSQL) at `zqrudkoqhsjsltpefgcl.supabase.co`
- **Auth:** bcrypt + TOTP MFA, HMAC-SHA256 JWT tokens, 30-day localStorage remember-me
- **Intraday cron:** cron-job.org → GitHub `workflow_dispatch` every 30 min market hours (PAT expires May 2027)

---

## Model
- **Universe:** 834 tickers (S&P 500 + Russell 1000)
- **5 Pillars:** Momentum 30%, Quality 25%, Volume 20%, Value 15%, Sentiment 10%
- **Signals:** HIGH ≥60, MODERATE 45–59, LOW <45 (UI) — internally BUY/HOLD/SELL in DB
- **Macro overlay:** 75/25 quant/macro blend
- **Backtest:** +347% adj vs SPY +131% · Sharpe 1.72 · Max DD 6.5% · 85% win rate

---

## CRITICAL ARCHITECTURE RULES

### 1. URL Action Pattern — Use for EVERYTHING interactive
**Never `st.button` + `st.rerun()` in platform pages.** Mobile WebSocket reconnects wipe session.

```python
# All interactive actions use URL params handled in main() router
_url = f"?qnav=screener&uid={uid}&plan={plan}&ck=1&wl_action=add&wl_ticker=AAPL"
st.markdown(f'<a href="{_url}" target="_self" style="...">button</a>', unsafe_allow_html=True)
```

Router handles at top of `main()` before any page renders:
- `wl_action` + `wl_ticker` → watchlist add/remove
- `port_action` + `port_ticker` → portfolio remove
- `port_period` → portfolio period selector
- `sim_rescan=1` → simulator rescan (runs run_full_scan)
- `sim_profile` + `_sp` → simulator profile select
- `sim_add` / `sim_remove` → simulator position add/remove
- `upgrade=pro` → upgrade plan directly
- `upgrade_page=1` → route to page_upgrade
- `qnav=KEY` → platform nav routing

**`st.button` is OK for:** Sign In, Create Account, MFA verify, Add holding, Mark read, MFA setup.

### 2. Helper Functions — Defined at lines 752–780, MUST stay before page functions
```python
_pin_nav(page_key)          # pins nav/page to prevent session drop on widget reruns
_back_btn(href, label)      # styled ghost back button HTML link
_upgrade_url(feature, nav)  # builds upgrade page URL with session params
_cta_gold(label, href)      # gold primary CTA HTML link (line ~1894)
_cta_ghost(label, href)     # ghost secondary CTA HTML link
```

### 3. Session Restore
- Runs before `main()` when `logged_in=False`
- Reads `uid` from query params → `get_user_by_id()` → sets session
- **`get_user_by_id` must be in `from db import (...)` list**
- Falls back to query param `plan=` if DB fails
- Nav recovery: `_n=PAGE` param written on every render, read on reconnect

### 4. scan_results vs sim_data
- `scan_results` cleared every 60s on screener page only
- `sim_data` — dedicated key for simulator, NEVER cleared by timer
- Simulator loads from `signal_log` on first open (spinner), cached in `sim_data`
- Sector enriched from `SECTORS.get(ticker)` after fetch (not in signal_log)

### 5. _pin_nav() on every page function
Every `def page_X()` starts with `_pin_nav("X")` — prevents text input reruns from dropping nav to screener.

---

## signal_log Column Reference
**EXISTS:** `adj_composite, composite, created_at, hidden_gem_reason, id, is_hidden_gem, macro_overlay, momentum, price, quality, sentiment, signal, signal_date, ticker, value, volume`

**DOES NOT EXIST:** `sector`, `adj_action`, `pct_rank`, `score_delta`

**Derive in Python:**
- `sector` → `SECTORS.get(ticker, "Unknown")` from `model_engine`
- `adj_action` → `"BUY" if adj>=60 else "SELL" if adj<45 else "HOLD"`

---

## Free Tier Gating
- **Full Universe:** top 50 results shown, gate banner + gold CTA after
- **Gems, Simulator, Alerts:** full page gate, CTA routes to `page_upgrade`
- **page_upgrade:** shows pricing, "Claim Founding Member" gold CTA → `upgrade=pro` URL action → router upgrades → redirect back
- **When Stripe ready:** replace `upgrade_plan()` in router with Stripe checkout redirect

---

## Upgrade Flow (pre-Stripe)
1. Free user hits gate → sees wall
2. Clicks gold CTA → `?upgrade_page=1&feature=X&return_nav=Y`
3. Router sets `page=upgrade`, `upgrade_feature`, `upgrade_return_nav`
4. `page_upgrade()` renders pricing + "Claim Founding Member Access" gold link
5. Click → `?upgrade=pro&qnav=Y` → router calls `upgrade_plan()` → session updated → redirects to feature

---

## Supabase Tables
`users`, `holdings`, `signal_log`, `notifications`, `backtest_cache`, `fundamentals_cache`, `signal_snapshots`, `model_portfolio_positions`, `user_watchlist`

### user_watchlist
```sql
create table user_watchlist (
  id uuid default gen_random_uuid() primary key,
  user_id text not null, ticker text not null,
  added_at timestamptz default now(), price_at_add numeric,
  unique(user_id, ticker)
);
```

### model_portfolio_positions
- 41 active positions (9 slots open — Energy/Materials capped at 30%)
- $2K/position, 50-stock target, auto-exit score<45, auto-fill nightly+intraday

---

## Page Functions
```python
page_landing()        # Public hero — ticker tape from signal_log, stat cards, pricing
page_auth()           # Sign In / Join Free (custom tab toggle, not st.tabs)
page_mfa()            # TOTP verification
page_upgrade()        # Upgrade to Pro — pricing + confirm CTA (pre-Stripe gate)
page_screener()       # Search + Top 10 + Full Universe + Sector Breakdown
page_watchlist()      # Tracked stocks — trend arrows, conviction alerts, sparklines
page_gems()           # Hidden Gems (Pro gate) — watchlist via URL action
page_backtest()       # Walk-forward backtest results
page_portfolio()      # Holdings P&L — actual yfinance prices, period lookbacks
page_simulator()      # Portfolio Simulator (Pro gate) — loads from signal_log + sim_data
page_model_portfolio()# 50-stock live model portfolio
page_alerts()         # Signal change alerts (Pro gate)
page_account()        # Profile, security, plan upgrade button
page_methodology()    # How QNTM Works
page_platform()       # Container: nav + 60s scan timer + nav_map routing
```

---

## Key Component Functions
- `factor_panel_html(r, is_gem, company_info)` — full score card HTML incl WHY THIS SCORE
- `_build_why_html(r)` — plain-English score explanation (standalone helper, used everywhere)
- `signal_history_chart(ticker, current_score)` — SVG sparkline from signal_log
- `resolve_ticker(query)` — company name → ticker (KNOWN dict + yfinance fallback)
- `_get_supabase()` from `data_refresh` — uses SERVICE_KEY (not anon)

---

## Secrets Required
```toml
SUPABASE_URL = "https://zqrudkoqhsjsltpefgcl.supabase.co"
SUPABASE_ANON_KEY = "..."
SUPABASE_SERVICE_KEY = "..."
ENCRYPTION_KEY = "gvRXtS0L-DqgRu9ieMvt9oxMgPdCChFCsUx-qgyGXd0="
ENVIRONMENT = "dev"   # v2 only
```

---

## Pre-Launch Checklist
- [ ] Fintech lawyer review (Mark) — IAA 1940, disclaimer language, CA DFPI
- [ ] Stripe integration — `STRIPE_SECRET_KEY` + `STRIPE_PRICE_ID_PRO` + webhook
- [ ] Push v2 → main

## Next Session
See **BACKLOG.md** for full prioritized feature list.

**Immediate priorities:**
1. Stripe (unblocks revenue — waiting on lawyer)
2. "What changed today?" delta on score cards (Tier 1 — highest ROI)
3. Daily briefing habit loop (Tier 1)
4. Hero trust fix (Tier 1)
5. Push v2 → main

---

## Session History

### May 24, 2026 (full day)
Major themes: session architecture, URL action pattern throughout, mobile UX, beta readiness.

**Completed:**
- Full mobile layout pass — responsive cards, buttons fit all screens
- Session restore fixed — `get_user_by_id` import, `_n` param reconnect recovery
- URL action pattern — ALL interactive elements (watchlist, portfolio, simulator, upgrade)
- `_pin_nav()` on all platform pages
- WHY THIS SCORE explainability on every stock card
- Conviction sparkline on screener search + full universe (≤20 filtered)
- Watchlist: trend arrows, conviction alerts, remove via URL action
- Portfolio: actual yfinance P&L, period lookbacks capped at entry date
- Portfolio period selector via URL actions (no selectbox rerun)
- Simulator: loads from signal_log automatically, profile via `_sp` param, sector enriched from SECTORS dict
- Free tier gating — 50-stock screener limit, gems/simulator/alerts gates
- `page_upgrade` — dedicated upgrade flow, gold CTA, back button
- BUY/HOLD/SELL → High/Moderate/Low Conviction throughout portfolio
- Live Refresh mentions removed
- All major CTAs → gold HTML links (`_cta_gold`, `_cta_ghost`)
- Back buttons styled consistently (`_back_btn`)
- Landing ticker tape from live signal_log
- Cold registration flow tested and working on mobile
- signal_log column audit — removed `sector`, `adj_action` from all queries

### Earlier May 24 (morning)
- v2 initial build: CSS nav, landing redesign, watchlist feature, model portfolio, methodology page

### Previous Sessions
- v1 fixes, Stack Financial Technologies (folded), structural analyzer
