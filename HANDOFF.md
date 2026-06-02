# QNTM Platform — Handoff Summary
*Updated: May 31, 2026 (late — live intraday macro engine shipped; prod migrated to Render at qntm.live)*

## What It Is
QNTM is a quantitative conviction factor model platform for retail investors. Dark institutional aesthetic, dark theme.

**Deployments:**
- **Prod: `qntm.live`** (apex) — hosted on **Render** (service `qntm-opbn.onrender.com`, Starter plan ~$7/mo always-on), tracks `main`, **auto-deploys on push** via `render.yaml` (blueprint). `www.qntm.live` also configured. SSL auto-provisioned by Render. Secrets live in a Render **Secret File** mounted at `.streamlit/secrets.toml` (the `startCommand` copies it from `/etc/secrets/secrets.toml`).
- **Dev: `qntm-dev.streamlit.app`** (dev branch) — still on Streamlit Cloud, active dev target.
- **GitHub:** `andymcalister/QNTM`
- **Domain note:** the project moved off `qntm.app` → **`qntm.live`** this session (all refs swept). Old prod Streamlit app `qntmmvp.streamlit.app` is now SUPERSEDED by Render — decommission it once qntm.live is stable a few days (kills the auto-rebuild-to-new-Streamlit risk).

**Standard push (dev — Streamlit Cloud):**
```bash
git push origin main:dev
git commit --allow-empty -m "chore: force rebuild" && git push origin main:dev
# then reboot dev app (Manage app → ⋮ → Reboot) + hard-refresh
```

**Push to prod (Render — NO reboot needed):**
```bash
git push origin main
# Render auto-deploys main within ~1-2 min. No force-rebuild, no manual reboot.
```
Note: local commits are made on `main`; `main:dev` pushes that branch to the `dev` remote. Prod and dev share the same Supabase project, so run migrations once.

**FILE-LOCATION GOTCHA (cost hours on May 31):** GitHub Actions workflows are ONLY read from `.github/workflows/`. A `nightly_refresh.yml` dropped in the repo root does nothing. When updating the workflow, the file MUST land at `.github/workflows/nightly_refresh.yml` — verify with `grep -c "macro:" .github/workflows/nightly_refresh.yml` (must be ≥1) BEFORE committing. Also: always eyeball `git diff --stat` before committing — an `app.py` change in the tens of lines is normal; thousands of lines means the wrong (ancient) file got copied in.

---

## Tech Stack
- **Frontend:** Streamlit (Python) **>=1.56** (bumped this session off the deprecated `st.components.v1.html`), custom HTML/CSS
- **Hosting:** prod on **Render** (web service, blueprint via `render.yaml`); dev on Streamlit Cloud
- **Database:** Supabase (PostgreSQL, **Pro plan** — daily backups, no auto-pause) at `zqrudkoqhsjsltpefgcl.supabase.co`
- **Auth:** bcrypt + TOTP MFA, HMAC-SHA256 JWT tokens, 30-day localStorage remember-me
- **`qntm_html()` wrapper** (defined in app.py after `set_page_config`): version-safe replacement for `st.components.v1.html`. On Streamlit ≥1.56 it routes JS-only payloads (height=0) to inline `st.html(..., unsafe_allow_javascript=True)` and the one self-contained backtest chart (height>0, `iframe=True`) to `st.iframe`; falls back to `components.html` on <1.56. All 8 prior call sites migrated. Reason for inline-not-iframe: `st.iframe` rejects height=0, and inline run lets `window.parent`/`parent.document` resolve to the top window.
- **Refresh jobs:** three modes — nightly full, intraday price, live macro (see **Refresh Architecture** below). Triggered by GitHub `schedule` + cron-job.org `workflow_dispatch`. GitHub PAT in the cron-job.org Authorization header (expires May 2027).

---

## Model
- **Universe:** 834 tickers (S&P 500 + Russell 1000)
- **5 Pillars:** Momentum 30%, Quality 25%, Volume 20%, Value 15%, Sentiment 10%
- **Signals:** HIGH ≥60, MODERATE 45–59, LOW <45. **The `signal` column in signal_log now stores HIGH/MODERATE/LOW** (normalized this session from 8 legacy vocabularies — BUY/HOLD/SELL/STRONG ALIGN/HIGH ALIGN/LOW ALIGN/WEAK/NEG). `signal_legacy` column holds the originals for rollback. `model_engine` writes HIGH/MODERATE/LOW going forward. The internal `adj_action` enum (BUY/SELL/HOLD) is STILL used in code for portfolio/promotion logic but is NEVER displayed — always converted to conviction labels. No buy/hold/sell instructional language anywhere user-facing.
- **Macro overlay:** regime-scaled quant/macro blend. Macro weight by regime: RISK_OFF/HIGH VOLATILITY 25–35%, RISK_ON/MILDLY BULLISH 15%, NEUTRAL 10% (in `apply_macro_overlay`). `adj_composite` = quant composite reweighted by sector overlay.
- **Backtest:** +347% adj vs SPY +131% · Sharpe 1.72 · Max DD 6.5% · 85% win rate

