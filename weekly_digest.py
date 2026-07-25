"""
QNTM weekly digest email
========================
Weekly recap email behind the "Email signal summaries (weekly digest)" pref.
Sections:
  • Commentary — a short factual narrative of the week
  • This week — SPY's move + biggest movers on the user's lists (bar chart)
  • Model portfolio vs SPY — DOLLAR-WEIGHTED model return vs SPY (gated)
  • Your watchlist — each watched stock's weekly move (bar chart)
  • Your portfolio — each held stock's weekly move (bar chart)

Charts are inline HTML/CSS bars (email-client safe — no JS/SVG). Commentary is
deterministic and factual (no recommendations). Mirrors alerts_engine.py:
service Supabase client, db.send_email, fails soft. Weekly Render cron, or
locally for one address:  python3 weekly_digest.py you@example.com

The "Model portfolio vs SPY" performance section is ON by default. Set
DIGEST_PERFORMANCE=0 to suppress it.
"""
import os
import sys
import json
import logging
from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("qntm.digest")

LOOKBACK_DAYS = 9  # ~one trading week of calendar days


def _week_start_iso(as_of=None):
    """Monday of the ISO week containing as_of (UTC today if None). All weekly
    windows anchor to this so the recap covers Mon-Fri of the current week and
    ties out to the market_outlook week wrap, instead of a rolling 9-day span
    that bled into the prior week."""
    import datetime as _dt
    ref = (_dt.date.fromisoformat(str(as_of)[:10]) if as_of
           else _dt.datetime.now(_dt.timezone.utc).date())
    return (ref - _dt.timedelta(days=ref.weekday())).isoformat()


def _cfg(key):
    try:
        import streamlit as st
        return st.secrets.get(key) or os.getenv(key)
    except Exception:
        return os.getenv(key)


def _app_url():
    return (_cfg("APP_URL") or "https://qntm.live").rstrip("/")


def _include_performance() -> bool:
    # Default ON. Set DIGEST_PERFORMANCE=0 (or false/no) to suppress the
    # model-vs-SPY performance section.
    val = _cfg("DIGEST_PERFORMANCE")
    if val is None:
        return True
    return str(val).strip().lower() not in ("0", "false", "no", "off")


# ── Data ──────────────────────────────────────────────────────────────────────

def recipients(sb):
    """{user_id: email} for verified users opted into the weekly digest.

    The weekly digest is a FREE feature — every plan is eligible. Gating:
      • email_verified      — consent + deliverability.
      • notifications.email — the weekly-digest preference (ON by default; users
        opt OUT). Free and paid users both manage this in Account -> Notifications.
    The single-recipient test path (run(only_email=...)) bypasses this gate.
    """
    from db import decrypt_field
    try:
        users = sb.table("users").select(
            "id,email_encrypted,notifications,email_verified").execute().data or []
    except Exception as e:
        log.error("users read failed: %s", e)
        return {}
    out = {}
    for u in users:
        notifs = u.get("notifications") or {}
        if isinstance(notifs, str):
            try:
                notifs = json.loads(notifs)
            except Exception:
                notifs = {}
        if u.get("email_verified") and notifs.get("email"):
            em = decrypt_field(u.get("email_encrypted", "") or "")
            if em:
                out[u["id"]] = em
    return out


def weekly_prices(sb, tickers):
    """{ticker: {"start":float,"end":float,"pct":float}} from signal_log
    (oldest vs latest close in the ~1-week window)."""
    out = {}
    tickers = list({t for t in tickers if t})
    if not tickers:
        return out
    since = _week_start_iso()
    rows = []
    for i in range(0, len(tickers), 300):
        chunk = tickers[i:i + 300]
        try:
            rows.extend(sb.table("signal_log").select("ticker,price,signal_date")
                        .in_("ticker", chunk).gte("signal_date", since)
                        .order("signal_date", desc=False).execute().data or [])
        except Exception as e:
            log.error("weekly price fetch failed: %s", e)
    by = {}
    for r in rows:
        tk, p = r.get("ticker"), r.get("price")
        if not tk or p is None:
            continue
        try:
            by.setdefault(tk, []).append((str(r.get("signal_date"))[:10], float(p)))
        except (TypeError, ValueError):
            continue
    for tk, series in by.items():
        series.sort()
        if len(series) < 2:
            continue
        start, end = series[0][1], series[-1][1]
        if start and start > 0:
            out[tk] = {"start": start, "end": end, "pct": (end - start) / start * 100.0}
    return out


def model_positions(sb):
    """[{ticker, entry_price, position_size}] for the active model portfolio."""
    try:
        from model_engine import MODEL_EPOCH
    except Exception:
        MODEL_EPOCH = "live"
    try:
        rows = (sb.table("model_portfolio_positions").select("ticker,entry_price,position_size")
                .eq("is_active", True).eq("epoch", MODEL_EPOCH).execute().data or [])
    except Exception as e:
        log.error("model positions read failed: %s", e)
        return []
    out = []
    seen = set()
    for r in rows:
        tk = (r.get("ticker") or "").upper()
        if not tk or tk in seen:
            continue
        seen.add(tk)
        out.append({"ticker": tk,
                    "entry_price": r.get("entry_price"),
                    "position_size": r.get("position_size") or 2000.0})
    return out


def model_dollar_weighted_return(positions, prices):
    """Market-value-weighted weekly return: shares = position_size/entry_price
    (fixed), return = Σ shares·end / Σ shares·start − 1. Falls back to None."""
    v_start = v_end = 0.0
    used = 0
    for p in positions:
        tk = p["ticker"]
        pr = prices.get(tk)
        ep = p.get("entry_price")
        ps = p.get("position_size") or 2000.0
        if not pr or not ep:
            continue
        try:
            shares = float(ps) / float(ep)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        v_start += shares * pr["start"]
        v_end += shares * pr["end"]
        used += 1
    if used == 0 or v_start <= 0:
        return None, 0
    return (v_end / v_start - 1.0) * 100.0, used


