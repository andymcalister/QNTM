# QNTM Platform — Handoff Summary
*Updated: May 24, 2026*

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
- **v2 branch:** All active development. `app.py` on v2 branch = v2 version.

---

## Branches
- `main` → prod (qntmmvp.streamlit.app)
- `dev` → v1 dev (qntm-dev.streamlit.app) 
- `v2` → v2 dev (qntm-v2-dev.streamlit.app) ← **active development**

**Deploy v2:**
```bash
git checkout v2
cp app_v2.py app.py  # if working from app_v2.py locally
git add app.py
git commit -m "message"
git push origin v2
```

---

## Model
- **Universe:** 834 tickers (S&P 500 + Russell 1000)
- **5 Pillars:** Momentum 30%, Quality 25%, Volume 20%, Value 15%, Sentiment 10%
- **Signals:** HIGH ≥60, MODERATE 45–59, LOW <45 (UI labels — internally BUY/HOLD/SELL in DB)
- **Macro overlay:** 75/25 quant/macro, max 25% dampening in RISK_OFF/HIGH VOLATILITY
- **Backtest:** +307% adj vs SPY +131% · Sharpe 1.72 · Max DD 6.5% · 85% win rate

---

## V2 Major Changes vs V1

### Navigation
- Pure CSS checkbox dropdown (`#qntm-toggle`) — no JS, works in Streamlit
- Trigger: `<label for="qntm-toggle">☰ MENU</label>` — shows current page
- Dropdown: 3-col grid of styled box buttons, active page highlighted green
- Navigation via `?qnav=KEY&uid=...&plan=...&ck=1` links with `target="_self"`
- `qnav` routing in `main()` sets `session_state.nav` + `page="platform"`
- Session restore reads `?qnav=` BEFORE hardcoding nav to preserve destination
- **Nav items:** screener, watchlist, gems, backtest, portfolio, simulator, model_portfolio, alerts, account, methodology

### Signal Labels (UI only)
- HIGH / MODERATE / LOW throughout UI
- Internal model + DB still use BUY/HOLD/SELL — do NOT change
- Alerts translate on display via `.replace()`

### Landing Page
- Two-column hero: headline left, 4 stat cards right (from BACKTEST_DATA)
- Hero HTML built via string concatenation — NO f-strings (avoids CSS brace conflicts)
- Cookie banner: slim bottom notice, implied consent, auto-sets `cookies_accepted=True`
- No full-page cookie gate

### Onboarding
- `show_onboarding()` is a no-op — disabled
- `onboarding_done` defaults to `True` in session state

### Live Refresh
- **REMOVED** from UI — no more 3-4 min refresh button
- Nightly cron handles data freshness
- Users hit Rescan for instant re-score using cached fundamentals

---

## Supabase Tables
`users`, `holdings`, `signal_log`, `notifications`, `backtest_cache`, `fundamentals_cache`, `signal_snapshots`, `model_portfolio_positions`, `user_watchlist`

### user_watchlist (NEW in v2)
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
**Note:** `price_at_add` column must be added if not present:
```sql
alter table user_watchlist add column if not exists price_at_add numeric;
```

### model_portfolio_positions
- Seeded 2026-05-19 with 50-stock portfolio (41 filled due to sector cap)
- Position size: **$2,000** per position ($100K total target)
- Sector cap: **30% / 15 positions max** per sector
- Exit: score < 45 → SELL_SIGNAL
- Re-entry: next highest conviction not held, respecting sector cap
- Auto-fills toward 50 on every nightly + intraday cron run

---

