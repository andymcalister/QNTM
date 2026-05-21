# QNTM Platform — Handoff Summary
*Updated: May 20, 2026*

## What It Is
QNTM is a quantitative conviction factor model platform for retail investors. Bloomberg terminal aesthetic, dark theme. Live at **qntmmvp.streamlit.app** (prod) and **qntm-dev.streamlit.app** (dev).

---

## Tech Stack
- **Frontend:** Streamlit (Python), custom HTML/CSS throughout
- **Database:** Supabase (PostgreSQL) at `zqrudkoqhsjsltpefgcl.supabase.co`
- **Auth:** bcrypt + TOTP MFA, AES-256 + HMAC-SHA256 JWT tokens, 30-day localStorage remember-me
- **GitHub:** `andymcalister/QNTM` — `main` → prod, `dev` → dev
- **Files:** `app.py` (~5,981 lines), `model_engine.py`, `db.py`, `data_refresh.py`, `proper_backtest.py`, `seed_track_record.py`, `universe_data.py`
- **Intraday trigger:** cron-job.org fires GitHub `workflow_dispatch` every 30 min, 1:30–8:30 PM UTC, Mon–Fri

---

## Model
- **Universe:** 834 tickers (S&P 500 + Russell 1000, cleaned — 12 delisted tickers removed May 20)
- **5 Pillars:** Momentum 30%, Quality 25%, Volume 20%, Value 15%, Sentiment 10%
- **Signals:** HIGH ≥60, MODERATE 45–59, LOW <45 (UI labels — internally still BUY/HOLD/SELL in model logic and DB)
- **Macro overlay:** Regime-scaled — 35% weight RISK_OFF, 15% RISK_ON, 10% NEUTRAL
- **Macro detection:** Yahoo Finance RSS + FRED RSS + yfinance VIX + WTI crude (no API keys needed)
- **Backtest:** Walk-forward, real prices, 10bps transaction costs, 124 tickers × 20 quarters (Q2 2020–Q1 2025)
- **Results:** +347% raw / +307% adj vs SPY +131% · Sharpe 1.72 · Sortino 10.53 · Max DD 6.5% vs SPY 25.4% · 80% quarterly win rate
- **Tiers:** Free and Pro ($29/mo, Stripe stub in place — not yet wired)

---

## Key Architecture Decisions

