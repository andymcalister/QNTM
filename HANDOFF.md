# QNTM Platform — Handoff Summary
*Updated: May 17, 2026*

## What It Is
QNTM is a quantitative conviction factor model platform for retail investors. Bloomberg terminal aesthetic, dark theme. Live at **qntmmvp.streamlit.app** (prod) and **qntm-dev.streamlit.app** (dev).

---

## Tech Stack
- **Frontend:** Streamlit (Python), custom HTML/CSS throughout
- **Database:** Supabase (PostgreSQL) at `zqrudkoqhsjsltpefgcl.supabase.co`
- **Auth:** bcrypt + TOTP MFA, AES-256 encryption, 30-day localStorage remember-me
- **GitHub:** `andymcalister/QNTM` — `main` → prod, `dev` → dev
- **Files:** `app.py` (~5000 lines), `model_engine.py`, `db.py`, `data_refresh.py`, `proper_backtest.py`, `schema.sql`

---

## Model
- **Universe:** 963 tickers (S&P 500 + Russell 1000)
- **5 Pillars:** Momentum 30%, Quality 30%, Value 20%, Volume 10%, Sentiment 10%
- **Signals:** BUY ≥60, HOLD 45–59, SELL <45 (dynamic threshold raises to 65 when >30 stocks score ≥60)
- **Macro overlay:** Regime-scaled — 35% weight RISK_OFF, 15% RISK_ON, 10% NEUTRAL
- **Macro detection:** Yahoo Finance RSS + FRED RSS + yfinance VIX + WTI crude (no API keys needed)
- **Backtest:** Walk-forward, real prices, 10bps transaction costs, 124 tickers × 20 quarters
- **Results:** +347% raw / +307% adj vs SPY +131% · Sharpe 1.72 · Sortino 10.53 · Max DD 6.5% vs SPY 25.4% · 85% win rate
- **Tiers:** Free and Pro ($29/mo, Stripe stub in place)

---

## Key Architecture Decisions

### Streamlit Rendering Rules
- All custom HTML rendered as string variables first, then `st.markdown(html, unsafe_allow_html=True)` — never multiline f-string markdown with inline conditionals
- **CRITICAL: `st.markdown` strips ALL `<script>` tags** — any JS must go in `st.components.v1.html()` which runs in an iframe. Use `parent.document` to access the main page DOM from that iframe
- No HTML comments `<!-- -->` inside `st.markdown` — Streamlit strips them and breaks surrounding content
- **Nested f-strings with `{}` in variables cause silent failures** — when building HTML that contains CSS `{}` or format strings, use string concatenation (`+`) not f-string embedding

### Mobile Layout Rules
- Don't use `st.columns()` for content that needs to reflow on mobile — use CSS `grid-template-columns: repeat(auto-fit, minmax(Xpx, 1fr))` instead
- `st.radio(horizontal=True)` works well for nav tabs — native Streamlit handles mobile wrapping
- Tooltips must use `position:fixed` with JS `getBoundingClientRect()` — `position:absolute` bleeds off-screen due to parent `overflow:hidden`
- `st.components.v1.html(height=0)` iframes are hidden via CSS: `iframe[height="0"] { display:none !important; }`
- Buttons with `st.columns([1,8])` or narrow columns cause vertical text — avoid for nav/action buttons

### Auth & Session
- **30-day localStorage token** — written on every login (no checkbox), uses `_write_localstorage_token(uid, plan)`
- **Session restore priority:** URL `?uid=` param is checked first (always), localStorage fires second via `_inject_localstorage_reader()`
- **`signed_out` flag** — only blocks localStorage restore within same session, not across browser refresh. Fresh loads with `?uid=` always attempt restore regardless of `signed_out`
- **JWT stub** — `_sign_token()` currently returns plain uid (JWT failed due to base64 `.` collision with token format). JWT is a pending task
- `go(page)` preserves `uid`/`plan` in URL query params on every navigation

### CSS Global Rules
- Global CSS is in one large `st.markdown("""<style>...</style>""")` block at top of file
- Font sizes in inline `style=""` attributes override global CSS — must be changed directly in the HTML strings
- Key color palette: `#00ff87` (green/BUY), `#fbbf24` (yellow/HOLD), `#ef4444` (red/SELL), `#d4a843` (gold/accent), `#94a3b8` (secondary text), `#cbd5e1` (primary text)