def user_lists(sb, user_id):
    wl, ho = [], []
    try:
        wl = [r["ticker"].upper() for r in (sb.table("watchlist_items").select("ticker")
              .eq("user_id", user_id).execute().data or []) if r.get("ticker")]
    except Exception:
        pass
    try:
        ho = [r["ticker"].upper() for r in (sb.table("holdings").select("ticker")
              .eq("user_id", user_id).execute().data or []) if r.get("ticker")]
    except Exception:
        pass
    # Dedupe (duplicate watchlist_items/holdings rows shouldn't double a ticker)
    # while preserving first-seen order.
    return list(dict.fromkeys(wl)), list(dict.fromkeys(ho))


# ── Rendering ─────────────────────────────────────────────────────────────────

def _fmt(p):
    return f"+{p:.1f}%" if p >= 0 else f"{p:.1f}%"


def _col(p):
    return "#15a97a" if p >= 0 else "#c0392b"


def _bar_table(items):
    """items: list of (ticker, pct). Inline-CSS horizontal bar chart, email-safe."""
    if not items:
        return ('<p style="font-size:13px;color:#888;margin:6px 0;">'
                'Not enough price history yet.</p>')
    maxabs = max((abs(p) for _, p in items), default=1.0) or 1.0
    rows = []
    for t, p in items:
        w = max(3, int(abs(p) / maxabs * 100))
        rows.append(
            '<tr>'
            f'<td style="padding:5px 8px 5px 0;font-weight:700;color:#0a0b14;font-size:14px;'
            f'white-space:nowrap;">{t}</td>'
            '<td style="padding:5px 0;width:100%;">'
            '<table style="width:100%;border-collapse:collapse;"><tr>'
            f'<td style="width:{w}%;"><div style="height:14px;border-radius:3px;'
            f'background:{_col(p)};"></div></td><td></td></tr></table></td>'
            f'<td style="padding:5px 0 5px 10px;text-align:right;font-weight:700;'
            f'color:{_col(p)};font-size:14px;white-space:nowrap;">{_fmt(p)}</td>'
            '</tr>')
    return (f'<table style="width:100%;border-collapse:collapse;'
            f'font-family:Arial,Helvetica,sans-serif;">{"".join(rows)}</table>')


def _section(title, inner):
    return (f'<div style="margin:22px 0 8px;font-size:13px;font-weight:800;letter-spacing:.05em;'
            f'text-transform:uppercase;color:#15a97a;">{title}</div>{inner}')


# ── Sector & macro context (the "why") ─────────────────────────────────────────

_SECTORS_CACHE = None


def _sectors_map():
    global _SECTORS_CACHE
    if _SECTORS_CACHE is None:
        try:
            from model_engine import SECTORS
            _SECTORS_CACHE = SECTORS or {}
        except Exception:
            _SECTORS_CACHE = {}
    return _SECTORS_CACHE


def _sector_perf(tickers, prices, min_names=2):
    """Average weekly move per sector across the given tickers.
    Returns [(sector, avg_pct, n)] sorted best→worst, sectors with >= min_names only."""
    from collections import defaultdict
    smap = _sectors_map()
    buckets = defaultdict(list)
    for t in set(tickers):
        if t in prices:
            sec = smap.get(t)
            if sec:
                buckets[sec].append(prices[t]["pct"])
    out = [(sec, sum(v) / len(v), len(v)) for sec, v in buckets.items() if len(v) >= min_names]
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def _sector_rotation_sentence(tickers, prices):
    """One-line leaders/laggards read across the user's own names."""
    perf = _sector_perf(tickers, prices, min_names=2)
    if len(perf) < 2:
        return ""
    lead, lag = perf[0], perf[-1]
    if (lead[1] - lag[1]) < 1.0:   # spread too small to be a story
        return ""
    return (f"Across your names, <b>{lead[0]}</b> led "
            f"(<span style='color:{_col(lead[1])};'>{_fmt(lead[1])}</span> avg) while "
            f"<b>{lag[0]}</b> lagged "
            f"(<span style='color:{_col(lag[1])};'>{_fmt(lag[1])}</span>).")


def _model_driver_sentence(positions, prices):
    """Which sectors drove the model this week (descriptive attribution)."""
    perf = _sector_perf([p["ticker"] for p in positions], prices, min_names=2)
    if len(perf) < 2:
        return ""
    lead, lag = perf[0], perf[-1]
    return (f"Within the model, <b>{lead[0]}</b> names contributed most "
            f"(<span style='color:{_col(lead[1])};'>{_fmt(lead[1])}</span> avg) and "
            f"<b>{lag[0]}</b> weighed most "
            f"(<span style='color:{_col(lag[1])};'>{_fmt(lag[1])}</span>).")


def macro_backdrop(sb):
    """Prose narration of QNTM's current macro overlay (regime + active events).
    A snapshot from the macro engine — descriptive of the current backdrop, not a
    per-day claim and not forward-looking advice. Returns '' if unavailable."""
    try:
        from data_refresh import _load_macro_state
        from model_engine import MACRO_EVENT_INFO
    except Exception:
        return ""
    try:
        state = _load_macro_state() or {}
    except Exception:
        return ""
    if not state:
        return ""
    regime = str(state.get("regime") or "NEUTRAL").upper()
    regime_word = {"RISK_ON": "risk-on", "RISK_OFF": "risk-off"}.get(regime, "neutral")
    events = [e for e in (state.get("active_events") or []) if e in MACRO_EVENT_INFO]
    lead = f"QNTM&rsquo;s macro overlay reads the current backdrop as <b>{regime_word}</b>."
    if not events:
        body = (' No major macro events are flagged right now, so the overlay is applying '
                'little sector tilt.')
        return _section("Macro backdrop",
            f'<p style="font-size:14px;color:#333;line-height:1.65;margin:0;">{lead}{body}</p>')
    items = []
    for e in events[:3]:
        info = MACRO_EVENT_INFO[e]
        impact = info.get("impact", "")
        items.append(
            f'<li style="margin:5px 0;"><b>{info["label"]}</b> &mdash; {info["summary"]}.'
            + (f' <span style="color:#888;">{impact}</span>' if impact else '')
            + '</li>')
    return _section("Macro backdrop",
        f'<p style="font-size:14px;color:#333;line-height:1.65;margin:0 0 8px;">{lead} '
        'Active events shaping its sector tilts this week:</p>'
        '<ul style="font-size:14px;color:#333;line-height:1.6;margin:0;padding-left:18px;">'
        + "".join(items) + '</ul>')