### Streamlit Rendering Rules
- All custom HTML rendered as string variables first, then `st.markdown(html, unsafe_allow_html=True)` — never multiline f-string markdown with inline conditionals
- **CRITICAL: `st.markdown` strips ALL `<script>` tags** — any JS must go in `st.components.v1.html()` which runs in an iframe. Use `parent.document` to access the main page DOM from that iframe
- `st.components.v1.html` is deprecated as of Streamlit 1.57 (warning only — won't break until after June 1, 2026). Replacement API not yet stable; defer migration
- No HTML comments `<!-- -->` inside `st.markdown` — Streamlit strips them and breaks surrounding content
- **Nested f-strings with `{}` in variables cause silent failures** — when building HTML that contains CSS `{}` or format strings, use string concatenation (`+`) not f-string embedding
- **Never hardcode `846`** — universe is now 834. Use `len(SECTORS)` or the hardcoded `834` where f-strings aren't available

### Mobile Layout Rules
- Don't use `st.columns()` for content that needs to reflow on mobile — use CSS `grid-template-columns: repeat(auto-fit, minmax(Xpx, 1fr))` instead
- `st.radio(horizontal=True)` works well for nav tabs — native Streamlit handles mobile wrapping
- Tooltips must use `position:fixed` with JS `getBoundingClientRect()` — `position:absolute` bleeds off-screen due to parent `overflow:hidden`
- `st.components.v1.html(height=0)` iframes are hidden via CSS: `iframe[height="0"] { display:none !important; }`
- MFA prompt buttons: use full-width stacked `st.button(use_container_width=True)` — never `st.columns(2)` for buttons with long labels on mobile

### Macro Overlay — CRITICAL
- `apply_macro_overlay()` looks up `sector_overlays` by sector name
- Sector names in `SECTOR_EVENT_MAP` use `"Consumer Discretionary"` — universe_data.py must also use `"Consumer Discretionary"` (not `"Cons Discretionary"`)
- **Sector must be assigned to raw scores BEFORE calling `apply_macro_overlay()`** — not after
- Fix pattern in screener: `for r in raw: r["sector"] = ALL_SECTORS.get(r["ticker"], "Unknown")` then `apply_macro_overlay(raw, macro)`

### Auth & Session
- **JWT:** `_sign_token()` now uses real HMAC-SHA256. Payload is `base64(json)|hex_sig`, uses `ENCRYPTION_KEY` from secrets, 30-day expiry enforced on verify
- **Session restore priority:** URL `?uid=` param checked first, localStorage fires second via `_inject_localstorage_reader()`
- **`signed_out` flag** — only blocks localStorage restore within same session, not across browser refresh
- `go(page)` preserves `uid`/`plan` in URL query params on every navigation

### Signal Labels — CRITICAL
- UI displays: **HIGH** (≥60), **MODERATE** (45–59), **LOW** (<45)
- Internal model logic, DB storage, and `signal_log.signal` column still use `"BUY"/"HOLD"/"SELL"` — do NOT change these
- Only the rendered display strings use HIGH/MOD/LOW

### CSS Global Rules
- Global CSS is in one large `st.markdown("""<style>...</style>""")` block at top of file
- Font sizes in inline `style=""` attributes override global CSS — must be changed directly in the HTML strings
- Key color palette: `#00ff87` (green/HIGH), `#fbbf24` (yellow/MOD), `#ef4444` (red/LOW), `#d4a843` (gold/accent), `#94a3b8` (secondary text), `#cbd5e1` (primary text)

### Supabase / get_supabase
- App uses `_get_supabase()` imported from `data_refresh` — there is NO standalone `get_supabase()` in app.py scope
- Both `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` must be in Streamlit Cloud secrets AND GitHub Actions secrets
- signal_log RLS: "Signal log public read" policy on SELECT for `public` role — anon reads work
- `signal_log.macro_overlay` is **numeric** — do NOT write regime strings to it
- `fundamentals_cache.refreshed_at` is updated on every refresh (nightly + intraday) — used by the freshness pill

---

## Nav Structure
```
Screener | Hidden Gems | Backtest | My Portfolio | Simulator | Model Portfolio | Alerts | Account
```
Keys: `screener | gems | backtest | portfolio | simulator | model_portfolio | alerts | account`

All defined in `platform_nav()` → `nav_options` and `nav_keys` lists, and in `nav_map` dict in `page_platform()`.

---

## Session State Keys (important ones)
```python
logged_in, user, mfa_verified, scan_results, macro_data,
page, nav, cookies_accepted, signed_out, remember_me,
pending_mfa_user, pending_mfa_secret, mfa_recovery_mode,
show_mfa_setup, force_mfa_setup, legal_doc, auto_upgrade,
onboarding_done, onboarding_step, port_period, last_refresh,
live_refresh_running, sim_profile, sim_selected, sim_weights,
sim_profile_applied
```

---

## Routing
```python
?page=model     → public model portfolio track record (no auth, no cookie gate)
?legal=privacy  → Privacy Policy
?legal=terms    → Terms of Service
?legal=cookies  → Cookie Policy
?ck=1           → cookie consent accepted (persists across sessions)
?uid=&plan=     → session restore (HMAC-signed JWT token)
?nav=signin     → route to sign in page
?nav=register   → route to register page
```

---

## Supabase Tables
`users`, `holdings`, `signal_log`, `notifications`, `backtest_cache`, `fundamentals_cache`, `signal_snapshots`, `model_portfolio_positions`

**signal_log** columns: `id, ticker, signal_date, composite, momentum, quality, volume, value, sentiment, signal, macro_overlay (numeric), adj_composite, is_hidden_gem, hidden_gem_reason, created_at, price`

**model_portfolio_positions** columns: `id, ticker, entry_date, entry_price, entry_score, exit_date, exit_price, exit_score, exit_reason, position_size, is_active, created_at`
- Seeded 2026-05-19 with top 20 HIGH conviction signals
- RLS: public read, service role full access

**fundamentals_cache** — `refreshed_at` touched on every nightly AND intraday run (via `_intraday_sentinel` row). Used by `data_freshness_banner()` to show last refresh time including intraday.

---

## GitHub Actions / Intraday Refresh
- **Workflow:** `.github/workflows/nightly_refresh.yml` — on `main` branch
- **Nightly schedule:** 2:00 AM UTC daily (full 834-ticker refresh, ~9 min)
- **Intraday schedule:** `*/30 13-20 * * 1-5` in workflow (GitHub scheduler unreliable — use cron-job.org instead)
- **External trigger:** cron-job.org fires `workflow_dispatch` every 30 min during market hours via GitHub API (PAT with `workflow` scope, expires May 2027)
- **INTRADAY_RUN env var:** set to `"true"` when triggered by the `*/30` cron — runs `data_refresh.py --intraday` (~90s)
- **Secrets required:** `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ENCRYPTION_KEY`

---

## data_refresh.py — Key Functions
- `run_refresh()` — full nightly: fetch fundamentals, score all 834 tickers, write signal_log + model_portfolio_positions
- `run_intraday_refresh()` — lightweight: fetch current prices via yfinance (200-ticker batches, 0.5s sleep), upsert price into signal_log, touch `fundamentals_cache.refreshed_at` via `_intraday_sentinel` row
- `cache_is_fresh()` — checks if today's signal_log already written
- **yfinance MultiIndex:** `yf.download()` returns MultiIndex DataFrame for multi-ticker batches — handle `hist["Close"][tk]` (MultiIndex), `hist["Close"]` (flat), and Series (single ticker) cases

---

## Page Functions Reference
```python
page_landing()              # Public landing — perf stats, competitor matrix, pricing
page_auth()                 # Sign in / register
page_mfa()                  # TOTP MFA verification
page_screener()             # Market screener — Top 10, Full Universe, Sector tabs
page_gems()                 # Hidden Gems (Pro)
page_backtest()             # Walk-forward backtest results
page_portfolio()            # My Portfolio — holdings, P&L tracking
page_simulator()            # Portfolio Simulator (Pro) — risk profiles, search-add, weights
page_model_portfolio()      # Live model portfolio — 20 positions from May 19
page_alerts()               # Signal change alerts
page_account()              # Profile, security, plan, notifications
page_public_track_record()  # Public ?page=model — standalone track record
```

---

## Simulator (page_simulator) — Pro Feature
- **3 risk profiles:** HIGH (top 20 by momentum), MEDIUM (top 20 by composite — default), LOW (top 20 by quality+value)
- **Session state:** `sim_profile`, `sim_selected`, `sim_weights`, `sim_profile_applied`
- **Search add:** text input searches ticker prefix across full scan universe
- **Equal weight toggle:** when off, per-position weight sliders in expanders (normalised to 100%)
- Pre-populates top 20 from selected profile on first load or profile switch

---

## Model Portfolio (page_model_portfolio) — Key Behaviors
- Positions loaded from `model_portfolio_positions` Supabase table
- Current prices + pillar scores pulled from `signal_log` — **no rescan required**
- Gem badges pulled from `signal_log.is_hidden_gem` — **no rescan required**
- SPY benchmark fetched live via yfinance from earliest entry date
- Rows: static HTML table always visible; each row followed by `st.expander("▸ pillar detail")` for MOM/QUAL/VOL/VAL/SENT scores
- Inception date: **May 19, 2026** (hardcoded fallback + dynamic from min entry_date)
- Prices shown to 2 decimal places (fractional moves were hidden with 0dp rounding)

---

## Landing Page Sections (in order)
1. Hero — headline, CTA buttons, live ticker strip (834 STOCKS)
2. Performance — 5-year stats (4 numbers + regime cards + risk metrics)
3. $100K outcome bar — QNTM $447k vs quant fund $310k vs SPY $231k vs retail $162k
4. The Model — 5 pillars + signal thresholds
5. VS The Market — competitor matrix (12 features × 6 competitors)
6. Pricing — Free / Pro ($29) / Institutional
7. Footer — legal links, © 2026 QNTM

---

## Pre-Launch Checklist

### Blocking Revenue
- [ ] **Fintech lawyer review** — ~1hr, ~$300-600. Questions: (1) IA status, (2) HIGH/MOD/LOW labels, (3) disclaimer adequacy. Contact texted May 20.
- [ ] **Stripe integration** — `STRIPE_SECRET_KEY` + `STRIPE_PRICE_ID_PRO` + webhook

### Before June 1
- [ ] **`st.components.v1.html` migration** — deprecation warning only, defer until Streamlit ships stable replacement

### Polish
- [ ] Screener mobile card truncation — pillar scores cut off on narrow phones (Full Universe tab)

---

## Secrets Required

### Streamlit Cloud (both apps)
```toml
SUPABASE_URL = "https://zqrudkoqhsjsltpefgcl.supabase.co"
SUPABASE_ANON_KEY = "..."
SUPABASE_SERVICE_KEY = "..."
ENCRYPTION_KEY = "gvRXtS0L-DqgRu9ieMvt9oxMgPdCChFCsUx-qgyGXd0="
ENVIRONMENT = "dev"   # dev app only — omit for prod
```

### GitHub Actions
```
SUPABASE_URL
SUPABASE_SERVICE_KEY
ENCRYPTION_KEY
```

### cron-job.org
- GitHub PAT with `workflow` scope — expires May 2027 (set calendar reminder)
- URL: `POST https://api.github.com/repos/andymcalister/QNTM/actions/workflows/nightly_refresh.yml/dispatches`
- Body: `{"ref":"main","inputs":{"force":"false"}}`
- Schedule: every 30 min, 1:30–8:30 PM UTC, Mon–Fri

---

## Cost Structure (all $0/mo)
- Streamlit Cloud, Supabase, GitHub Actions, cron-job.org, yfinance — all free tier
- **Cost triggers:** first paying users → Streamlit ~$20/mo; ~500 users → Supabase ~$25/mo; custom domain → $10-15/yr

---

## Known Issues / Watch-outs
- yfinance rate limits during market hours — intraday uses 0.5s sleep between chunks
- `signal_log.macro_overlay` is numeric — do NOT write regime strings to it
- `st.components.v1.html` deprecation warning in logs — cosmetic only
- GitHub Actions free tier scheduler unreliable for `*/30` crons — cron-job.org is the reliable trigger
- Model portfolio entry prices seeded at 2AM UTC May 19 — may reflect May 18 close for some tickers
- cron-job.org PAT expires May 2027 — set a calendar reminder

---

## Output Files Location
Production: `andymcalister/QNTM` — `main` branch
Dev: `andymcalister/QNTM` — `dev` branch
Both deployed on Streamlit Cloud. Push to `dev` only during development, merge to `main` for prod releases.
