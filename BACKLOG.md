# QNTM — Product Backlog
*Created: May 24, 2026*

Prioritized from GPT product review + current platform state.
Work in order. Each tier is a session target.

---

## BLOCKING (do before any paid users)

- [ ] **Stripe integration** — `STRIPE_SECRET_KEY` + `STRIPE_PRICE_ID_PRO` + webhook → plan upgrade flow. Replace `upgrade_plan()` calls in gate CTAs with Stripe checkout redirect. Lawyer review required first.
- [ ] **Push v2 → main** — merge when stable, beta users hit prod URL `qntmmvp.streamlit.app`

---

## TIER 1 — Trust + Retention (highest ROI, do first)

### 1. "What Changed Today?" — Score Delta Context
- On every score card, show score movement vs previous scan: `▲ +6 since yesterday` or `▼ -4 this week`
- Data already in signal_log (two most recent rows per ticker)
- Add to: screener search result, full universe cards, watchlist
- Already have batch trend fetch pattern from watchlist — reuse it

### 2. Daily Briefing / Habit Loop
- In-app: "Today in QNTM" summary at top of screener on login
- Shows: macro regime, top conviction upgrades, new weakening signals, new hidden gems, portfolio warnings
- Email version post-Stripe (requires SendGrid + pro gate)
- This is the single biggest retention driver

### 3. Hero Page Trust Fix
- Current hero leads with +347% performance claims — feels like guru ad
- Restructure: lead with what QNTM *is* (834 stocks, multi-factor engine, daily refresh, regime-aware)
- Move performance stats to Performance section below fold
- Trust before bragging = higher conversion

### 4. Search UX Polish — Autocomplete + Recent Searches
- Recent searches: store last 5 tickers in session state, show as quick-tap chips below search box
- Autocomplete: as user types, filter SECTORS dict for matching tickers/names, show dropdown
- Should feel like TradingView search, not a form field

---

## TIER 2 — Product Depth (high value, do second)

### 5. Model Portfolio Storytelling
- Currently buried — surface it as "How the QNTM model is positioned right now"
- Add: weekly changes section (what entered/exited this week)
- Add: current sector posture summary (overweight/underweight vs benchmark)
- Add: cash/risk stance indicator based on macro regime
- This is sticky content users check weekly

### 6. Portfolio Intelligence — Conviction Summary
- Portfolio page needs more signal intelligence beyond current 4-stat header
- Add: "2 positions weakening — consider reviewing" alert
- Add: Portfolio Conviction Score (weighted avg of all holdings scores)
- Add: Concentration warning (if >30% in one sector)
- Add: Macro sensitivity rating (% of portfolio in RISK_OFF-sensitive positions)

### 7. Top 10 Tab Density Fix
- Mobile: too dense, all cards expanded
- Change to collapsed-only cards: `NVDA — High Conviction — 84`
- Tap to expand, only one open at a time (accordion pattern)
- Cleaner, feels premium

### 8. Watchlist Intelligence Enhancement
- Watchlist summary header: "3 improving · 2 weakening · overall conviction rising"
- Per-stock: show score movement more prominently (currently ↑ ↓ → arrow is small)
- Add full sparkline per watchlist stock (data builds daily — needs 5+ nightly runs)

---

## TIER 3 — Premium Feature Polish (do third)

### 9. Simulator — Before vs After Comparison
- Current simulator shows allocation only
- Add: conviction improvement score vs user's current portfolio holdings
- Add: sector diversification delta
- Add: simple visual comparison — "current vs simulated"
- Positions this as "worth paying for" tool

### 10. Screener Top 10 — Sector Breakdown Polish
- Sector breakdown tab shows BUY/HOLD/SELL counts but uses raw internal labels
- Update to High/Moderate/Low conviction language throughout
- Add: sector regime context (which sectors are benefiting from current macro)

---

## TIER 4 — Post-Launch Growth

### 11. Email Notifications
- Signal change alerts to pro users (requires Stripe → SendGrid)
- Daily briefing email (opt-in, pro only)
- Weekly model portfolio update email

### 12. Multiple Watchlists
- Allow sector watchlists, thematic watchlists
- Currently one flat list per user

### 13. Watchlist Alerts
- Push/email when watched stock changes conviction level
- Already have the detection logic in conviction alerts banner — just needs delivery

### 14. API Access (Institutional tier)
- Model outputs via API endpoint
- Custom universe upload
- Already in PLAN_LIMITS as institutional tier

---

## KNOWN TECH DEBT (fix opportunistically)

- `signal_log` sector enrichment — sector comes from `SECTORS` dict not DB, must be joined in Python after every signal_log query (currently done in simulator, need consistent pattern everywhere)
- `sim_data` session key — simulator uses separate key from `scan_results` to avoid 60s timer wipe; document this pattern
- `_pin_nav()` must be defined before any page function — if it moves, NameError crashes the app
- All helper functions (`_pin_nav`, `_back_btn`, `_upgrade_url`, `_cta_gold`, `_cta_ghost`) defined at lines 752–1910 — keep them there
- URL action handlers in `main()` must stay in order: sim_rescan → sim_profile → sim_add → sim_remove → upgrade → wl_action → port_action → port_period → upgrade_page → qnav routing
- Free tier screener limit: 50 stocks — gate shows until user clicks CTA → `upgrade=pro` URL action → router upgrades → full universe unlocks
- `st.button` is still used for: Sign In form, Create Account form, MFA verify, Add holding, Mark alerts read, Account MFA setup. These are safe (form submits, not nav actions).

---

## SIGNAL_LOG COLUMN REFERENCE
*Always check before writing new queries*

Columns that **exist**: `adj_composite, composite, created_at, hidden_gem_reason, id, is_hidden_gem, macro_overlay, momentum, price, quality, sentiment, signal, signal_date, ticker, value, volume`

Columns that **do NOT exist**: `sector`, `adj_action`, `pct_rank`, `score_delta`

Derive missing fields in Python:
- `sector` → `SECTORS.get(ticker, "Unknown")` from `model_engine`
- `adj_action` → derive from `adj_composite`: ≥60=BUY, <45=SELL, else HOLD