def _commentary(spy, model_ret, wl_rows, ho_rows, movers, prices=None):
    """Deterministic, factual recap sentences. No recommendations."""
    bits = []
    if spy is not None:
        bits.append(f"The S&amp;P 500 {'rose' if spy >= 0 else 'fell'} "
                    f"<b style='color:{_col(spy)};'>{_fmt(spy)}</b> this week.")
    if movers:
        top = movers[0]
        bot = movers[-1]
        if top[1] > 0:
            bits.append(f"Your strongest name was <b>{top[0]}</b> "
                        f"(<span style='color:{_col(top[1])};'>{_fmt(top[1])}</span>).")
        if bot[1] < 0 and bot[0] != top[0]:
            bits.append(f"The weakest was <b>{bot[0]}</b> "
                        f"(<span style='color:{_col(bot[1])};'>{_fmt(bot[1])}</span>).")
    if prices is not None:
        tickers = [t for t, _ in wl_rows] + [t for t, _ in ho_rows]
        rotation = _sector_rotation_sentence(tickers, prices)
        if rotation:
            bits.append(rotation)
    if wl_rows:
        up = sum(1 for _, p in wl_rows if p >= 0)
        bits.append(f"{up} of {len(wl_rows)} watchlist names were up.")
    if ho_rows:
        up = sum(1 for _, p in ho_rows if p >= 0)
        bits.append(f"{up} of {len(ho_rows)} of your holdings were up.")
    if not bits:
        return ""
    return ('<p style="font-size:14px;color:#333;line-height:1.65;margin:0;">'
            + " ".join(bits) + '</p>')


# ── Model performance detail (all gated behind DIGEST_PERFORMANCE) ─────────────

def _weekday(dstr):
    try:
        return datetime.strptime(str(dstr)[:10], "%Y-%m-%d").strftime("%a")
    except Exception:
        return str(dstr)[5:10]


def spy_daily(sb):
    """[(date, close)] daily SPY over the window, oldest→newest."""
    since = _week_start_iso()
    try:
        rows = (sb.table("benchmark_price").select("d,close")
                .gte("d", since).order("d", desc=False).execute().data or [])
    except Exception as e:
        log.error("spy_daily failed: %s", e)
        return []
    out = []
    for r in rows:
        c = r.get("close")
        if c is None:
            continue
        try:
            out.append((str(r["d"])[:10], float(c)))
        except (TypeError, ValueError):
            pass
    out.sort()
    return out


def _model_daily_prices(sb, tickers):
    """{ticker: {date: price}} from signal_log over the window."""
    px = {}
    tickers = list({t for t in tickers if t})
    if not tickers:
        return px
    since = _week_start_iso()
    rows = []
    for i in range(0, len(tickers), 300):
        chunk = tickers[i:i + 300]
        try:
            rows.extend(sb.table("signal_log").select("ticker,price,signal_date")
                        .in_("ticker", chunk).gte("signal_date", since)
                        .order("signal_date", desc=False).execute().data or [])
        except Exception as e:
            log.error("model_daily price fetch failed: %s", e)
    for r in rows:
        tk, p, d = r.get("ticker"), r.get("price"), r.get("signal_date")
        if not tk or p is None or not d:
            continue
        try:
            px.setdefault(tk.upper(), {})[str(d)[:10]] = float(p)
        except (TypeError, ValueError):
            continue
    return px


def perf_paths(sb, positions, prices):
    """Aligned cumulative-% paths (model, SPY) on SPY's trading-day axis.

    The model path is anchored to the SAME basket and window-start prices that
    model_dollar_weighted_return uses, so the chart's endpoints tie out exactly
    to the headline numbers: model_cum[-1] == model_ret, spy_cum[-1] == spy_week.
    Per-ticker daily prices give the intra-week shape (LOCF; pre-data held at the
    window start so a name contributes 0% until it has data).
    Returns (dates, model_cum, spy_cum) or (None, None, None)."""
    sd = spy_daily(sb)
    if len(sd) < 2:
        return None, None, None
    spy_dates = [d for d, _ in sd]
    s0 = sd[0][1]
    if not s0:
        return None, None, None
    spy_cum = [(c / s0 - 1.0) * 100.0 for _, c in sd]

    # Basket identical to model_dollar_weighted_return: tickers in `prices`,
    # valid entry_price, fixed shares, anchored at prices[tk]["start"].
    basket = []
    for p in positions:
        tk, ep = p["ticker"], p.get("entry_price")
        ps, pr = p.get("position_size") or 2000.0, prices.get(p["ticker"])
        if not pr or not ep:
            continue
        try:
            sh = float(ps) / float(ep)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        basket.append((tk, sh, pr["start"]))
    if not basket:
        return None, None, None

    px = _model_daily_prices(sb, [tk for tk, _, _ in basket])
    v0 = sum(sh * start for _, sh, start in basket)
    if v0 <= 0:
        return None, None, None

    last = {tk: start for tk, _, start in basket}   # pre-data anchored to start
    model_cum = []
    for d in spy_dates:
        v = 0.0
        for tk, sh, _ in basket:
            p = px.get(tk, {}).get(d)
            if p is not None:
                last[tk] = p
            v += sh * last[tk]
        model_cum.append((v / v0 - 1.0) * 100.0)

    return spy_dates, model_cum, spy_cum


