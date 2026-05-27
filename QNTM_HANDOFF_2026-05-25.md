# QNTM Handoff Notes — 2026-05-25 (Evening Session)

## Session Summary
Continued from morning session. Major focus: card toggle fix (root cause found), model portfolio rebuild, prod deployment issues.

---

## Root Cause Found — Card Toggle

**The issue**: Streamlit uses `nh3` HTML sanitizer which strips:
- `<input>` elements entirely
- `<label>` elements (keeps text only)  
- `<style>` tags entirely
- `onclick` attributes entirely
- `class` and `data-*` attributes from most elements

This broke every CSS/JS approach we tried via `st.markdown`.

**The fix**: `st.components.v1.html` renders in a real iframe with no sanitization. All card batches (Top 10, Full Universe, Gems, Watchlist, Model Portfolio) now use `st.components.v1.html` with an embedded `<script>` tag that binds click handlers.

**Single cards** (search result): rendered pre-expanded via `st.markdown` — no toggle needed since it's always one card.

---

## Card Architecture (Final)

### Batch cards (multiple cards)
```python
import streamlit.components.v1 as _cv1_xxx
_html = ""
for r in items:
    _html += factor_panel_html(r, ...)
_height = max(60, _html.count('qcard-wrap') * 68 + 360)
_cv1_xxx.html(_html + CARD_SCRIPT, height=min(_height, 8000), scrolling=False)
```

### CARD_SCRIPT (embedded in each batch)
```html
<style>
@media(max-width:640px){ .qcard-pillars{grid-template-columns:repeat(2,1fr)!important;} }
body{margin:0;}
</style>
<script>
document.querySelectorAll('.qcard-header').forEach(function(h){
  h.addEventListener('click',function(){
    var d=h.querySelector('.qcard-detail');
    if(!d)return;
    var open=d.style.display==='block';
    document.querySelectorAll('.qcard-detail').forEach(function(x){x.style.display='none';});
    if(!open)d.style.display='block';
  });
});
</script>
```

### Single search result card
```python
_sr_html = factor_panel_html(sr, False, company_info=ci, suppress_wl_btn=True)
_sr_html = _sr_html.replace('class="qcard-detail" style="display:none;', 'class="qcard-detail" style="display:block;')
st.markdown(_sr_html, unsafe_allow_html=True)
```

### Card HTML structure (factor_panel_html)
```html
<div class="qcard-wrap">
  <div class="qcard-header" data-cid="cXXX">  ← JS binds click here
    ...summary row...
    <div class="qcard-detail" style="display:none;">  ← toggled by JS
      ...pillar bars, WHY THIS SCORE, QUANT/MACRO/BLEND/RANK...
    </div>
  </div>
</div>
```

---

## Model Portfolio Rebuild

### What was wrong
- `update_model_portfolio` in intraday cron used `.eq("signal_date", today_str)` — only fetched today's rows
- If nightly ran yesterday and intraday ran today with no new scores, `scored_list` was empty → no candidates found
- Entry threshold was hardcoded at 60 regardless of macro regime (should be 67 in HIGH VOLATILITY)

### Fix applied
- `data_refresh.py`: intraday now fetches most recent signal_date (not just today)
- `rebuild_model_portfolio.py`: script that replays all dates from 2026-05-19, applies regime-aware thresholds

### Rebuild script
`rebuild_model_portfolio.py` — run from QNTM directory:
```bash
python rebuild_model_portfolio.py
```
- Clears all existing positions
- Replays each signal date from 2026-05-19
- Detects regime from adj/composite ratio (< 0.90 = HIGH VOLATILITY → 67+ threshold)
- Respects 30% sector cap (15/50 per sector)
- Exits at score < 45
- Inserts in batches

### Model portfolio display
- Cards use `st.components.v1.html` with P&L strip injected into detail
- Shows: entry date, entry price, current price, % return, $ return
- Live prices via yfinance (5-min session cache), falls back to signal_log
- SPY comparison per-position (each position vs SPY over its holding window)

---

## Full Universe — Pagination

- Capped at 200 cards displayed (RENDER_LIMIT)
- Paginated at 50/page with Prev/Next buttons
- Page resets when filters change
- Company info from session cache only (no yfinance per card = fast)
- `_fu_filter_key` session state tracks current filter combo

---

## Pillar Bars — Cleaned Up

Removed tooltip icons (`<i class="tip-icon">i</i>`) and verbose descriptions.
Now shows: `Pillar name · score · coloured bar` only.
Grid: 5-col desktop, 2-col mobile (`@media(max-width:640px)`).

---

## Prod Deployment State

**WARNING**: main branch had conflicts with dev at end of session.
Resolution: `git checkout dev -- app.py && git commit && git push origin main`

Both branches should now be identical.

- **prod**: qntmmvp.streamlit.app (main branch)
- **dev**: qntm-dev.streamlit.app (dev branch)

---

## What's Next

### Stripe Integration
- Build behind `STRIPE_LIVE=false` env var gate
- Webhook needs Supabase Edge Function (Streamlit can't receive POST)
- Flow: checkout → webhook → upgrade user plan in Supabase
- Lawyer green light needed before flipping `STRIPE_LIVE=true`

### Model Portfolio Cron
- Monitor nightly to confirm it fills remaining open slots
- Currently ~41 active positions, ~9 open
- Should auto-fill as new HIGH conviction stocks emerge

### Known Issues / Watch List
- Full Universe iframe height is fixed — cards open within iframe but page doesn't scroll to reveal expanded content on mobile
- Watchlist page uses `st.components.v1.html` — same fixed-height iframe issue for large watchlists
- `st.html` (new Streamlit API) also sanitizes via DOMPurify — not useful for card HTML

---

## Key Files Changed Today

| File | Changes |
|------|---------|
| `app.py` | Card toggle, full universe pagination, model portfolio display, nav fixes, all UX polish |
| `data_refresh.py` | Intraday uses most recent signal_date; write_platform_stats added |
| `rebuild_model_portfolio.py` | New script — regime-aware portfolio rebuild from 2026-05-19 |

---

## Git State
```
main = prod (qntmmvp.streamlit.app) — synced with dev at end of session
dev  = development (qntm-dev.streamlit.app)
```

Last meaningful commits on dev:
- fix: search result card pre-expanded, st.markdown, no iframe gap
- fix: all card batches use st.components.v1.html
- fix: intraday portfolio uses most recent signal_date
- feat: model portfolio cards show entry date, prices, return % and $
- fix: full universe paginated 50/page
- fix: pillar bars cleaned up, no tooltip icons