---

## Refresh Architecture — THREE modes (shipped May 31)

One workflow (`.github/workflows/nightly_refresh.yml`), one script (`data_refresh.py`), three modes selected by env/flag. The entrypoint routes: `MACRO_RUN`/`--macro` → `run_macro_refresh`; else `INTRADAY_RUN`/`--intraday` → `run_intraday_refresh`; else → `run_refresh` (full).

| Mode | Function | What it does | Trigger | Writes |
|---|---|---|---|---|
| **Full** | `run_refresh` | Re-fetch all 834 tickers' fundamentals+prices, full re-score, live macro scan, write everything. Skips if `cache_is_fresh()` (≈20h) unless `--force`. | GitHub `schedule: 0 2 * * *` (2 AM UTC) | all signal_log cols + macro_state |
| **Intraday** | `run_intraday_refresh` | Price + momentum only (~834 yfinance, ~90s). No fundamentals, no live macro scan (reads persisted `macro_state`). | cron-job.org, every 30 min **Mon–Fri market hours** (ET), body `{"ref":"main","inputs":{"intraday":"true"}}` | price/composite/momentum |
| **Macro** | `run_macro_refresh` | Lightweight live macro re-scan (RSS + VIX + WTI, ~6 calls, ~10–30s). Re-applies sector overlay to today's existing scores. NO ticker re-fetch. | cron-job.org, every 30 min **all week, extended hours** (~4 AM–9 PM PT), body `{"ref":"main","inputs":{"macro":"true"}}` | adj_composite/signal/macro_overlay + macro_state |

**Why macro is its own mode (the May 31 ask):** intraday was price-only, so a daytime macro/geopolitical event (e.g. Iran headline) couldn't move scores until the next nightly run. `run_macro_refresh` fixes that — it re-scans news/macro and re-applies the overlay every 30 min.

**Collision-safe:** the macro pass writes ONLY `adj_composite`, `signal`, `macro_overlay`; the price pass owns `price`/`composite`/`momentum`. Disjoint columns → the two cron jobs can fire at the same instant with no clobbering (no schedule offset needed).

**`macro_state` table (single source of truth):** `run_macro_refresh` and `run_refresh` both persist the live overlay dict to `macro_state` (single row, id=1, JSONB `overlay`). `_load_macro_state()` reads it. The **app reads `macro_state` for the banner** (via `_live_macro()` in app.py — every former in-process `fetch_macro_overlay()` call now routes through it), so the displayed regime always matches the `adj_composite` scoring AND page loads no longer each hit the RSS/VIX/WTI feeds. Falls back to a live scan only if `macro_state` is empty.

**News summary:** `fetch_macro_overlay` now returns `summary` (human-readable, e.g. "Risk Off — War Escalation, Oil Spike (VIX 31.2, WTI $98). 47 live headlines scanned.") and `event_labels`. The banner renders `summary` as a "News read:" line.

**`INTRADAY_RUN`/`MACRO_RUN` are driven by the dispatch INPUT, not `github.event.schedule`.** Original bug (May 31): the workflow keyed `INTRADAY_RUN` off `github.event.schedule == '...'`, but cron-job.org triggers via `workflow_dispatch` where that field is empty → always ran full refresh → cache-skip → timestamp never advanced. Fixed: workflow_dispatch `inputs.intraday`/`inputs.macro` → env. The workflow's high-frequency GitHub `schedule` crons were removed; cron-job.org owns intraday+macro, GitHub `schedule` keeps only the 2 AM full run.

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

**`st.button` is OK for:** Sign In, Create Account, MFA verify, Add holding, Mark read, MFA setup, one-click Cancel subscription (account page, server-side mutation).

### 1b. CARD RENDERING — `st.markdown` + native `<details>` (NOT iframes)
**This is the proven pattern; reach for it first, do not use `st.components.v1.html` iframes for stock cards.** Established after a long debugging saga (see May 30 session). The full reasoning:

- Stock cards render via `factor_panel_html(r, ..., as_details=True)` which returns a native HTML `<details name="qntm-cards">` element, rendered with `st.markdown(unsafe_allow_html=True)`.
- **Why not iframes:** cards were previously wrapped in `st.components.v1.html` iframes. That caused three compounding bugs — (a) fixed iframe height clipped expanded card content, (b) the resize JS (`setFrameHeight`) didn't reliably grow the iframe on expand, (c) action-button links **inside** an iframe cannot navigate the parent (sandbox blocks `target=_top`, `window.top.location`, and `window.open`). Every attempt to satisfy "button works AND no clip" failed because button-inside-iframe can't navigate and button-outside-iframe clips.
- **The fix:** no iframe at all. `<details>`/`<summary>` gives native click-to-expand (no JS, no clipping, grows naturally in the page). The action button is a plain `target="_self"` link in the main document, so it reaches the router like any other URL action.
- **One card open at a time:** all cards share `name="qntm-cards"` (native exclusive-accordion in modern browsers) PLUS a JS fallback in `page_platform()` that closes siblings on open (reaches `parent.document`).
- **Performance:** build all cards for a list into one string via `build_card_html(...)` and render with a single `render_cards_batch(html)` (one `st.markdown`), NOT one `st.markdown` per card. Used on screener Top-10, Full Universe, Gems, Watchlist.
- Helpers: `build_card_html(r, nav, is_gem, company_info, in_list, extra_detail, remove_url, mode)` returns HTML; `render_card_with_watchlist(...)` renders one; `_card_action_button(tk, mode, nav, in_set, uid, pln, remove_url)` builds the styled link. `mode` ∈ `watchlist` / `portfolio` / `simulator`.
- Tradeoff accepted: the action button navigates (full page rerun) on click. `st.button` (rerun, wipes mobile session) and `fetch` (CORS-blocked in sandbox) were both rejected. Reload cost was mitigated by throttling the per-render freshness DB checks (see perf work).

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
- `scan_results` reused across reruns; a signal_log freshness check (is there a newer nightly batch?) runs at most once per 5 min per session (throttled — was per-render, which slowed every button click). Header "updated" date cached per session.
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
- `sector` → `SECTORS.get(ticker, "Unknown")` from `model_engine`. NOTE: `run_macro_refresh` attaches sector from `load_cached_fundamentals(max_age_hours=48)` (the fundamentals JSONB carries `sector`) so the overlay maps correctly on the read side. The macro pass writes ONLY `adj_composite`/`signal`/`macro_overlay` (disjoint from the price pass — see Refresh Architecture).
- `adj_action` → `"BUY" if adj>=60 else "SELL" if adj<45 else "HOLD"` (internal enum, never displayed)
- `pct_rank` → computed in `factor_panel_html` on the fly from the session `scan_results` distribution when missing (watchlist/portfolio rows from signal_log lack it; otherwise they'd all show "50th"). Falls back to 50 only if no scan in session.

---

## Free Tier Gating
- **Full Universe:** top 50 results shown, gate banner + gold CTA after
- **Gems, Simulator, Alerts:** full page gate, CTA routes to `page_upgrade`
- **page_upgrade:** shows pricing, "Claim Founding Member" gold CTA → `upgrade=pro` URL action → router upgrades → redirect back
- **When Stripe ready:** replace `upgrade_plan()` in router with Stripe checkout redirect

---

## Upgrade Flow + ARL Compliance (pre-Stripe)

**Current live flow ($0 Founding Member):**
1. Free user hits gate → sees wall
2. Clicks gold CTA → `?upgrade_page=1&feature=X&return_nav=Y`
3. Router sets `page=upgrade`, `upgrade_feature`, `upgrade_return_nav`
4. `page_upgrade()` renders pricing + "Claim Founding Member Access" gold link
5. Click → `?upgrade=pro&qnav=Y` → router calls `upgrade_plan()` → session updated → redirects to feature

**California ARL (AB 2863) machinery is built but GATED.** The $0 Founding flow has no auto-renewal, so ARL doesn't attach yet. All ARL checkout pieces activate when `st.session_state._paid_trial_mode = True` (flip this from the Stripe wiring):
- **1A initial notice** — 6-element §17602(a)(8) disclosure block renders ON the upgrade page before the button (`arl.initial_notice_html()`).
- **1B affirmative consent** — separate unchecked `st.checkbox` (verbatim label) gates the "Start free trial" button.
- **1C consent log** — `arl.log_consent()` writes append-only row to `arl_consent_log` on confirm.
- **1D acknowledgment email** — `arl.send_acknowledgment()` (stubbed send + logged).

**Cancellation (account page) is now ARL-compliant:** true one-click Cancel for paid users (`billing_active`) — single visible button, immediately stops next renewal, confirmation message states access-to-period-end, confirmation email sent+logged. No expander maze, no two-step confirm (that was removed). Founding members get an informational note.

**`arl.py` module** holds all compliance copy/logic: consent logging, notice logging (`notices_sent`), email templates (acknowledgment, annual reminder, price change, material change, cancellation confirmation), stubbed `_send_email`, and `run_annual_reminders()` cron (`python arl.py annual_reminders`). Bump `TERMS_VERSION`/`CONTENT_VERSION` when copy changes.

## Stripe Billing — BUILT & WORKING IN SANDBOX (May 30)
Full 7-day-trial → $29/mo subscription lifecycle works end-to-end in Stripe **sandbox**: checkout, trial, paid/Founder distinction, trial countdown, cancel, self-healing sync. Module: `stripe_billing.py`. Integration style: **Stripe Checkout (hosted redirect)** — NOT Payment Element (iframe conflicts with Streamlit). State sync: **polling** (no webhook server — Streamlit can't receive POSTs).

**Secrets (dev has them; prod does NOT yet):**
```toml
STRIPE_SECRET_KEY = "sk_test_..."          # sandbox secret key
STRIPE_PRICE_ID_PRO = "price_1TcumNPiKYrkolEYwFb8u3qE"   # sandbox $29/mo recurring price
```
Both MUST be from the SAME Stripe environment (sandbox key + sandbox price). Mismatch → "No such price" / "Invalid API Key". The 7-day trial is applied in CODE (`trial_period_days:7` in `create_checkout_url`), NOT on the dashboard price — there's no trial option on the price, that's expected.

**`stripe_billing.py` functions:** `create_checkout_url`, `finalize_checkout(user_id, email)` (email-first lookup, version-safe), `poll_subscription_status`, `cancel_subscription` (cancel_at_period_end=True), `reactivate_subscription`, `status_grants_access`, `last_error()`. All use the `_g()` getattr helper — **Stripe objects don't reliably support `.get()` across SDK versions; use `_g(obj, attr)` not `obj.get(attr)`**.

**db.py:** `set_stripe_billing` / `get_stripe_billing` store stripe_customer_id / stripe_subscription_id / billing_active / stripe_status / trial_end / current_period_end in the `users.notifications` JSON blob (no migration).

**Flow:** free user → upgrade page → ARL notice + consent checkbox → "Start free trial" button → `create_checkout_url` → `st.link_button` to Stripe → pay (test card `4242 4242 4242 4242`) → return `?checkout=success` → `finalize_checkout` sets billing_active + flips to Pro + fires ack email. Founder-supporter path is the same but from `page_account`, logs consent as plan `pro_supporter`.

**`_paid_trial_mode` auto-enables when `billing_configured()` is true** (keys present), so the ARL checkout activates automatically once Stripe secrets are set.

**Self-heal poll:** once-per-session, syncs plan from live Stripe status. Gated behind `_awaiting_checkout` counter (set to 3 on Start-trial click) so it does NOT fire a Stripe email lookup for every free user on every load (that bug stalled the page). Decrements per load.

### CHECKOUT BUTTON — known state & the unfinished bit
- Currently uses **`st.link_button`** → opens Stripe in a **NEW TAB**. This WORKS. Accepted for now.
- The white-button-after-click and new-tab are cosmetic/UX nits left unfixed by choice (May 30, after a long debugging loop).
- **Same-tab is solvable** but was deferred: the proven pattern is the card buttons' `window.open(url,'_top')` inside a `components.v1.html` iframe (see ~line 1704; plain `<a target=_top>` and `window.top.location` are BLOCKED by the sandbox, `window.open(_top)` is permitted). A `_render_checkout_button()` helper using this exists in git history. When revisiting: push it, then **verify deploy is current (`git log origin/dev`) and FULL REBOOT before judging** — stale deploys caused most of the May 30 confusion, not the code.

## What's left before LIVE payments
1. **Bank account** (Mercury) → needs Articles of Organization approval (filed, pending state). Stripe payout needs it. Sandbox needs nothing, so dev testing is unblocked.
2. **Swap sandbox keys → live keys** (`sk_live_...`) + recreate product/price in live mode. Sandbox data doesn't carry over.
3. **Stripe account activation** (needs bank).
4. **Wire `arl._send_email` to SendGrid** — currently stubbed (logs intent, `notices_sent.delivered=False`).
5. **Fintech-attorney review** of ARL copy + consent/cancel UI + Founder-supporter path + trading policy + disclosures — THE GATE before paying users. Do not go live until counsel signs off.
6. **Add Stripe webhooks** eventually (replaces polling lag) — optional, polling is fine for launch.
7. Add `STRIPE_*` + `SUPABASE_SERVICE_KEY` secrets to PROD when going live.

---

## Supabase Tables
`users`, `holdings`, `signal_log`, `notifications`, `backtest_cache`, `fundamentals_cache`, `signal_snapshots`, `model_portfolio_positions`, `watchlists`, `watchlist_items`, `arl_consent_log`, `notices_sent`, `signal_batch_audit`, `macro_state`

**Migrations (run in Supabase SQL editor; prod+dev share one project):**
- `macro_state.sql` — single-row live macro overlay table (id=1, JSONB `overlay`, public-read RLS). **Run May 31.** Written by `run_macro_refresh`/`run_refresh`, read by the app banner.
- `migrations/atomic_publishing.sql` — batch_id/published_at columns, append-only `signal_batch_audit`, `publish_signal_batch` RPC (atomic batch swap). NOTE: still need to wire `publish_signal_batch()` into `run_refresh` to activate atomicity.
- `migrations/arl_compliance.sql` — `arl_consent_log` + `notices_sent` (both append-only, UPDATE/DELETE blocked by trigger).
- Signal normalization (3 SQL blocks, run on backup): add `signal_legacy`, UPDATE `signal` from adj_composite to HIGH/MODERATE/LOW, verify.

### watchlists + watchlist_items (multi-list, replaced old user_watchlist)
Named lists per user with FK items. `watchlist_items` carries `price_at_add` for "since added" P&L. Legacy `get_watchlist/add/remove` shims redirect to the user's default list.

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
- `factor_panel_html(r, is_gem, company_info, wl_btn=, as_details=)` — full score card HTML incl WHY THIS SCORE. `as_details=True` returns a native `<details>` card (current pattern); `wl_btn` injects the action button inside the detail.
- `build_card_html(...)` — returns one card's HTML for batching; `render_cards_batch(html)` renders many in one `st.markdown`; `render_card_with_watchlist(...)` renders one.
- `_card_action_button(tk, mode, nav, in_set, uid, pln, remove_url)` — styled `target="_self"` action link; `mode` ∈ watchlist/portfolio/simulator.
- `_build_why_html(r)` — plain-English score explanation (standalone helper, used everywhere)
- `signal_history_chart(ticker, current_score)` — SVG sparkline from signal_log
- `resolve_ticker(query)` — company name → ticker (KNOWN dict + yfinance fallback)
- `_get_supabase()` from `data_refresh` — uses SERVICE_KEY (not anon)
- `arl.py` — ARL compliance module (consent/notice logging, email templates, stubbed sender, annual-reminder cron)
- `stripe_billing.py` — Stripe Checkout/trial/cancel/poll module (see Stripe Billing section). Use `_g()` not `.get()` on Stripe objects.

---

## Secrets Required
```toml
SUPABASE_URL = "https://zqrudkoqhsjsltpefgcl.supabase.co"
SUPABASE_ANON_KEY = "..."
SUPABASE_SERVICE_KEY = "..."
ENCRYPTION_KEY = "gvRXtS0L-DqgRu9ieMvt9oxMgPdCChFCsUx-qgyGXd0="
ENVIRONMENT = "dev"   # dev deployment only; prod omits or sets "prod"
```
**Outstanding:** rotate Supabase keys before paid launch (flagged repeatedly).
**Where secrets live now:** dev = Streamlit Cloud secrets; **prod = Render Secret File** mounted at `.streamlit/secrets.toml` (must include `SUPABASE_SERVICE_KEY` — ARL logging, atomic publish, freshness checks, and the macro pass all use the service-key client). **GitHub Actions** (the refresh jobs) has its own repo secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ENCRYPTION_KEY`. `STRIPE_*` stays OFF prod until go-live.

---

## Pre-Launch Checklist
- [x] **QNTM LLC** — Articles of Organization FILED (pending state approval). EIN + business email obtained.
- [x] Stripe integration built & working in SANDBOX (Checkout + 7-day trial + cancel + Founder-supporter); validated end-to-end on dev May 31. Prod stays GATED (no STRIPE_* secrets) until go-live.
- [x] Signal vocabulary normalized to HIGH/MODERATE/LOW (code + DB)
- [x] ARL machinery built (auto-on when Stripe configured)
- [x] **Prod migrated to Render at qntm.live** (May 31) — always-on, custom domain, SSL, auto-deploy
- [x] **Supabase upgraded to Pro** (May 31) — daily backups, no auto-pause (PITR add-on NOT enabled; unnecessary)
- [x] **Streamlit ≥1.56 migration** — off deprecated `st.components.v1.html` (June-1 deprecation resolved)
- [x] **Live intraday macro engine** shipped (May 31) — `run_macro_refresh`, `macro_state`, banner reads it, news summary
- [x] **Intraday + macro crons live** — cron-job.org jobs verified (intraday Mon–Fri market hours; macro all-week extended hours)
- [x] qntm.live mailboxes (hello@/legal@/billing@/privacy@/security@ → admin@), receiving only
- [ ] **Bank account (Mercury)** — blocked on Articles approval; needed for Stripe payout
- [ ] **Swap Stripe sandbox → live keys** + recreate $29 product/price in live mode (needs bank + account activation); add `STRIPE_*` to PROD secrets ONLY at go-live
- [ ] **Fintech lawyer review** — IAA 1940 publisher's exclusion, ARL copy + consent/cancel UI, Founder-supporter path, conflicts disclosure, trading policy, disclaimers, CA DFPI. THE GATE before paying users. (Counsel engaged; will forward `QNTM_POLICIES_FINAL.md`.) Disclaimer/label finalization is gated on their feedback.
- [ ] Wire `arl._send_email` to SendGrid (stubbed) + SPF/DKIM/DMARC on qntm.live for sending
- [ ] Rotate Supabase keys
- [ ] Wire `publish_signal_batch()` into `run_refresh` (atomic publishing)
- [ ] **SEO: split marketing site from app** (NEXT PROJECT — see Next Session)
- [ ] (optional) Decommission old prod Streamlit app `qntmmvp.streamlit.app` once qntm.live is stable a few days
- [ ] (optional) iPhone home-screen icon via edge-served `apple-touch-icon.png` (180px file ready; Streamlit doesn't serve it)
- [ ] (optional) Stripe webhooks to replace polling lag; same-tab checkout button

## Next Session
**Primary next project: SEO — split the marketing site from the app.** qntm.live currently serves the Streamlit SPA, which returns an empty JS shell to crawlers (title "Streamlit", body "enable JavaScript") → effectively zero indexable content. The fix is the standard SaaS split: a real static/SSR landing page on the apex `qntm.live` (Astro on Cloudflare Pages recommended — zero-JS, free, sits next to Render) with proper title/meta/OG/`SoftwareApplication`+`Organization`+`WebSite` schema and the competitor matrix as crawlable HTML; move the Streamlit app to `app.qntm.live` (add the subdomain in Render → Custom Domains; repoint apex DNS to the static host, add `app` CNAME → `qntm-opbn.onrender.com`). Estimated SEO score jumps ~18→65–75.
- **Brand collision is real and in-vertical:** ticker `QNTM` = **Quantum BioPharma** (NASDAQ/CSE) dominates all finance SERPs; also Sam Hughes (qntm.org, sci-fi author) + QNTM Group (MarTech). Don't chase bare "qntm" — target "QNTM quantitative conviction model / factor screener / conviction signals"; avoid "QNTM stock" (that's the biopharma ticker). Title/H1 should always pair the name with the category.
- **Legal applies to the public page too:** the competitor matrix + "conviction signal" claims on an indexable marketing page are the same public-facing claim surface the fintech lawyer is reviewing — don't publish performance/comparative claims ahead of sign-off.

**Path to revenue (unchanged):** Articles approve → Mercury bank → Stripe live activation → swap to live keys → attorney sign-off → go live. Attorney review is the real gate and runs in parallel with the bank wait.

Other backlog: see **BACKLOG.md**.

---

## Session History

### May 31, 2026 (evening — Render migration + live intraday macro engine)
Big infrastructure + feature day.

**Hosting / domain / infra:**
- Renamed `qntm.app` → **`qntm.live`** everywhere (~37 refs across app.py, policies, arl.py).
- **Migrated prod off Streamlit Cloud → Render** (Starter, always-on; `render.yaml` blueprint; secrets via Render Secret File → `.streamlit/secrets.toml`). Custom domain `qntm.live` + `www`, SSL auto-issued. GoDaddy DNS: apex A→Render IP, www CNAME→`qntm-opbn.onrender.com`. Prod now auto-deploys on push to main, no reboot.
- **Supabase → Pro** (daily backups, no auto-pause; PITR add-on deliberately skipped).
- Set up 5 qntm.live mailboxes as forwarding aliases → admin@ (receiving only).
- Mobile sign-in bug fixed (home-page tz detector was calling `location.replace()` mid-navigation → `history.replaceState()`). Q favicon wired (`qntm_icon.png`). Repo cleanup (removed junk/dupes, untracked venv). MFA-gate buttons stacked vertically (were clipping on mobile). Stripe checkout re-validated on dev with test card.
- **`st.components.v1.html` → `qntm_html()` migration** + bumped Streamlit to ≥1.56 (resolved the June-1 deprecation). All 8 call sites migrated; JS-only payloads go inline via `st.html`, the backtest chart via `st.iframe`.

**Live intraday macro engine (the main feature — see Refresh Architecture):**
- Diagnosed why "last refreshed" was stuck a day behind: the workflow keyed `INTRADAY_RUN` off `github.event.schedule`, but cron-job.org triggers via `workflow_dispatch` (that field empty) → every run did a full refresh → cache-skip in 2s → timestamp never moved. Fixed by driving `INTRADAY_RUN`/`MACRO_RUN` off `workflow_dispatch` inputs; removed the redundant high-frequency GitHub `schedule` crons (cron-job.org owns intraday+macro now; GitHub keeps the 2 AM full run).
- Built **`run_macro_refresh`** (`--macro` / `MACRO_RUN`): lightweight live macro re-scan (~6 calls) that re-applies the sector overlay to today's existing scores with no ticker re-fetch, so daytime macro/geopolitical events move `adj_composite` intraday. Writes ONLY `adj_composite`/`signal`/`macro_overlay` (disjoint from the price pass → collision-safe).
- New **`macro_state`** table (single-row JSONB) as the macro source of truth; written by macro + full passes, read by the app.
- **Banner now reads `macro_state`** via `_live_macro()` (replaced all in-process `fetch_macro_overlay()` calls) → displayed regime matches the scoring, and page loads stop hitting RSS/VIX/WTI per-session.
- `fetch_macro_overlay` now returns `summary` + `event_labels`; banner shows a "News read:" line.
- Two cron-job.org jobs configured: intraday (`intraday:true`, Mon–Fri market hours) + macro (`macro:true`, all-week extended hours). Verified end-to-end; macro run shows on the app.

**Lessons / scars (READ):**
- **Workflows live ONLY in `.github/workflows/`.** A downloaded `nightly_refresh.yml` landed in the repo root (twice) and did nothing; the macro input never appeared and the cron 422'd. Always `grep -c "macro:" .github/workflows/nightly_refresh.yml` (must be ≥1) before committing workflow changes.
- **`git diff --stat` before every commit.** Stale/ancient files from `~/Downloads` got copied over current code (app.py showing 8000+ changed lines = wrong file). Re-download from the session's presented files, not old Downloads; delete stale Downloads copies.
- A `204` from cron-job.org only means GitHub accepted the dispatch — it says nothing about whether the Action ran or wrote anything. Check the Action run logs + step duration (a 2s "Run refresh" = cache-skip, not a real run).

### May 30, 2026 (evening — Stripe billing)
Built the full payments layer. Major themes: Stripe Checkout + trial, Founder-supporter path, lots of Streamlit-sandbox navigation debugging.

**Completed:**
- `stripe_billing.py` — Checkout (hosted), 7-day trial, polling-based sync, cancel/reactivate, `last_error()`. Version-safe `_g()` accessor (Stripe objects don't reliably support `.get()`).
- `db.py` — `set_stripe_billing`/`get_stripe_billing` (notifications JSON, no migration).
- Upgrade page: ARL notice + consent checkbox + Start-trial → Checkout. `_paid_trial_mode` auto-on when Stripe configured.
- Checkout return handler (`?checkout=success`) → finalize → set Pro + billing_active + trial_end + ack email. Once-per-session poll syncs status; self-heal gated behind `_awaiting_checkout` counter (un-gated version stalled every free user's page load with a Stripe call).
- Trial countdown on account page ("PRO · FREE TRIAL — X days left, first charge [date]"). Founder vs paid distinguished by `billing_active`.
- One-click Cancel wired to Stripe (`cancel_at_period_end=True`) + confirmation email.
- **Founder-supporter path** (`page_account`): Founding Members can optionally start the $29/mo sub to support QNTM. One-way: cancel later → regular Free, not free Founding. Reuses ARL machinery, logs consent as `pro_supporter`.
- Trial-started themed banner (replaced unthemeable white `st.toast`), shows on any return page.
- `stripe` added to requirements.txt (was missing — would crash deploy).
- Verified in sandbox: upgrade → trial → paid distinction → countdown → cancel, all working. Test card `4242 4242 4242 4242`.

**Lessons / scars (READ before touching checkout nav):**
- Streamlit sandbox blocks `<a target=_top>` and `window.top.location`; only `window.open(url,'_top')` inside a `components.v1.html` iframe drives the parent. `st.link_button` works but opens a NEW TAB. `target=_self` navigates the iframe → Stripe refuses (X-Frame-Options) → hang.
- `st.button` is True for ONE rerun; render follow-up UI from session_state outside the button block, or it vanishes.
- **Most of the wasted time was STALE DEPLOYS** masking whether a fix landed. After any push: `git log origin/dev`, then FULL REBOOT (Manage app → ⋮ → Reboot), then judge. Don't trust a refresh.
- Checkout currently = `st.link_button` (new tab). Same-tab `_render_checkout_button()` (window.open _top component) is in git history, deferred.
- Use `git add -A` not `git add app.py` — multi-file changes (db.py, stripe_billing.py) get stranded otherwise. This bit us repeatedly.

**Also:** survived a user-deletion scare (deleted an empty test account, not the buddy — confirmed via child-row counts). Supabase is on FREE plan = NO BACKUPS — upgrade to Pro before launch. Reset-for-retest SQL: set plan=free + strip stripe_* keys from notifications JSON, cancel the Stripe sub immediately, use fresh incognito session (or a `+test` email alias for a clean account).

### May 30, 2026 (full day)
Major themes: watchlist/card UX overhaul, two compliance builds (atomic publishing + signal vocab + ARL), prod deploy.

**Multi-watchlist + card actions:**
- Multi-watchlist feature: `watchlists` + `watchlist_items` tables, named lists, create/rename/delete, "% since added" + "today's change" P&L strip.
- **Card rendering rewritten** (see Architecture Rule 1b) — abandoned iframes for `st.markdown` + native `<details>` after long debugging. Per-card Add/Remove buttons (watchlist/portfolio/simulator modes) that work AND don't clip on expand.
- One-card-open accordion (`name="qntm-cards"` + JS fallback).
- Cards batched into single `st.markdown` per list for perf.
- Fixed: pct_rank showing "50th" everywhere (now computed from session distribution); inconsistent P&L layouts (now uniform SINCE ADDED + TODAY); TODAY change showing stale figure on weekends (now "CLOSED" when not a trading day, ET-aware).

**Compliance — atomic publishing + vocab (doc-driven):**
- `migrations/atomic_publishing.sql` — atomic batch publish RPC, append-only `signal_batch_audit`, published_at. `data_refresh.publish_signal_batch()` calls it (not yet wired into run_refresh).
- Conflicts-of-interest disclosure added (Investment Disclaimer + footer + TOS §3). `docs/TRADING_POLICY.md` created (internal).
- Removed ALL buy/hold/sell instructional language from user-facing copy. Normalized signal_log `signal` column (8 vocabularies → HIGH/MODERATE/LOW) at root in `model_engine` + via SQL on backup (`signal_legacy`). seed_track_record fixed.

**Compliance — California ARL (AB 2863), doc-driven:**
- Full audit done first (checkout + cancel flows). Found $0 Founding flow has no auto-renewal → ARL gated behind `_paid_trial_mode`.
- `arl.py` module + `migrations/arl_compliance.sql` (`arl_consent_log`, `notices_sent`, both append-only).
- Initial notice block (1A), affirmative-consent checkbox (1B), consent log (1C), acknowledgment email (1D) — gated on paid mode.
- True one-click cancel (replaced expander + two-step confirm) + confirmation email.
- Notice templates + annual-reminder cron + notices_sent logging. Email STUBBED.
- Policy edits: 7–30 day price-change window, material-change includes how-to-cancel, one-click-cancel wording aligned. Updated in app.py, `QNTM_POLICIES_FINAL.md`, and How It Works (new Billing & Cancellation section). No overstated performance claims.

**Deploy:** pushed everything to prod (`git push origin main`); prod now in sync with dev. User is set up to start Stripe next.

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