def _signed_col(value, maxabs, color, w=13, H=104):
    """A single Outlook-safe vertical column (nested table, signed about a midline)."""
    half = H // 2
    h = int(round(min(abs(value), maxabs) / maxabs * half)) if maxabs > 0 else 0
    if abs(value) > 0.01:
        h = max(h, 2)
    else:
        h = 0
    if value >= 0:
        top_pad, pos, neg, bot_pad = half - h, h, 0, half
    else:
        top_pad, pos, neg, bot_pad = half, 0, h, half - h

    def cell(px, bg=None, radius=""):
        if px <= 0:
            return ""
        style = (f"height:{px}px;line-height:{px}px;font-size:0;"
                 "mso-line-height-rule:exactly;")
        if bg:
            return (f'<tr><td height="{px}" width="{w}" bgcolor="{bg}" '
                    f'style="{style}border-radius:{radius};width:{w}px;">&nbsp;</td></tr>')
        return f'<tr><td height="{px}" style="{style}">&nbsp;</td></tr>'

    return ('<table cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse;display:inline-block;width:{w}px;">'
            + cell(top_pad) + cell(pos, color, "2px 2px 0 0")
            + cell(neg, color, "0 0 2px 2px") + cell(bot_pad) + '</table>')


def perf_chart_html(dates, model_cum, spy_cum):
    """Grouped daily column chart: cumulative model vs SPY across the week."""
    MODEL_C, SPY_C = "#15a97a", "#8a93a6"
    maxabs = max([abs(v) for v in model_cum + spy_cum] + [0.5])
    cols = []
    for i, d in enumerate(dates):
        cols.append(
            '<td style="text-align:center;vertical-align:bottom;padding:0 5px;">'
            '<table cellpadding="0" cellspacing="0" style="display:inline-block;">'
            '<tr>'
            f'<td style="vertical-align:bottom;">{_signed_col(model_cum[i], maxabs, MODEL_C)}</td>'
            f'<td style="vertical-align:bottom;padding-left:2px;">'
            f'{_signed_col(spy_cum[i], maxabs, SPY_C)}</td>'
            '</tr></table>'
            f'<div style="font-size:11px;color:#999;margin-top:5px;">{_weekday(d)}</div></td>')
    legend = (
        '<div style="font-size:12px;color:#555;margin:0 0 10px;">'
        f'<span style="display:inline-block;width:10px;height:10px;background:{MODEL_C};'
        'border-radius:2px;"></span> Model'
        '<span style="display:inline-block;width:16px;"></span>'
        f'<span style="display:inline-block;width:10px;height:10px;background:{SPY_C};'
        'border-radius:2px;"></span> S&amp;P 500</div>')
    caption = (f'<p style="font-size:13px;color:#333;margin:10px 0 0;">Week to date: '
               f'<b style="color:{MODEL_C};">Model {_fmt(model_cum[-1])}</b> &nbsp;vs&nbsp; '
               f'<b style="color:{SPY_C};">S&amp;P 500 {_fmt(spy_cum[-1])}</b>. '
               'Bars are cumulative return from the start of the window.</p>')
    return (legend
            + '<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
              '<tr>' + "".join(cols) + '</tr></table>' + caption)


def model_attribution(positions, prices):
    """Dollar-weighted contribution (pts) to the model's weekly return, by sector.
    Returns (total_pct, [(sector, contrib_pts, n)] best→worst) or (None, [])."""
    smap = _sectors_map()
    base, rows = 0.0, []
    for p in positions:
        tk, pr, ep = p["ticker"], prices.get(p["ticker"]), p.get("entry_price")
        ps = p.get("position_size") or 2000.0
        if not pr or not ep:
            continue
        try:
            sh = float(ps) / float(ep)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        base += sh * pr["start"]
        rows.append((tk, sh, pr["start"], pr["end"]))
    if base <= 0 or not rows:
        return None, []
    by_sec, total = {}, 0.0
    for tk, sh, st, en in rows:
        c = sh * (en - st) / base * 100.0
        total += c
        agg = by_sec.setdefault(smap.get(tk, "Other"), [0.0, 0])
        agg[0] += c
        agg[1] += 1
    out = sorted(((s, v[0], v[1]) for s, v in by_sec.items()),
                 key=lambda x: x[1], reverse=True)
    return total, out


def _attribution_sentence(positions, prices, spy):
    total, secs = model_attribution(positions, prices)
    if total is None or not secs:
        return ""
    lead = secs[0]
    lead_word = "contributed most" if lead[1] >= 0 else "held up best"
    parts = [f"<b>{lead[0]}</b> {lead_word} "
             f"(<span style='color:{_col(lead[1])};'>{_fmt(lead[1])}</span> pts)"]
    tail = secs[-1]
    if tail[0] != lead[0] and tail[1] < 0:
        parts.append(f"<b>{tail[0]}</b> weighed most "
                     f"(<span style='color:{_col(tail[1])};'>{_fmt(tail[1])}</span> pts)")
    sent = "Within the model this week, " + ", and ".join(parts) + "."
    if spy is not None:
        diff = total - spy
        sent += (f" Net, it finished <b style='color:{_col(diff)};'>"
                 f"{_fmt(abs(diff)).lstrip('+')}</b> "
                 f"{'ahead of' if diff >= 0 else 'behind'} the S&amp;P.")
    return f'<p style="font-size:14px;color:#333;line-height:1.65;margin:10px 0 0;">{sent}</p>'