---

## Session State Keys (important ones)
```python
logged_in, user, mfa_verified, scan_results, macro_data,
page, nav, cookies_accepted, signed_out, remember_me,
pending_mfa_user, pending_mfa_secret, mfa_recovery_mode,
show_mfa_setup, force_mfa_setup, legal_doc, auto_upgrade,
onboarding_done, onboarding_step, port_period, last_refresh,
live_refresh_running
```

---

## Routing
```python
?page=model     → public model portfolio (no auth, no cookie gate)
?legal=privacy  → Privacy Policy
?legal=terms    → Terms of Service
?legal=cookies  → Cookie Policy
?ck=1           → cookie consent accepted (persists across sessions)
?uid=&plan=     → session restore (uid = plain uid for now)
?nav=signin     → route to sign in page
?nav=register   → route to register page
```

---

## Supabase Tables
`users`, `holdings`, `signal_log` (has `price` column), `notifications`, `backtest_cache`, `fundamentals_cache`, `signal_snapshots`

**signal_snapshots** stores `{ticker: {action, score, was_gem}}` per user for cross-session deterioration detection.

---

## What Was Built This Session (May 17, 2026 — Session 2)

### Cron + Seeding + Search Resolver
- ✅ **GitHub Actions nightly cron** — `.github/workflows/nightly_refresh.yml` on `dev` branch. Runs `data_refresh.py` at 2:00 AM UTC daily (after US market close). Supports `workflow_dispatch` with `--force` and `--tickers` inputs. Exits non-zero and surfaces error on refresh failure.
- ✅ **Track record seeder** — `seed_track_record.py`. One-shot local script that backfills all 20 quarters (Q2 2020 → Q1 2025) into `signal_log` with real entry dates. Supports `--dry-run`, `--force`, `--quarter`. Safe to re-run (skips existing rows by default). Tags seeded rows with `seeded: true` for auditability.
- ✅ **Screener search name resolver** — `app.py` screener search box now calls `resolve_ticker()` before scoring. Accepts "Tesla", "Nvidia", "Goldman" etc. Shows `✓ TICKER — Company Name` green preview on successful resolution. Consistent with Add Position flow. Placeholder updated to `e.g. AAPL, Tesla, Nvidia...`
- ✅ **Pillar weight doc fix** — HANDOFF and README showed stale v1.0 weights. Corrected to match `model_engine.py` v2.0: Momentum 30%, Quality **30%**, Value **20%**, Volume **10%**, Sentiment 10%.

---

## What Was Built This Session (May 17, 2026)

### Beta Readiness Features
- ✅ **Onboarding flow** — 3-step inline card modal for new users (no holdings). `show_onboarding()` + `st.stop()` pattern. Skippable, never shows again once holdings exist
- ✅ **Page summaries** — consistent `page_summary(icon, title, subtitle, pills)` header on every nav page (Screener, Gems, Backtest, Portfolio, Alerts, Account)
- ✅ **Data freshness banner** — green/amber badge on screener showing when data was last refreshed, with rescan prompt if stale
- ✅ **Empty states** — Portfolio and Alerts both have rich empty states with CTAs instead of blank screens
- ✅ **Rescan + Live Refresh** — buttons added directly under BUY/HOLD/SELL stat strip on screener (always visible, not buried in Full Universe tab)
- ✅ **Ticker/Name resolver** — Add Position input accepts company names ("Tesla") and resolves to ticker (`TSLA`) via `resolve_ticker()`. Shows green preview before adding
- ✅ **JWT stub** — `_sign_token()` / `_verify_token()` infrastructure in place, currently passthrough. Replace with real HMAC-SHA256 signing once tested separately

