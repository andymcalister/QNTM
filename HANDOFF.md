# QNTM Platform — Handoff Summary
*Updated: May 30, 2026 (late — Stripe sandbox lifecycle working)*

## What It Is
QNTM is a quantitative conviction factor model platform for retail investors. Dark institutional aesthetic, dark theme.

**Deployments:**
- Prod: `qntmmvp.streamlit.app` (main branch) ← **now in sync with dev as of this session**
- Dev: `qntm-dev.streamlit.app` (dev branch) ← **active dev target**
- **GitHub:** `andymcalister/QNTM`

**Standard push (dev):**
```bash
git push origin main:dev
# then force rebuild:
git commit --allow-empty -m "chore: force rebuild" && git push origin main:dev
# then reboot app (Manage app → ⋮ → Reboot) + hard-refresh
```

**Push to prod:**
```bash
git push origin main
git commit --allow-empty -m "chore: force rebuild" && git push origin main
# reboot prod + hard-refresh
```
Note: local commits are made on `main`; `main:dev` pushes that branch to the `dev` remote. Prod and dev share the same Supabase project, so run migrations once.

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
- **Signals:** HIGH ≥60, MODERATE 45–59, LOW <45. **The `signal` column in signal_log now stores HIGH/MODERATE/LOW** (normalized this session from 8 legacy vocabularies — BUY/HOLD/SELL/STRONG ALIGN/HIGH ALIGN/LOW ALIGN/WEAK/NEG). `signal_legacy` column holds the originals for rollback. `model_engine` writes HIGH/MODERATE/LOW going forward. The internal `adj_action` enum (BUY/SELL/HOLD) is STILL used in code for portfolio/promotion logic but is NEVER displayed — always converted to conviction labels. No buy/hold/sell instructional language anywhere user-facing.
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
- `sector` → `SECTORS.get(ticker, "Unknown")` from `model_engine`
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
`users`, `holdings`, `signal_log`, `notifications`, `backtest_cache`, `fundamentals_cache`, `signal_snapshots`, `model_portfolio_positions`, `watchlists`, `watchlist_items`, `arl_consent_log`, `notices_sent`, `signal_batch_audit`

**Migrations (run in Supabase SQL editor; prod+dev share one project):**
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
**Outstanding:** rotate Supabase keys before paid launch (flagged repeatedly). Add `SUPABASE_SERVICE_KEY` to Streamlit Cloud secrets on BOTH dev and prod — the ARL logging, atomic publish, and freshness checks use the service-key client.

---

## Pre-Launch Checklist
- [x] **QNTM LLC** — Articles of Organization FILED (pending state approval). EIN + business email obtained.
- [x] Stripe integration built & working in SANDBOX (Checkout + 7-day trial + cancel + Founder-supporter)
- [x] Prod in sync with dev (May 30)
- [x] Signal vocabulary normalized to HIGH/MODERATE/LOW (code + DB)
- [x] ARL machinery built (auto-on when Stripe configured)
- [ ] **Bank account (Mercury)** — blocked on Articles approval; needed for Stripe payout
- [ ] **Swap Stripe sandbox → live keys** + recreate product in live mode (needs bank + account activation)
- [ ] **Fintech lawyer review** — IAA 1940 publisher's exclusion, ARL copy + consent/cancel UI, Founder-supporter path, conflicts disclosure, trading policy, disclaimers, CA DFPI. THE GATE before paying users.
- [ ] Wire `arl._send_email` to SendGrid (currently stubbed)
- [ ] Add `STRIPE_*` + `SUPABASE_SERVICE_KEY` to PROD secrets when going live
- [ ] Rotate Supabase keys
- [ ] **Upgrade Supabase to Pro for backups** (currently FREE = no backups — risk before paying users)
- [ ] Wire `publish_signal_batch()` into `run_refresh` (atomic publishing)
- [ ] Verify intraday cron on prod
- [ ] (optional) Stripe webhooks to replace polling lag; same-tab checkout button

## Next Session
Stripe sandbox lifecycle is DONE. Remaining path to revenue: **Articles approve → Mercury bank → Stripe live activation → swap to live keys → attorney sign-off → go live.** Attorney review is the real gate and can run in parallel with the bank wait. Quick wins available now: test-account cleanup discipline (`+test` aliases), Supabase Pro backups, SendGrid wiring.

Other backlog: see **BACKLOG.md**.

---

## Session History

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