def model_turnover(sb, since_iso):
    """(entries, exits) the model made within the window. Excludes bulk reseeds."""
    try:
        from model_engine import MODEL_EPOCH
    except Exception:
        MODEL_EPOCH = "live"
    entries, exits = [], []
    try:
        for r in (sb.table("model_portfolio_positions")
                  .select("ticker,entry_date,entry_price,entry_score")
                  .eq("epoch", MODEL_EPOCH).gte("entry_date", since_iso)
                  .order("entry_date", desc=True).execute().data or []):
            if r.get("ticker"):
                entries.append((r["ticker"].upper(), str(r.get("entry_date"))[:10],
                                r.get("entry_price"), r.get("entry_score")))
    except Exception as e:
        log.error("turnover entries failed: %s", e)
    try:
        for r in (sb.table("model_portfolio_positions")
                  .select("ticker,exit_date,exit_price,exit_reason")
                  .eq("epoch", MODEL_EPOCH).gte("exit_date", since_iso)
                  .order("exit_date", desc=True).execute().data or []):
            if r.get("ticker") and (r.get("exit_reason") or "") != "reseeded":
                exits.append((r["ticker"].upper(), str(r.get("exit_date"))[:10],
                              r.get("exit_price"), r.get("exit_reason")))
    except Exception as e:
        log.error("turnover exits failed: %s", e)
    return entries, exits


def turnover_html(entries, exits):
    if not entries and not exits:
        return ""

    def chips(items, bg, fg, sign):
        out = []
        for tk, d, *_ in items[:10]:
            out.append(
                f'<span style="display:inline-block;background:{bg};color:{fg};'
                f'font-weight:700;font-size:13px;border-radius:5px;padding:3px 9px;'
                f'margin:3px 6px 3px 0;">{sign}{tk} '
                f'<span style="font-weight:400;color:#999;">{_weekday(d)}</span></span>')
        return "".join(out)

    inner = ""
    if entries:
        inner += ('<div style="margin:2px 0 8px;"><div style="font-size:13px;color:#555;'
                  'font-weight:700;margin-bottom:2px;">Entered</div>'
                  + chips(entries, "#e7f7f1", "#15a97a", "+") + '</div>')
    if exits:
        inner += ('<div style="margin:2px 0;"><div style="font-size:13px;color:#555;'
                  'font-weight:700;margin-bottom:2px;">Exited</div>'
                  + chips(exits, "#fbeaea", "#c0392b", "\u2212") + '</div>')
    return _section("Model changes this week", inner)


def _include_opportunity() -> bool:
    # Default ON. Set DIGEST_OPPORTUNITY=0 (or false/no/off) to suppress the
    # "Opportunity of the week" section (a named high-conviction/cheap stock).
    val = _cfg("DIGEST_OPPORTUNITY")
    if val is None:
        return True
    return str(val).strip().lower() not in ("0", "false", "no", "off")


def _headline_sentence(spy, wl_rows, ho_rows, prices):
    """One-line narrative lede: macro regime + sector leadership (or SPY).
    Gives the email a story before the statistics. Returns '' if nothing to say."""
    bits = []
    try:
        from data_refresh import _load_macro_state
        rg = str((_load_macro_state() or {}).get("regime") or "NEUTRAL").upper()
        rw = {"RISK_ON": "a risk-on", "RISK_OFF": "a risk-off"}.get(rg, "a neutral")
        bits.append(f"QNTM&rsquo;s overlay reads {rw} backdrop")
    except Exception:
        pass
    tickers = [t for t, _ in wl_rows] + [t for t, _ in ho_rows]
    perf = _sector_perf(tickers, prices, min_names=2) if prices else []
    if len(perf) >= 2 and (perf[0][1] - perf[-1][1]) >= 1.0:
        bits.append(f"{perf[0][0]} outperformed while {perf[-1][0]} lagged across your names")
    elif spy is not None:
        bits.append(f"the S&amp;P 500 {'rose' if spy >= 0 else 'fell'} {_fmt(spy).lstrip('+')}")
    if not bits:
        return ""
    sentence = bits[0] if len(bits) == 1 else bits[0] + ", " + " and ".join(bits[1:])
    sentence = sentence[0].upper() + sentence[1:]
    return ('<p style="font-size:15px;color:#0a0b14;line-height:1.55;margin:16px 0 2px;'
            'font-weight:700;border-left:3px solid #15a97a;padding-left:12px;">'
            'This week in one sentence: ' + sentence + '.</p>')


_OPP_PILLAR_LABEL = {
    "momentum":  "price momentum",
    "quality":   "quality fundamentals",
    "volume":    "volume / accumulation",
    "sentiment": "sentiment",
}


def _opportunity_drivers(row):
    """Up to two strongest NON-valuation pillars (>=55), highest first, as
    (label, score) pairs. Cheapness is carried separately by value position, so
    the value pillar is intentionally excluded to avoid a circular 'cheap because
    cheap' read. Purely descriptive — the model's own factor scores, not advice."""
    pillars = []
    for k in ("momentum", "quality", "volume", "sentiment"):
        try:
            v = float(row.get(k))
        except (TypeError, ValueError):
            continue
        if v >= 55:
            pillars.append((_OPP_PILLAR_LABEL[k], v))
    pillars.sort(key=lambda kv: kv[1], reverse=True)
    return pillars[:2]


def _opportunity_why(tk, conv, vp, row):
    """One factual sentence explaining why this name surfaced: its composite, the
    pillars driving it, and where it sits in its valuation range. Impersonal."""
    drivers = _opportunity_drivers(row)
    _d = lambda v: "strong" if v >= 65 else "solid"
    if len(drivers) >= 2:
        driver = (f"led by {_d(drivers[0][1])} {drivers[0][0]} ({drivers[0][1]:.0f}) "
                  f"and {_d(drivers[1][1])} {drivers[1][0]} ({drivers[1][1]:.0f})")
    elif len(drivers) == 1:
        driver = f"led by {_d(drivers[0][1])} {drivers[0][0]} ({drivers[0][1]:.0f})"
    else:
        driver = "supported by a balanced composite across factors"
    if vp <= 10:
        vp_phrase = "the very bottom of its valuation range"
    elif vp <= 25:
        vp_phrase = "the low end of its valuation range"
    else:
        vp_phrase = "the lower half of its valuation range"
    return (f"{tk} scores {conv:.0f} on QNTM\u2019s composite, {driver}, while a value "
            f"position of {vp:.0f}% places it at {vp_phrase}. High conviction meeting a "
            f"low relative price is what surfaces it here.")