## Model Portfolio Strategy
- **Target:** 50 positions, $2K each = $100K total
- **Entry:** adj_composite ≥ 60 (High Conviction)
- **Hold:** by default
- **Exit:** score < 45 → logged as SELL_SIGNAL, capital freed
- **Reinvest:** immediately finds next highest conviction not held, sector cap respected
- **Wait:** if no qualifying candidate, slot stays open until next refresh finds one
- **Sector cap:** max 15 positions (30%) per sector — enforced on NEW entries only, never force-exits existing
- **Auto-fill:** `update_model_portfolio()` in `data_refresh.py` runs on BOTH nightly and intraday cron
- **Live prices:** model portfolio page fetches via `yf.download()` batch for all positions

### Current portfolio state (as of May 24)
- 41 active positions (9 slots open — waiting for non-Energy/Materials HIGH conviction)
- Energy: 15 positions (capped), Materials: 14, Healthcare: 7, Consumer Staples: 3, Real Estate: 1, Comm Services: 1
- Inception: May 19–23, 2026

---

## Watchlist (NEW in v2)
- **Page:** `page_watchlist()` — nav key: `watchlist`
- **DB helpers:** `get_watchlist()`, `add_to_watchlist()`, `remove_from_watchlist()` 
- **Add button:** appears below search result card on Screener — gold if not in list, ghost if already added
- **Data shown:** ticker, company, sector, live price, conviction score, signal, DAY change %, SINCE ADDED change %, factor drivers (top 2 pillars)
- **Day change:** yfinance 5-day batch fetch, compares today vs prev close
- **Since added:** compares current price to `price_at_add` stored at time of adding
- **Remove:** "Remove TICKER" button per row

---

## Key Architecture Rules

### Streamlit HTML Rendering
- `st.markdown` strips `<script>` tags — JS must go in `st.components.v1.html()` (iframe)
- **Never use HTML comments** `<!-- -->` inside `st.markdown` — strips surrounding HTML
- **Never use `{{}}` CSS braces inside f-strings** — use string concatenation instead
- Never split `<div>` open/close across separate `st.markdown()` calls
- `components.v1.html` iframe is sandboxed — `window.parent.location.href` is blocked

### Nav CSS Checkbox Pattern (WORKING)
```python
# In st.markdown:
'<input type="checkbox" id="qntm-toggle">'
'<label for="qntm-toggle">☰ MENU</label>'
'<div id="qntm-dd">...<a href="?qnav=KEY..." target="_self">...</a>...</div>'
# CSS:
'#qntm-toggle{display:none;}'
'#qntm-toggle:checked ~ #qntm-dd{max-height:600px;opacity:1;}'
```

### Session State Key Defaults
```python
"onboarding_done": True,   # disabled
"tz_offset_hours": None,   # injected after cookie accept
"tz_name": None,
```

### Timezone Detection
- Injected via `components.html` **only after cookies accepted**
- Reads `?_tz=` and `?_tzname=` query params
- Used to show last refresh time in user's local timezone with proper abbreviation (PDT, EDT etc.)

---

## Page Functions (v2)
```python
page_landing()           # Public — hero, stats, competitor matrix, pricing
page_auth()              # Sign In / Create Free Account tabs
page_mfa()               # TOTP verification
platform_nav()           # CSS checkbox dropdown nav — called from page_platform()
page_screener()          # Market screener — Rescan, hero search, macro, tabs
page_watchlist()         # NEW — tracked stocks with day/since change
page_gems()              # Hidden Gems (Pro feature)
page_backtest()          # Walk-forward backtest results
page_portfolio()         # My Portfolio — holdings P&L
page_simulator()         # Portfolio Simulator (Pro)
page_model_portfolio()   # 50-stock live model portfolio
page_alerts()            # Signal change alerts
page_account()           # Profile, security, plan
page_methodology()       # How QNTM Works — transparent methodology
page_platform()          # Container: calls platform_nav() + nav_map routing
```

---

## Screener Search (v2)
- Hero search box: 60px tall, glowing green border, `key="screener_search"`
- Label: large Syne font "⚡ Instant Conviction Score" + subtitle
- Resolves company names via `resolve_ticker()` (inline dict + yfinance fallback)
- Unknown tickers → clean not-found card
- Score result shows: factor panel + "Add to Watchlist" gold button
- Min-position floor bug: use `apply_macro_overlay()` normally, then check `sr.get("promoted")` and correct `adj_action`

