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

COMPLIANCE: "Model portfolio vs SPY" is a performance/benchmark statement; it is
OMITTED unless DIGEST_PERFORMANCE=1, so the language can clear review first.
"""
import os
import sys
import json
import logging
from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("qntm.digest")

LOOKBACK_DAYS = 9  # ~one trading week of calendar days


def _cfg(key):
    try:
        import streamlit as st
        return st.secrets.get(key) or os.getenv(key)
    except Exception:
        return os.getenv(key)


def _app_url():
    return (_cfg("APP_URL") or "https://qntm.live").rstrip("/")


def _include_performance() -> bool:
    return str(_cfg("DIGEST_PERFORMANCE") or "0").strip().lower() in ("1", "true", "yes")


# ── Data ──────────────────────────────────────────────────────────────────────

def recipients(sb):
    """{user_id: email} for verified users opted into the weekly digest."""
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
    since = (datetime.now(timezone.utc).date() - timedelta(days=LOOKBACK_DAYS)).isoformat()
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
    return wl, ho


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


def _commentary(spy, model_ret, wl_rows, ho_rows, movers):
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
    if wl_rows:
        up = sum(1 for _, p in wl_rows if p >= 0)
        bits.append(f"{up} of {len(wl_rows)} watchlist names were up.")
    if ho_rows:
        up = sum(1 for _, p in ho_rows if p >= 0)
        bits.append(f"{up} of {len(ho_rows)} of your holdings were up.")
    if _include_performance() and model_ret is not None and spy is not None:
        diff = model_ret - spy
        bits.append(f"The model portfolio was "
                    f"<b style='color:{_col(diff)};'>{_fmt(abs(diff)).lstrip('+')}</b> "
                    f"{'ahead of' if diff >= 0 else 'behind'} SPY.")
    if not bits:
        return ""
    return ('<p style="font-size:14px;color:#333;line-height:1.65;margin:0;">'
            + " ".join(bits) + '</p>')


def build_email_html(wl, ho, prices, model_ret, model_used, spy):
    base = _app_url()

    def _rows(tickers):
        return sorted([(t, prices[t]["pct"]) for t in tickers if t in prices],
                      key=lambda x: x[1], reverse=True)

    wl_rows = _rows(wl)
    ho_rows = _rows(ho)
    movers = sorted([(t, prices[t]["pct"]) for t in set(wl) | set(ho) if t in prices],
                    key=lambda x: x[1], reverse=True)

    parts = []
    commentary = _commentary(spy, model_ret, wl_rows, ho_rows, movers)
    if commentary:
        parts.append(commentary)

    if movers:
        mv = movers[:3] + [m for m in movers[::-1] if m[1] < 0][:3]
        seen = set()
        mv = [m for m in mv if not (m[0] in seen or seen.add(m[0]))]
        parts.append(_section("Biggest movers on your lists", _bar_table(mv)))

    if _include_performance() and model_ret is not None and spy is not None:
        parts.append(_section("Model portfolio vs SPY", _bar_table(
            [("Model", model_ret), ("SPY", spy)])
            + '<p style="font-size:12px;color:#888;margin:6px 0 0;">Hypothetical, '
              f'dollar-weighted across {model_used} equal-size positions.</p>'))

    if wl:
        parts.append(_section("Your watchlist", _bar_table(wl_rows)))
    if ho:
        parts.append(_section("Your portfolio", _bar_table(ho_rows)))

    if not parts:
        parts.append('<p style="font-size:14px;color:#333;">Add stocks to your watchlist or '
                     'portfolio to get a personalized weekly recap.</p>')

    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:540px;margin:0 auto;padding:24px;">'
        '<div style="font-size:22px;font-weight:800;letter-spacing:.04em;color:#0a0b14;">'
        'Q<span style="color:#15a97a;">NTM</span> <span style="font-size:14px;font-weight:600;'
        'color:#888;">· Weekly recap</span></div>'
        + "".join(parts)
        + f'<p style="margin:24px 0;"><a href="{base}/" style="display:inline-block;background:#15a97a;'
        'color:#fff;text-decoration:none;padding:12px 26px;border-radius:8px;font-weight:700;'
        'font-size:15px;">Open QNTM</a></p>'
        '<p style="font-size:12px;color:#999;line-height:1.6;">Weekly moves are price changes over '
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
        html = build_email_html(wl, ho, prices, model_ret, model_used, spy)
        res = send_email(email, "Your QNTM weekly recap", html,
                         text="Your QNTM weekly recap is ready. Open QNTM: " + _app_url() + "/")
        if res.get("success"):
            sent += 1
    log.info("done: %d recipients, %d emails sent", len(recips), sent)
    return {"success": True, "recipients": len(recips), "sent": sent}


def spy_week(sb):
    since = (datetime.now(timezone.utc).date() - timedelta(days=LOOKBACK_DAYS)).isoformat()
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
