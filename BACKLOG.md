# QNTM — UX Launch Polish Backlog
*Source: GPT product review · Updated: May 24, 2026*

This is a UX-first launch readiness backlog.

**DO NOT modify:** scoring logic, signal labels, paywall logic, simulator logic, methodology calculations, backend data model.

**Focus ONLY on:** UX simplification, visual hierarchy, clarity, premium feel, retention mechanics, scanability, mobile optimization.

Execute in sprint order. Complete Sprint 1 before Sprint 2.

---

# SPRINT 1 — HIGH IMPACT UX SIMPLIFICATION

---

## TASK 1 — Collapse Card Architecture

**Problem:** Too many cards show too much at once. Cognitive overload.

**Applies to:** Top Signals, Full Universe, Watchlist, Hidden Gems, Portfolio views

**Default state (collapsed):**
- Ticker · Conviction label · Score · Trend arrow
- Example: `NVDA — High Conviction — 84 ↑`

**Expanded state (tap/click):**
- Factor breakdown
- WHY THIS SCORE
- Signal history sparkline
- Supporting metrics

**Interaction rule:** Only ONE card expanded at a time. Opening new card collapses previous.

**Acceptance:** User can scan screen quickly. Detail only on demand.

---

## TASK 2 — Home Page Information Hierarchy Redesign

**Problem:** Hero has too many competing elements. Performance stats dominate too early.

**Above the fold ONLY:**
1. Hero headline + subtext + primary CTA + secondary CTA
2. Single primary insight card: **Market Regime Today** (dominant visual)
3. Top 5 Highest Conviction Signals — collapsed cards only
4. Watchlist Summary (if logged in) — compact only

**Move** hero performance metrics (+347%, Sharpe, win rate, drawdown) below primary content. Do NOT remove.

**Acceptance:** User understands app purpose in under 3 seconds. Hero feels simple and premium.

---

## TASK 3 — Visual Hierarchy Intensity Reduction

**Problem:** Everything feels equally loud. Too many competing visual elements.

**Apply 3-level hierarchy across entire UI:**

- **Level 1 (high emphasis):** Primary CTAs, conviction badges, regime badge, active alerts ONLY
- **Level 2 (medium):** Cards, charts, section headers, expanded content
- **Level 3 (low):** Timestamps, explanatory copy, secondary metrics, helper text, metadata

**Reduce:** excessive glow, bright borders, heavy shadows, nested boxes, competing colors

**Acceptance:** Eye naturally goes to primary content first. UI feels calmer.

---

## TASK 4 — Spacing / Breathing Room Pass

**Problem:** Cards and sections feel compressed.

**Increase across all screens:** vertical padding, section gaps, card spacing, line spacing, margin consistency

**Reduce:** cramped metric stacks, tight rows, border clutter, dense dividers

**Mobile specific:** larger tap targets, more row spacing, more card padding

**Acceptance:** No screen feels visually cramped. Improved mobile readability.

---

## TASK 5 — Top Signals Scan Mode

**Problem:** Top Signals screen is visually dense.

**Default layout — simple signal rows:**
```
NVDA — High Conviction — 84 ↑
MSFT — High Conviction — 81 ↑
AAPL — Moderate Conviction — 67 →
```

**Tap to expand:** WHY THIS SCORE, factor bars, signal history, deeper metrics

**Interaction rule:** Only one expanded at a time

**Acceptance:** User can scan top signals in seconds. Details only on demand.

---

# SPRINT 2 — UX POLISH / STICKINESS

---

## TASK 6 — Watchlist Intelligence UX

**Problem:** Watchlist stores stocks but doesn't feel dynamic.

**Add summary section at top:**
- X improving · X weakening · avg conviction trend · sector posture

**Per stock row upgrade:**
- Current: `AAPL — 74`
- New: `AAPL — 74 ↑ +4` or `AAPL — 74 ↓ -3`

**Optional:** mini sparkline per row

**Acceptance:** User immediately sees what changed. Watchlist feels alive.

---

## TASK 7 — Search Experience Redesign

**Problem:** Search works but feels like a form field.

**Add live autocomplete:**
- As user types → `Apple (AAPL)`, `Microsoft (MSFT)`, `NVIDIA (NVDA)`
- Include ticker + company name

**Add recent searches:** shown when search focused and empty (last 5)

**Styling upgrades:** search icon, premium dropdown, hover states, softer borders, larger input

**Acceptance:** Search feels like premium fintech UX.

---

## TASK 8 — Watchlist / Stock Detail History Visuals

**Problem:** Current score lacks visual context.

**Watchlist card:** small sparkline showing recent conviction trend

**Stock detail:** larger chart with conviction trend + direction + optional price overlay

**Acceptance:** User can see signal trajectory visually.

*(Note: sparkline function `signal_history_chart()` already built — wire into watchlist cards)*

---

## TASK 9 — Portfolio Summary Simplification

**Problem:** Portfolio shows too much detail too early.

**Lead with single summary card:**
```
Portfolio Conviction: Moderate
Trend: Improving
Key risks:
  · Concentration elevated
  · 2 weakening positions
```

**Detail below:** expanded analytics only on interaction

**Acceptance:** Portfolio screen communicates main message immediately.

---

# SPRINT 3 — TRUST / PREMIUM FEEL

---

## TASK 10 — Hero Trust Rebalance

**Problem:** Performance claims dominate trust messaging.

**Replace primary trust stats with:**
- 834 Stocks Monitored
- Multi-Factor Quant Engine
- Daily Signal Updates
- Market Regime Aware

**Move** +347%, Sharpe, win rate, drawdown lower on page. Keep visible but secondary.

**Acceptance:** Hero feels credible, not promotional.

---

## TASK 11 — 3-Second Rule Audit (every screen)

**Problem:** Many screens require too much cognitive processing.

**For each screen — ask:** Can user understand primary message in 3 seconds?

**If no — reduce:** visible metrics, simultaneous charts, stacked copy, competing cards

**Promote:** one primary insight · one secondary insight · expandable detail

**Acceptance:** Every screen passes 3-second comprehension test.

---

## TASK 12 — Streamlit Feel Reduction Pass

**Problem:** Some screens still feel like a dashboard prototype.

**Reduce:** obvious form styling, stacked widget look, default dashboard card feel

**Improve:** spacing, card ratios, typography hierarchy, cleaner interaction states, premium CTA styling, better alignment

**Acceptance:** App feels like premium fintech SaaS, not a dashboard prototype.

---

# BLOCKING (outside UX scope but must happen)

- [ ] Stripe integration (waiting on lawyer)
- [ ] Push v2 → main

---

# NOTES FOR IMPLEMENTATION

- Signal history sparkline already built: `signal_history_chart(ticker, score)` — reuse in Task 8
- `_build_why_html(r)` already built — reuse in Task 1 expanded state
- `factor_panel_html()` already renders full card — Task 1 means wrapping it in a collapsed default
- All interactive elements must use URL action pattern — NO `st.button` + `st.rerun()` in platform pages
- signal_log columns that exist: `adj_composite, composite, momentum, quality, volume, value, sentiment, price, signal, signal_date, ticker, is_hidden_gem, macro_overlay`
- Sector always derived from `SECTORS.get(ticker)` — not in signal_log