---

## data_refresh.py Key Functions
- `run_refresh()` — full nightly: score all 834, write signal_log, call `update_model_portfolio()`
- `run_intraday_refresh()` — price-only pass, then calls `update_model_portfolio()` with today's signal_log
- `update_model_portfolio()` — full strategy: exits score<45, fills to 50, sector cap, $2K positions
- `cache_is_fresh()` — checks signal_log freshness

---

## CTA Button Standards (v2)
- **Gold primary:** `.land-btn-primary` wrapper → `background: linear-gradient(135deg,#d4a843...)`
- **Ghost secondary:** `.land-btn-ghost` wrapper → transparent with white border
- Both defined in **global CSS block** (not just landing page CSS)
- All auth/nav links: `target="_self"` to prevent new tab

---

## Pre-Launch Checklist

### Blocking Revenue
- [ ] **Fintech lawyer review** — contact Mark. Questions: IAA 1940, HIGH/MOD/LOW label adequacy, disclaimer language, CA DFPI, LLC vs sole proprietor
- [ ] **Stripe integration** — `STRIPE_SECRET_KEY` + `STRIPE_PRICE_ID_PRO` + webhook

### V2 Remaining Work (in priority order)
- [ ] Push v2 to production (merge v2 → main) once stable
- [ ] Portfolio page — conviction summary header (built, verify working)
- [ ] Hidden Gems — why-tags display (built, verify working)
- [ ] Alerts page — verify HIGH/MODERATE/LOW labels correct
- [ ] Account page — verify plan display, MFA flow
- [ ] Mobile layout — test all pages on 375px
- [ ] Screener tabs (Top 10, Full Universe, Sector Breakdown) — verify after v2 changes
- [ ] Factor panel explainability — macro delta context on score cards
- [ ] Email notifications (Stripe → plan upgrade → enable)
- [ ] Watchlist alerts — notify when watched stock changes conviction level

### Known Issues / Watch-outs
- `signal_log.macro_overlay` is numeric — do NOT write regime strings
- Min-position floor in `apply_macro_overlay()` promotes single-ticker searches — check `sr.get("promoted")`
- yfinance rate limits — intraday uses 0.5s sleep between 200-ticker chunks
- `st.components.v1.html` deprecation warning — cosmetic only
- Model portfolio `price_at_add` column needs to exist in `user_watchlist` table
- 9 open slots in model portfolio — will fill as new non-Energy/Materials conviction emerges
- Nav `qnav` links must include `&uid=...&plan=...&ck=1` suffix to preserve session

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

## Session History Summary

### This Session (May 24, 2026) — v2 build
Major v2 redesign work:
- CSS checkbox dropdown nav with box-button grid
- Landing page hero redesign (two-column with stat cards)
- Cookie banner → slim bottom notice, implied consent
- Onboarding disabled
- Live Refresh removed from UI
- Signal labels: HIGH/MODERATE/LOW throughout
- Search hero box with glowing border
- Watchlist feature: page + DB + add button + day/since change
- Model portfolio: 50 stocks, $2K/position, 30% sector cap, auto-fill
- Seeder: `seed_model_portfolio_50.py` — Monday takes all HIGH, tops up daily
- data_refresh.py: `update_model_portfolio()` rewritten for full strategy, wired into intraday
- Methodology page added
- Persistent disclaimer footer
- Gold CTA buttons standardized globally
- Menu: CSS checkbox, box buttons, active state highlighted

### Previous Sessions
- v1 fixes: SPY benchmark, mobile layout, nav, signal labels, screener UX
- Stack Financial Technologies (folded), structural analyzer (GitHub: andymcalister/structural-analyzer)