### Mobile Fixes (extensive)
- ✅ Landing page: all `st.columns` replaced with CSS grids, no horizontal scroll
- ✅ Pricing cards: `repeat(3,1fr)` compact, fit on screen
- ✅ Platform nav: `st.radio(horizontal=True)` — no vertical text
- ✅ Sign Out: standalone button below nav radio
- ✅ Screener filters: 2-row layout (3 dropdowns + 2 buttons)
- ✅ Screener stat strip: `UNIV` label, 18px font, no overflow
- ✅ Top 10 table: 3-col layout (TICKER/COMPANY/SCORE) fits mobile
- ✅ Backtest: 2×2 CSS grids for stat cards
- ✅ Hidden Gems: CSS `auto-fit` grid, string concatenation (no f-string brace conflicts)
- ✅ Portfolio: 2-row Add Position form, period buttons as `st.columns` + active underline
- ✅ Portfolio holding card: pillar bars in 2×2 grid, score boxes `repeat(4,1fr)`
- ✅ Remove button: full-width `🗑 Remove TICKER`
- ✅ Tooltip: `st.components.v1.html()` JS with `position:fixed` + `getBoundingClientRect()`, touch support

### Auth Fixes
- ✅ 30-day token written on every login (no checkbox)
- ✅ `signed_out` no longer blocks restore on fresh page load with `?uid=` param
- ✅ `go()` preserves `uid`/`plan` in URL on every navigation
- ✅ Legal pages bypass cookie consent gate
- ✅ `factor_panel_html` function restored after accidental deletion

### Visual / UX
- ✅ Global font size pass — 513 inline style replacements (9→12px, 10→13px, 11→13px)
- ✅ Global color brightness pass — `#475569`→`#94a3b8`, `#334155`→`#64748b` throughout
- ✅ Button font: 11px → 13px
- ✅ Components iframe hidden (`display:none`) to remove visible box artifact
- ✅ Dead `<script>` tags removed from `st.markdown` blocks

---

## Pending Build Queue (in priority order)
1. **Run seed_track_record.py locally** — one-time command: `python seed_track_record.py`. Seeds all 20 quarters of historical signal_log data. Run before first beta user touches the Alerts/Portfolio pages.
2. **Add GH Actions secrets** — add `SUPABASE_SERVICE_KEY` (not just anon key) to the `dev` repo secrets in GitHub Settings → Secrets. The cron uses service key for writes.
3. **JWT signed token** — replace `_sign_token()` passthrough with real HMAC-SHA256. Use `|` as separator (URL-encoded `%7C`) to avoid base64 `.` collision.
4. **Stripe integration** — upgrade button exists, stub in place. Needs `STRIPE_SECRET_KEY` + `STRIPE_PRICE_ID_PRO`
5. **SendGrid email notifications** — infrastructure ready in Supabase. Needs `SENDGRID_API_KEY`
6. **Screener full universe mobile** — stock cards still cut off pillar scores on far right on narrow phones

---

## Secrets Required (Streamlit Cloud)
```toml
SUPABASE_URL = "https://zqrudkoqhsjsltpefgcl.supabase.co"
SUPABASE_ANON_KEY = "..."
ENCRYPTION_KEY = "gvRXtS0L-DqgRu9ieMvt9oxMgPdCChFCsUx-qgyGXd0="
ENVIRONMENT = "dev"   # dev app only — omit for prod
```

---

## Key Functions Reference
```python
factor_panel_html(r, is_gem, company_info)  # Full stock card HTML — DO NOT DELETE
resolve_ticker(query)                        # Name→ticker resolver ("Tesla" → "TSLA", "TSLA") — used in screener + Add Position
get_company_info(ticker)                     # Ticker→name lookup with yfinance fallback
page_summary(icon, title, subtitle, pills)   # Consistent page header
data_freshness_banner()                      # Green/amber data age badge
show_onboarding()                            # 3-step new user flow (calls st.stop())
_sign_token(uid, plan)                       # Currently passthrough — replace with JWT
_verify_token(token)                         # Currently passthrough — replace with JWT
_write_localstorage_token(uid, plan)         # Writes 30-day token to localStorage
go(page)                                     # Navigate + preserve uid/plan in URL
nav(section)                                 # Switch platform nav section
```

## New Files (Session 2)
```
.github/workflows/nightly_refresh.yml   # GH Actions cron — runs data_refresh.py at 2AM UTC daily
seed_track_record.py                    # One-shot historical signal_log seeder (run locally before beta)
```

---

## Output Files Location
Current production version at `andymcalister/QNTM` — `main` branch.
Dev version at `andymcalister/QNTM` — `dev` branch.
