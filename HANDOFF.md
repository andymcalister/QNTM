# QNTM Platform — Handoff Summary
*Updated: May 24, 2026 (end of day)*

## What It Is
QNTM is a quantitative conviction factor model platform for retail investors. Bloomberg terminal aesthetic, dark theme.

**Deployments:**
- Prod: `qntmmvp.streamlit.app` (main branch)
- Dev v1: `qntm-dev.streamlit.app` (dev branch)
- Dev v2: `qntm-v2-dev.streamlit.app` (v2 branch)
- **GitHub:** `andymcalister/QNTM`

---

## Tech Stack
- **Frontend:** Streamlit (Python), custom HTML/CSS throughout
- **Database:** Supabase (PostgreSQL) at `zqrudkoqhsjsltpefgcl.supabase.co`
- **Auth:** bcrypt + TOTP MFA, HMAC-SHA256 JWT tokens, 30-day localStorage remember-me
- **Files:** `app.py` (main), `model_engine.py`, `db.py`, `data_refresh.py`, `universe_data.py`, `seed_model_portfolio_50.py`
- **Intraday cron:** cron-job.org → GitHub `workflow_dispatch` every 30 min market hours (PAT expires May 2027)
- **v2 branch:** All active development. Push with `git add app.py && git commit -m "..." && git push origin v2`

---

## Branches
- `main` → prod (qntmmvp.streamlit.app)
- `dev` → v1 dev (qntm-dev.streamlit.app)
- `v2` → v2 dev (qntm-v2-dev.streamlit.app) ← **active development**

**Standard push command (use every time):**
```bash
git add app.py && git commit -m "message" && git push origin v2
```

---

## Model
- **Universe:** 834 tickers (S&P 500 + Russell 1000)
- **5 Pillars:** Momentum 30%, Quality 25%, Volume 20%, Value 15%, Sentiment 10%
- **Signals:** HIGH ≥60, MODERATE 45–59, LOW <45 (UI labels — internally BUY/HOLD/SELL in DB)
- **Macro overlay:** 75/25 quant/macro, max 25% dampening in RISK_OFF/HIGH VOLATILITY
- **Backtest:** +347% adj vs SPY +131% · Sharpe 1.72 · Max DD 6.5% · 85% win rate

---

## V2 Architecture — Critical Patterns

### Session Restore
- Runs at module top-level (before `main()`) when `st.session_state.logged_in` is False
- Reads `uid` from query params → calls `get_user_by_id()` → sets full session state
- **`get_user_by_id` must be imported from `db`** — was missing, caused all nav session drops
- Falls back to building minimal session from query param `plan=` if DB call fails
- localStorage reader only injected inside `page_landing()` — NOT globally (caused location.replace wipe)

### URL Action Pattern (CRITICAL — use for all interactive elements)
**Never use `st.button` + `st.rerun()` for watchlist/navigation actions.** It clears session on Streamlit Cloud.

Instead use HTML `<a>` links with action query params:
```python
# Build action URL
_url = f"?qnav=screener&uid={uid}&plan={plan}&ck=1&wl_action=add&wl_ticker=AAPL"
st.markdown(f'<a href="{_url}" target="_self" style="...">☆ + Watchlist</a>', unsafe_allow_html=True)

# Router handles action at top of main() before any page renders:
_wl_action = st.query_params.get("wl_action", "")
_wl_ticker = st.query_params.get("wl_ticker", "")
if _wl_action and _wl_ticker and st.session_state.get("logged_in"):
    if _wl_action == "add": add_to_watchlist(uid(), _wl_ticker)
    elif _wl_action == "remove": remove_from_watchlist(uid(), _wl_ticker)
```

**When to use `st.button` (OK):** form submits (Sign In, Create Account, MFA verify, Save prefs, Rescan, Add holding, account upgrades)
**When to use URL action links:** watchlist add/remove, nav CTAs, any button that would otherwise call `st.rerun()` in a platform page

### CTA Helper Functions
```python
_cta_gold(label, href, full_width=True)   # Gold primary — Join Free, upgrade CTAs
_cta_ghost(label, href, full_width=True)  # Ghost secondary — Sign In, secondary actions
```
Both return HTML strings, render via `st.markdown(..., unsafe_allow_html=True)`.

### Nav Links
All nav links must carry: `?qnav=KEY&uid={user_id}&plan={plan}&ck=1`
- `uid` always read from `st.session_state.user.id` — NOT from query params (they get popped)
- `plan` from `st.session_state.user.plan`
- Watchlist actions append `&wl_action=add|remove&wl_ticker=TICKER`
- Screener search preserves query via `&sq=TICKER` param

### Scan Results / Page Reruns
- `scan_results` is cleared every 60s in `page_platform()` — **except on gems page** (would trigger 834-ticker rescan on button click)
- Never call `run_full_scan` inside a button handler — use session state cache
- `st.rerun()` is safe ONLY when `st.session_state.logged_in` is already True (in-platform rerenders)

---