def opportunity_of_week(sb, uid=None):
    """Highest-conviction name trading cheapest in its valuation range, from the
    latest signal_log day — a reason to come back into the app. Impersonal research
    signal, not a recommendation. Returns '' if nothing qualifies."""
    base = _app_url()
    try:
        latest = (sb.table("signal_log").select("signal_date")
                  .order("signal_date", desc=True).limit(1).execute().data or [])
        if not latest:
            return ""
        sd = latest[0]["signal_date"]
        rows = (sb.table("signal_log")
                .select("ticker,adj_composite,composite,value_position,val_basis,signal,"
                        "momentum,quality,volume,value,sentiment")
                .eq("signal_date", sd).execute().data or [])
    except Exception:
        return ""
    best, best_score = None, -1.0
    for r in rows:
        conv = float(r.get("adj_composite") or r.get("composite") or 0)
        if conv < 60 or (r.get("val_basis") or "na") == "na":
            continue
        try:
            vp = float(r.get("value_position"))
        except (TypeError, ValueError):
            continue
        if vp > 40:           # must be genuinely cheap to be an "opportunity"
            continue
        blend = 0.65 * conv + 0.35 * (100.0 - vp)
        if blend > best_score:
            best, best_score = r, blend
    if not best:
        return ""
    tk = best["ticker"]
    conv = float(best.get("adj_composite") or best.get("composite") or 0)
    vp = float(best.get("value_position"))
    sig = (best.get("signal") or "HIGH").upper()
    sub = "near lower range" if vp <= 25 else "lower half of range"
    link = f"{base}/screener?utm_source=newsletter&utm_medium=email&utm_campaign=weekly_digest"
    why = _opportunity_why(tk, conv, vp, best)
    card = (
        '<div style="border:1px solid #d7ece3;background:#f4fbf8;border-radius:10px;'
        'padding:16px 18px;margin:6px 0;">'
        # Header (ticker + conviction badge) — table, not flex (Gmail drops flex).
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="border-collapse:collapse;"><tr>'
        f'<td style="font-size:20px;font-weight:800;color:#0a0b14;">{tk}</td>'
        '<td align="right" style="font-size:12px;font-weight:700;color:#15a97a;'
        f'letter-spacing:.04em;">{sig} CONVICTION</td>'
        '</tr></table>'
        # Metrics — two table cells with explicit spacing (flex gap is dropped in
        # Gmail, which ran the two labels together in the rendered email).
        '<table role="presentation" cellpadding="0" cellspacing="0" '
        'style="border-collapse:collapse;margin:12px 0 8px;"><tr>'
        '<td style="padding-right:40px;vertical-align:top;">'
        '<div style="font-size:11px;color:#888;text-transform:uppercase;'
        'letter-spacing:.05em;">Conviction</div>'
        f'<div style="font-size:22px;font-weight:800;color:#15a97a;">{conv:.0f}</div></td>'
        '<td style="vertical-align:top;">'
        '<div style="font-size:11px;color:#888;text-transform:uppercase;'
        'letter-spacing:.05em;">Value position</div>'
        f'<div style="font-size:22px;font-weight:800;color:#15a97a;">{vp:.0f}%</div>'
        f'<div style="font-size:11px;color:#888;">{sub}</div></td>'
        '</tr></table>'
        # The actual reasoning — derived from the model's own pillar scores.
        f'<p style="font-size:13px;color:#333;line-height:1.6;margin:2px 0 10px;">{why}</p>'
        f'<a href="{link}" style="font-size:13px;font-weight:700;color:#15a97a;'
        f'text-decoration:none;">See {tk} on QNTM &rarr;</a>'
        '</div>'
        '<p style="font-size:11px;color:#999;margin:6px 0 0;line-height:1.5;">'
        'Surfaced because it is the highest-conviction name currently trading cheapest '
        'in its valuation range. An impersonal research signal, not a recommendation or '
        'personalized advice.</p>')
    return _section("Opportunity of the week", card)


def _whats_new_section(limit=3):
    """Recent product updates, pulled from the same source as the in-app popup
    so there's one changelog to maintain."""
    try:
        from whats_new import WHATS_NEW
    except Exception:
        return ""
    entries = sorted(WHATS_NEW, key=lambda e: e.get("id", ""), reverse=True)[:limit]
    if not entries:
        return ""
    items = []
    for e in entries:
        tag = (e.get("tag") or "new").lower()
        tag_col = "#15a97a" if tag == "new" else "#b88600"
        tag_bg = "#e7f7f1" if tag == "new" else "#fbf3dc"
        items.append(
            '<div style="margin:0 0 12px;">'
            f'<span style="font-size:10px;font-weight:800;letter-spacing:.06em;'
            f'text-transform:uppercase;color:{tag_col};background:{tag_bg};'
            f'border-radius:4px;padding:1px 6px;">{tag}</span> '
            f'<span style="font-size:14px;font-weight:700;color:#0a0b14;">{e.get("title","")}</span>'
            f'<div style="font-size:13px;color:#555;line-height:1.6;margin-top:3px;">'
            f'{e.get("body","")}</div></div>')
    return _section("New in QNTM", "".join(items))


