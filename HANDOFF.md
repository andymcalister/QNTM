# QNTM Platform — Handoff Summary
*Updated: May 21, 2026*

## What It Is
QNTM is a quantitative conviction factor model platform for retail investors. Bloomberg terminal aesthetic, dark theme. Live at **qntmmvp.streamlit.app** (prod) and **qntm-dev.streamlit.app** (dev).

---

## Tech Stack
- **Frontend:** Streamlit (Python), custom HTML/CSS throughout
- **Database:** Supabase (PostgreSQL) at `zqrudkoqhsjsltpefgcl.supabase.co`
- **Auth:** bcrypt + TOTP MFA, AES-256 + HMAC-SHA256 JWT tokens, 30-day localStorage remember-me
- **GitHub:** `andymcalister/QNTM` — `main` → prod, `dev` → dev
- **Files:** `app.py` (~5,981 lines), `model_engine.py`, `db.py`, `data_refresh.py`, `proper_backtest.py`, `seed_track_record.py`, `universe_data.py`
- **Intraday trigger:** cron-job.org fires GitHub `workflow_dispatch` every 30 min, Mon–Fri during market hours (PAT with `workflow` scope, expires May 2027)

---

## Model
- **Universe:** 834 tickers (S&P 500 + Russell 1000, cleaned — 12 delisted tickers removed May 20)
- **5 Pillars:** Momentum 30%, Quality 25%, Volume 20%, Value 15%, Sentiment 10%
- **Signals:** HIGH ≥60, MODERATE 45–59, LOW <45 (UI labels — internally still BUY/HOLD/SELL in model logic and DB)
- **Macro overlay:** Regime-scaled — 35% weight RISK_OFF, 15% RISK_ON, 10% NEUTRAL
- **Backtest:** Walk-forward, real prices, 10bps transaction costs, 124 tickers × 20 quarters (Q2 2020–Q1 2025)
- **Results:** +347% raw / +307% adj vs SPY +131% · Sharpe 1.72 · Sortino 10.53 · Max DD 6.5% · 80% quarterly win rate
- **Tiers:** Free and Pro ($29/mo, Stripe stub in place — not yet wired)

---

## Nav Structure
```
Screener | Hidden Gems | Backtest | My Portfolio | Simulator | Model Portfolio | Alerts | Account
```
Keys: `screener | gems | backtest | portfolio | simulator | model_portfolio | alerts | account`

---

## Key Architecture Decisions

### Signal Labels — CRITICAL
- UI displays: **HIGH** (≥60), **MODERATE** (45–59), **LOW** (<45)
- Internal model logic, DB storage, and `signal_log.signal` column still use `"BUY"/"HOLD"/"SELL"` — do NOT change these

### Streamlit Rendering Rules
- All custom HTML rendered as string variables first, then `st.markdown(html, unsafe_allow_html=True)`
- **`st.markdown` strips ALL `<script>` tags** — JS must go in `st.components.v1.html()` (iframe)
- `st.components.v1.html` deprecated in Streamlit 1.57 (warning only — defer migration)
- No HTML comments `<!-- -->` inside `st.markdown`
- Nested f-strings with `{}` in CSS cause silent failures — use string concatenation

### Auth & JWT
- `_sign_token()` uses real HMAC-SHA256. Payload: `base64(json)|hex_sig`, uses `ENCRYPTION_KEY`, 30-day expiry
- Session restore: URL `?uid=` first, localStorage second via `_inject_localstorage_reader()`

### Supabase
- App uses `_get_supabase()` imported from `data_refresh` — no standalone `get_supabase()` in app.py
- `signal_log.macro_overlay` is **numeric** — do NOT write regime strings to it
- `fundamentals_cache.refreshed_at` touched on every run (nightly + intraday via `_intraday_sentinel` row)
- Model portfolio pulls prices + pillar scores from `signal_log` directly — **no rescan required**
- Gem badges pulled from `signal_log.is_hidden_gem` — **no rescan required**

### Macro Overlay
- Sector names must use `"Consumer Discretionary"` (not `"Cons Discretionary"`)
- Sector must be assigned to raw scores BEFORE calling `apply_macro_overlay()`

---

## Supabase Tables
`users`, `holdings`, `signal_log`, `notifications`, `backtest_cache`, `fundamentals_cache`, `signal_snapshots`, `model_portfolio_positions`

**signal_log** columns: `id, ticker, signal_date, composite, momentum, quality, volume, value, sentiment, signal, macro_overlay (numeric), adj_composite, is_hidden_gem, hidden_gem_reason, created_at, price`

**model_portfolio_positions** columns: `id, ticker, entry_date, entry_price, entry_score, exit_date, exit_price, exit_score, exit_reason, position_size, is_active, created_at`
- Seeded 2026-05-19 with top 20 HIGH conviction signals
- Inception date: May 19, 2026

---

## GitHub Actions / Intraday Refresh
- **Workflow:** `.github/workflows/nightly_refresh.yml` — on `main` branch only
- **Nightly:** 2:00 AM UTC daily (full 834-ticker refresh, ~9 min)
- **Intraday:** cron-job.org triggers `workflow_dispatch` every 30 min during market hours
  - URL: `POST https://api.github.com/repos/andymcalister/QNTM/actions/workflows/nightly_refresh.yml/dispatches`
  - Header: `Authorization: Bearer ghp_...` (PAT with `workflow` scope, expires May 2027)
  - Body: `{"ref":"main","inputs":{"force":"false"}}`
- `INTRADAY_RUN=true` env var triggers `data_refresh.py --intraday` (~90s price-only pass)
- **Secrets:** `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ENCRYPTION_KEY`