## Supabase Tables
`users`, `holdings`, `signal_log`, `notifications`, `backtest_cache`, `fundamentals_cache`, `signal_snapshots`, `model_portfolio_positions`, `user_watchlist`

### signal_log
- One row per ticker per nightly run
- Key fields: `ticker`, `signal_date`, `adj_composite`, `composite`, `momentum`, `quality`, `volume`, `value`, `sentiment`, `price`, `signal` (BUY/HOLD/SELL internal), `macro_overlay` (numeric — do NOT write regime strings)
- Used for: signal history sparklines, watchlist trend arrows, model portfolio scoring

### user_watchlist
```sql
create table user_watchlist (
  id           uuid default gen_random_uuid() primary key,
  user_id      text not null,
  ticker       text not null,
  added_at     timestamptz default now(),
  price_at_add numeric,
  unique(user_id, ticker)
);
create index idx_watchlist_user on user_watchlist(user_id);
```

### model_portfolio_positions
- Seeded 2026-05-19 with 50-stock portfolio (41 filled due to sector cap)
- Position size: **$2,000** per position ($100K total target)
- Sector cap: **30% / 15 positions max** per sector
- Exit: score < 45 → SELL_SIGNAL; auto-reinvest into next highest conviction

---

## Model Portfolio Strategy
- **Target:** 50 positions, $2K each = $100K total
- **Entry:** adj_composite ≥ 60 (High Conviction)
- **Exit:** score < 45 → logged as SELL_SIGNAL, capital freed
- **Sector cap:** max 15 positions (30%) per sector — enforced on NEW entries only
- **Auto-fill:** `update_model_portfolio()` in `data_refresh.py` runs on BOTH nightly and intraday cron
- **Current state (May 24):** 41 active positions, 9 slots open (Energy/Materials capped)

---

## Watchlist (v2)
- **Page:** `page_watchlist()` — nav key: `watchlist`
- **DB helpers:** `get_watchlist()`, `add_to_watchlist()`, `remove_from_watchlist()` — defined in `app.py`
- **Add/Remove:** URL action links (gold = add, red = remove) — NOT st.button
- **Data shown:** ticker, sector, price, score, DAY %, SINCE ADDED %, TREND arrow, signal, factor drivers
- **Trend column:** batch-fetched last 2 signal_log rows per ticker — ↑ ↓ → with point delta
- **Conviction alerts:** gold banner at top when any stock changes conviction level or moves 10+ pts
- **Day change:** yfinance 5-day batch fetch
- **Since added:** compares current price to `price_at_add`

---

## Screener (v2)
- **Hero search:** 60px glowing green input, `key="screener_search"`, company name resolution via `resolve_ticker()`
- **Search persistence:** stored in `st.session_state.screener_search_val` + `&sq=TICKER` in watchlist URLs
- **Score card:** `factor_panel_html()` + "WHY THIS SCORE" plain-English explainability + signal history sparkline
- **Sparkline:** `signal_history_chart(ticker, current_score)` — SVG with conviction zones, trend label
- **Tabs:** Top 10 Signals | Full Universe | Sector Breakdown
- **Full Universe filters:** Sector / Conviction (High/Moderate/Low) / Min Score (60+/70+/80+)
- **Sparkline on full universe:** shown only when filtered to ≤20 results (performance)
- **Watchlist button:** gold "☆ + Watchlist" → red "✕ Remove from Watchlist" — URL action pattern

### resolve_ticker() aliases
Handles company name → ticker: "nvidia"→NVDA, "apple"→AAPL, "tesla"→TSLA, "microsoft"→MSFT, etc. Falls back to yfinance search.

---

## factor_panel_html() — Score Card
Returns full HTML card with:
- Ticker + conviction badge (HIGH/MODERATE/LOW) + sector
- Price + scan date
- "Driven by X + Y — watch Z" driver line
- 5 pillar bars with tooltip explainers
- QUANT / MACRO / BLEND / RANK stat grid
- **WHY THIS SCORE** plain-English explanation (drivers + watch items + macro context)

## signal_history_chart(ticker, current_score)
- Fetches last 30 signal_log rows for ticker
- Returns SVG sparkline with conviction zone bands (green ≥60, red <45)
- Trend: ↑ Improving / → Stable / ↓ Deteriorating (based on 5-day avg comparison)
- Graceful "building history" message if <3 data points
- Empty string if DB unavailable

---

## Page Functions (v2)
```python
page_landing()           # Public — hero, stats, competitor matrix, pricing
page_auth()              # Sign In / Join Free tabs (custom toggle buttons, not st.tabs)
page_mfa()               # TOTP verification
platform_nav()           # CSS checkbox dropdown nav
page_screener()          # Market screener — search, tabs, sparklines
page_watchlist()         # Tracked stocks — trend arrows, conviction alerts
page_gems()              # Hidden Gems (Pro) — watchlist add via URL action
page_backtest()          # Walk-forward backtest results
page_portfolio()         # My Portfolio — holdings P&L + conviction summary header
page_simulator()         # Portfolio Simulator (Pro)
page_model_portfolio()   # 50-stock live model portfolio
page_alerts()            # Signal change alerts
page_account()           # Profile, security, plan upgrade
page_methodology()       # How QNTM Works
page_platform()          # Container: nav + nav_map routing
```