# ── QNTM 101 — short educational footer, rotates weekly ───────────────────────
# Plain-language explainers of how QNTM's signals are built. Grounded in the real
# methodology so each note teaches a concept AND demystifies the product. Purely
# educational/general — never advice. One shows per send, cycling by ISO week so a
# weekly reader sees a different concept each Saturday.
_QNTM_101 = [
    ("How conviction is scored",
     "Conviction is one 0\u2013100 score that blends five factors \u2014 momentum, "
     "quality, volume, value and sentiment \u2014 weighted toward momentum and "
     "quality, the steadiest historical predictors. HIGH (\u226560) means several "
     "factors line up at once, not just a hot price. A single strong factor rarely "
     "clears the bar on its own."),
    ("Why macro nudges some sectors and not others",
     "On top of each stock's factor score, QNTM applies a macro overlay that tilts "
     "whole sectors up or down based on the current regime \u2014 read from news, the "
     "VIX, oil and rate expectations. A hawkish-rate read, for example, pressures "
     "long-duration sectors like tech, REITs and utilities while helping banks. The "
     "tilt is the same direction textbooks predict; QNTM just sizes it to the regime."),
    ("The overlay leans harder when markets are stressed",
     "The macro overlay isn't a fixed weight. In calm, trending markets the quant "
     "factors lead and macro is dialed down to ~10\u201315%. When volatility spikes "
     "(risk-off), the overlay gets more say \u2014 up to ~35% \u2014 because broad "
     "regime moves matter more than single-stock factors during drawdowns."),
    ("What 'value position' actually means",
     "Value position shows where today's price sits inside a stock's own QNTM "
     "valuation band: 0% is the cheap end, 100% the rich end. It's descriptive "
     "context, not a price target. A high-conviction name at a low value position is "
     "the model flagging strong factors AND an attractive price relative to its own range."),
    ("Why a signal can change when the price barely moved",
     "Conviction is recomputed daily on fresh data and it's relative across the whole "
     "universe. A stock can slip from HIGH to MODERATE because its momentum cooled or "
     "a macro headwind hit its sector \u2014 even if its share price hardly budged. "
     "You're seeing a multi-factor ranking, not just a price chart."),
    ("One reason the model caps each sector",
     "The model portfolio never lets a single sector exceed ~30% of its positions. "
     "It's a simple risk rule: if one macro shock hits, say, semiconductors, a capped "
     "book takes a dent rather than a crater. Concentration is where a lot of avoidable "
     "drawdown comes from \u2014 a principle any portfolio can borrow."),
]


def _education_note():
    """A single QNTM 101 explainer, rotated by ISO week so it varies week to week."""
    if not _QNTM_101:
        return ""
    try:
        wk = datetime.now(timezone.utc).isocalendar()[1]
    except Exception:
        wk = 0
    title, body = _QNTM_101[wk % len(_QNTM_101)]
    return (
        '<div style="border-top:1px solid #eee;margin:22px 0 0;padding-top:16px;">'
        '<div style="font-size:10px;font-weight:800;letter-spacing:.08em;'
        'text-transform:uppercase;color:#15a97a;margin-bottom:6px;">QNTM 101</div>'
        f'<div style="font-size:14px;font-weight:700;color:#0a0b14;margin-bottom:4px;">{title}</div>'
        f'<div style="font-size:13px;color:#555;line-height:1.65;">{body}</div>'
        '<div style="font-size:11px;color:#aaa;margin-top:8px;">General education on how '
        'QNTM\u2019s signals work \u2014 not investment advice.</div>'
        '</div>')


def build_email_html(sb, wl, ho, prices, positions, model_ret, model_used, spy, uid=None):
    base = _app_url()
    # Tracked CTA: /?src=digest&du=<uid> lets the app log a 'digest_click' event
    # per recipient (see app.py). Falls back to the plain app URL if no uid.
    cta = f"{base}/screener?utm_source=newsletter&utm_medium=email&utm_campaign=weekly_digest"

    def _rows(tickers):
        return sorted([(t, prices[t]["pct"]) for t in tickers if t in prices],
                      key=lambda x: x[1], reverse=True)

    wl_rows = _rows(wl)
    ho_rows = _rows(ho)
    movers = sorted([(t, prices[t]["pct"]) for t in set(wl) | set(ho) if t in prices],
                    key=lambda x: x[1], reverse=True)

    parts = []
    headline = _headline_sentence(spy, wl_rows, ho_rows, prices)
    if headline:
        parts.append(headline)
    commentary = _commentary(spy, model_ret, wl_rows, ho_rows, movers, prices=prices)
    if commentary:
        parts.append(commentary)

    macro = macro_backdrop(sb)
    if macro:
        parts.append(macro)

    if movers:
        mv = movers[:3] + [m for m in movers[::-1] if m[1] < 0][:3]
        seen = set()
        mv = [m for m in mv if not (m[0] in seen or seen.add(m[0]))]
        parts.append(_section("Biggest movers on your lists", _bar_table(mv)))

    if _include_performance() and model_ret is not None and spy is not None:
        diff = model_ret - spy
        block = [
            '<p style="font-size:14px;color:#333;line-height:1.65;margin:0 0 10px;">'
            'The model portfolio is '
            f"<b style='color:{_col(diff)};'>{_fmt(abs(diff)).lstrip('+')}</b> "
            f"{'ahead of' if diff >= 0 else 'behind'} the S&amp;P 500 this week "
            f"(<b style='color:{_col(model_ret)};'>{_fmt(model_ret)}</b> vs "
            f"<b style='color:{_col(spy)};'>{_fmt(spy)}</b>)."
            '</p>'
        ]
        dates, mcum, scum = perf_paths(sb, positions, prices)
        if dates:
            block.append(
                '<div style="border-top:1px solid #eee;border-bottom:1px solid #eee;'
                'padding:14px 0;margin:8px 0;">' + perf_chart_html(dates, mcum, scum) + '</div>')
        else:
            block.append(_bar_table([("Model", model_ret), ("SPY", spy)]))
        attr = _attribution_sentence(positions, prices, spy)
        if attr:
            block.append(attr)
        block.append('<p style="font-size:12px;color:#888;margin:8px 0 0;">Hypothetical, '
                     f'dollar-weighted across {model_used} equal-size positions. '
                     'Past performance does not guarantee future results.</p>')
        parts.append(_section("Model portfolio vs SPY", "".join(block)))

        since = _week_start_iso()
        ent, ex = model_turnover(sb, since)
        tn = turnover_html(ent, ex)
        if tn:
            parts.append(tn)

    if wl:
        parts.append(_section("Your watchlist", _bar_table(wl_rows)))
    if ho:
        parts.append(_section("Your portfolio", _bar_table(ho_rows)))

    if _include_opportunity():
        opp = opportunity_of_week(sb, uid=uid)
        if opp:
            parts.append(opp)

    if not parts:
        parts.append('<p style="font-size:14px;color:#333;">Add stocks to your watchlist or '
                     'portfolio to get a personalized weekly recap.</p>')

    whats_new = _whats_new_section(limit=3)
    if whats_new:
        parts.append(whats_new)

    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:540px;margin:0 auto;padding:24px;">'
        '<div style="font-size:22px;font-weight:800;letter-spacing:.04em;color:#0a0b14;">'
        'Q<span style="color:#15a97a;">NTM</span> <span style="font-size:14px;font-weight:600;'
        'color:#888;">· Weekly recap</span></div>'
        + "".join(parts)
        + f'<p style="margin:24px 0;"><a href="{cta}" style="display:inline-block;background:#15a97a;'
        'color:#fff;text-decoration:none;padding:12px 26px;border-radius:8px;font-weight:700;'
        'font-size:15px;">Open QNTM</a></p>'
        + _education_note()
        + '<p style="font-size:12px;color:#999;line-height:1.6;">Weekly moves are price changes over '
        'roughly the last five trading days from QNTM\'s stored data. Conviction scores and the model '
        'portfolio are algorithmic outputs for research, not recommendations or personalized advice. '
        'The model portfolio is hypothetical and equal-weighted; past performance does not guarantee '
        'future results. You make your own investment decisions.</p>'
        '<p style="font-size:12px;color:#aaa;line-height:1.5;margin-top:14px;">You receive this because '
        'weekly summaries are on in Account &rarr; Notifications. Turn them off there anytime.<br>'
        'QNTM LLC \u00b7 35 Laguna Woods Drive, Laguna Niguel, CA 92677</p></div>'
    )