### yfinance MultiIndex gotcha
`yf.download()` returns MultiIndex DataFrame for multi-ticker — handle `hist["Close"][tk]` (MultiIndex), `hist["Close"]` (flat), and Series (single ticker) cases separately.

---

## data_refresh.py Key Functions
- `run_refresh()` — full nightly: fetch fundamentals, score all 834 tickers, write signal_log + model_portfolio_positions
- `run_intraday_refresh()` — lightweight: fetch current prices (200-ticker batches), upsert price into signal_log, touch `fundamentals_cache.refreshed_at` via `_intraday_sentinel` row
- `cache_is_fresh()` — checks if today's signal_log already written

---

## Page Functions
```python
page_landing()              # Public landing — perf stats, competitor matrix, pricing
page_auth()                 # Sign in / register
page_mfa()                  # TOTP MFA verification
page_screener()             # Market screener — Top 10, Full Universe, Sector tabs
page_gems()                 # Hidden Gems (Pro)
page_backtest()             # Walk-forward backtest results + Chart.js growth chart
page_portfolio()            # My Portfolio — holdings, P&L tracking
page_simulator()            # Portfolio Simulator (Pro) — 3 risk profiles, search-add, custom weights
page_model_portfolio()      # Live model portfolio — 20 positions from May 19
page_alerts()               # Signal change alerts
page_account()              # Profile, security, plan, notifications
page_public_track_record()  # Public ?page=model route
```

---

## Model Portfolio Page Details
- Positions loaded from `model_portfolio_positions` Supabase table
- Current prices + pillar scores pulled from `signal_log` — no rescan needed
- SPY benchmark fetched live via yfinance from earliest entry date
- **Performance chart removed** — will re-add once model builds positive track record
- Rows: compact single-line cards (6 columns: Ticker+name | Sector+date | Entry→Current | Shares | P&L | Return+Score)
- Left border: green if positive P&L, red if negative
- Inception date: May 19, 2026 (hardcoded fallback + dynamic from min entry_date)
- Prices shown to 2 decimal places

---

## Simulator (Pro Feature)
- **3 risk profiles:** HIGH (top 20 by momentum), MEDIUM (top 20 by composite — default), LOW (top 20 by quality+value)
- **Session state:** `sim_profile`, `sim_selected`, `sim_weights`, `sim_profile_applied`
- Search-to-add by ticker prefix
- Equal weight toggle; per-position weight sliders when off (normalised to 100%)

---

## Landing Page Sections (in order)
1. Hero — headline, CTA buttons
2. Performance stats — 5-year numbers
3. The Model — 5 pillars
4. VS The Market — competitor matrix (12 features × 6 competitors)
5. Pricing — Free / Pro $29 / Institutional
6. Footer — © 2026 QNTM

---

## Disclaimers (added May 20)
Three blocks added to DISCLAIMER and DISCLAIMER_FULL:
- **Personalisation:** scores don't account for individual situation, tax, risk tolerance
- **Model Limitations:** quantitative models may fail in regimes not in training period
- **Conflicts of Interest:** QNTM holds no positions, receives no issuer compensation

---

## Pre-Launch Checklist

### Blocking Revenue
- [ ] **Fintech lawyer review** — contact: Mark (texted May 21). Questions: (1) IA status under IAA 1940, (2) HIGH/MOD/LOW label adequacy, (3) disclaimer language, (4) California DFPI considerations, (5) sole proprietor vs LLC before taking payment
- [ ] **Stripe integration** — `STRIPE_SECRET_KEY` + `STRIPE_PRICE_ID_PRO` + webhook to update `user.plan`

### Before June 1
- [ ] `st.components.v1.html` → replacement API (defer until Streamlit ships stable replacement)

### Polish
- [ ] Screener mobile card truncation — pillar scores cut off on narrow phones (Full Universe tab)
- [ ] Performance chart on Model Portfolio — re-add when model builds positive alpha track record

---

## Cost Structure (all $0/mo)
- Streamlit Cloud, Supabase, GitHub Actions, cron-job.org, yfinance — all free tier
- **Cost triggers:** first paying users → Streamlit ~$20/mo; ~500 users → Supabase ~$25/mo

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

---

## Known Issues / Watch-outs
- yfinance rate limits during market hours — intraday uses 0.5s sleep between 200-ticker chunks
- `signal_log.macro_overlay` is numeric — do NOT write regime strings to it
- `st.components.v1.html` deprecation warning in logs — cosmetic only until June 1
- GitHub Actions free tier scheduler unreliable for crons — cron-job.org is the reliable trigger
- cron-job.org PAT expires May 2027 — set calendar reminder
- Model portfolio entry prices seeded at 2AM UTC May 19 — may reflect May 18 close for some tickers
- Model portfolio currently tracking -3.5% vs SPY (2 days in, energy-heavy portfolio, volatile macro)

---

## Session State Keys
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
```
?page=model     → public model portfolio track record
?legal=privacy  → Privacy Policy
?legal=terms    → Terms of Service
?legal=cookies  → Cookie Policy
?ck=1           → cookie consent accepted
?uid=&plan=     → session restore (HMAC-signed JWT)
?nav=signin     → sign in page
?nav=register   → register page
```

---

## Output Files Location
Production: `andymcalister/QNTM` — `main` branch
Dev: `andymcalister/QNTM` — `dev` branch
Push to `dev` only during development, merge to `main` for prod releases.
Always use the most recently downloaded `app.py` as the base for the next session — do not re-upload from the repo as it may be missing recent changes.