---

## Auth Page (v2)
- Custom tab toggle (NOT st.tabs — clips on mobile)
- Two `st.columns(2)` buttons: "▶ Sign In" / "▶ Join Free" — styled as tabs
- `st.session_state.auth_tab` controls which form shows
- localStorage reader skipped when `nav=signin|register` or `page=auth` (prevents location.replace wipe)

---

## data_refresh.py Key Functions
- `run_refresh()` — full nightly: score all 834, write signal_log, call `update_model_portfolio()`
- `run_intraday_refresh()` — price-only pass, then calls `update_model_portfolio()`
- `update_model_portfolio()` — exits score<45, fills to 50, sector cap, $2K positions
- `cache_is_fresh()` — checks signal_log freshness
- `_get_supabase()` — uses `SUPABASE_SERVICE_KEY` (not anon key)

---

## Known Issues / Watch-outs
- `signal_log.macro_overlay` is numeric — do NOT write regime strings
- Min-position floor in `apply_macro_overlay()` promotes single-ticker searches — check `sr.get("promoted")`
- yfinance rate limits — intraday uses 0.5s sleep between 200-ticker chunks
- `st.components.v1.html` deprecation warning — cosmetic only
- Nav `qnav` links must include `&uid=...&plan=...&ck=1` suffix to preserve session
- Trend arrows on watchlist need ≥2 nightly cron runs; sparklines need ≥3
- Full universe sparkline only renders for ≤20 filtered results (performance guard)
- `get_user_by_id` must be in the `from db import (...)` list — was missing, caused session drops

---

## Pre-Launch Checklist

### Blocking Revenue
- [ ] **Fintech lawyer review** — contact Mark. Questions: IAA 1940, HIGH/MOD/LOW label adequacy, disclaimer language, CA DFPI, LLC vs sole proprietor
- [ ] **Stripe integration** — `STRIPE_SECRET_KEY` + `STRIPE_PRICE_ID_PRO` + webhook

### Next Session Priority
1. Stripe integration (unblocks revenue)
2. "What changed today?" delta context on score cards
3. Screener recent searches (quick-tap chips below search box)
4. Signal history sparkline on watchlist page (full per-stock chart)
5. Push v2 → main (merge when stable)

### Completed (May 24 session)
- [x] Mobile layout pass — responsive watchlist/model portfolio cards
- [x] Session restore fixed (`get_user_by_id` import, fallback to query params)
- [x] URL action pattern for all watchlist interactions
- [x] Gold/red watchlist button states (add=gold, remove=red)
- [x] Screener search persistence across nav
- [x] `_cta_gold()` / `_cta_ghost()` helper functions — all major CTAs converted
- [x] Landing nav buttons visible on mobile
- [x] Auth page tab buttons — custom toggle, no st.tabs clipping
- [x] Factor panel "WHY THIS SCORE" explainability
- [x] Watchlist conviction change alerts (banner)
- [x] Watchlist trend column (↑ ↓ → with delta)
- [x] Signal history sparkline on screener search result
- [x] Full universe sparkline (filtered ≤20)
- [x] Screener filters: Conviction labels + Min Score filter
- [x] Portfolio conviction summary CSS fix
- [x] Gems watchlist add/remove via URL action
- [x] `resolve_ticker()` company name aliases (nvidia, apple, tesla, etc.)
- [x] `scan_results` not cleared on gems page (prevents 4-min rescan on interaction)
- [x] localStorage reader scoped to landing page only

---

## Secrets Required
```toml
SUPABASE_URL = "https://zqrudkoqhsjsltpefgcl.supabase.co"
SUPABASE_ANON_KEY = "..."
SUPABASE_SERVICE_KEY = "..."
ENCRYPTION_KEY = "gvRXtS0L-DqgRu9ieMvt9oxMgPdCChFCsUx-qgyGXd0="
ENVIRONMENT = "dev"   # v2 app only
```

---

## Session History

### May 24, 2026 (full day) — v2 mobile + product pass
See "Completed" checklist above. Major themes: session architecture stabilization, URL action pattern, mobile UX, explainability features, signal history.

### Earlier May 24 (morning) — v2 initial build
- CSS checkbox dropdown nav
- Landing page hero redesign
- Cookie banner → slim implied consent
- Onboarding disabled
- Live Refresh removed
- Watchlist feature: page + DB + day/since change
- Model portfolio: 50 stocks, $2K/position, 30% sector cap
- Methodology page
- Persistent disclaimer footer

### Previous Sessions
- v1 fixes: SPY benchmark, mobile layout, nav, signal labels, screener UX
- Stack Financial Technologies (folded), structural analyzer (GitHub: andymcalister/structural-analyzer)