def _find_user_by_email(sb, email):
    """Locate a user row by decrypted email (used by the test path)."""
    from db import decrypt_field
    try:
        rows = sb.table("users").select(
            "id,email_encrypted,email_verified,notifications").execute().data or []
    except Exception:
        return None, None
    for u in rows:
        dec = decrypt_field(u.get("email_encrypted", "") or "")
        if dec and dec.lower() == email.lower():
            return u, dec
    return None, None


def run(only_email=None):
    try:
        from data_refresh import _get_supabase
    except Exception as e:
        log.error("cannot import _get_supabase: %s", e)
        return {"success": False}
    sb = _get_supabase()
    if not sb:
        log.error("no supabase service client")
        return {"success": False}

    if only_email:
        # Test path: send to this address regardless of the verified/pref gates,
        # but report whether the real cron WOULD deliver to it.
        u, dec = _find_user_by_email(sb, only_email)
        if not u:
            log.error("No QNTM account found with email %s — sign up / log in with it first.", only_email)
            return {"success": False, "error": "no such user"}
        notifs = u.get("notifications") or {}
        if isinstance(notifs, str):
            try:
                notifs = json.loads(notifs)
            except Exception:
                notifs = {}
        would = bool(u.get("email_verified") and notifs.get("email"))
        log.info("TEST send to %s | email_verified=%s, email_pref=%s -> cron would deliver: %s",
                 only_email, u.get("email_verified"), notifs.get("email"), would)
        if not would:
            log.warning("Heads up: in the real weekly cron this user is currently SKIPPED. "
                        "Fix by verifying the email and enabling 'Email signal summaries' in "
                        "Account -> Notifications (and saving).")
        recips = {u["id"]: dec}
    else:
        recips = recipients(sb)
    if not recips:
        log.info("No digest recipients.")
        return {"success": True, "recipients": 0}

    positions = model_positions(sb)
    per_user = {uid: user_lists(sb, uid) for uid in recips}
    need = {p["ticker"] for p in positions}
    for wl, ho in per_user.values():
        need |= set(wl) | set(ho)
    prices = weekly_prices(sb, need)
    spy = spy_week(sb)
    model_ret, model_used = model_dollar_weighted_return(positions, prices)
    log.info("%d recipients · %d tickers priced · spy=%s · model=%s (%d pos)",
             len(recips), len(prices), None if spy is None else round(spy, 2),
             None if model_ret is None else round(model_ret, 2), model_used)

    from db import send_email
    sent = 0
    for uid, email in recips.items():
        wl, ho = per_user[uid]
        html = build_email_html(sb, wl, ho, prices, positions, model_ret, model_used, spy, uid=uid)
        res = send_email(email, "Your QNTM weekly recap", html,
                         text="Your QNTM weekly recap is ready. Open QNTM: "
                              + _app_url() + "/screener?utm_source=newsletter&utm_medium=email&utm_campaign=weekly_digest")
        if res.get("success"):
            sent += 1
    log.info("done: %d recipients, %d emails sent", len(recips), sent)
    return {"success": True, "recipients": len(recips), "sent": sent}


def spy_week(sb):
    since = _week_start_iso()
    try:
        rows = (sb.table("benchmark_price").select("d,close")
                .gte("d", since).order("d", desc=False).execute().data or [])
    except Exception as e:
        log.error("benchmark read failed: %s", e)
        return None
    seq = []
    for r in rows:
        if r.get("close") is not None:
            try:
                seq.append((str(r["d"])[:10], float(r["close"])))
            except (TypeError, ValueError):
                pass
    seq.sort()
    if len(seq) < 2 or not seq[0][1]:
        return None
    return (seq[-1][1] - seq[0][1]) / seq[0][1] * 100.0


if __name__ == "__main__":
    run(only_email=(sys.argv[1] if len(sys.argv) > 1 else None))
