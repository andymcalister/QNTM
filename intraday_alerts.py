"""
QNTM — Intraday Conviction-Drop Alert Job
=========================================
Runs every 30 minutes during US market hours (via Render Cron). For the union of
tickers that users HOLD or WATCH, it re-scores conviction with fresh intraday
price/volume (fundamentals frozen from the last nightly refresh, since those
don't move intraday), re-applies the macro overlay to get adj_composite, and
emails a user when one of their tickers' conviction drops to LOW from HIGH or
MODERATE.

Design guards (per the agreed spec):
  • Scope: watched/held tickers only — keeps yfinance within rate limits.
  • Trigger: conviction label drops to LOW (adj_composite < 45). No exit-
    threshold logic (that would read as advice).
  • Confirmation: the LOW label must hold for TWO consecutive runs before any
    email goes out (suppresses partial-day flip-flop noise).
  • Dedupe: one email per LOW episode — state is cleared once the ticker
    recovers to MODERATE/HIGH, so a future drop can fire again.
  • Gating: only users with a VERIFIED email who have explicitly opted into
    low-conviction alert emails (notifications.low_alert_email == True).
  • An in-app notification (the bell) is created alongside the email.

Run:  python intraday_alerts.py
Env/secrets required (same secrets.toml as the web service):
  SUPABASE_URL, SUPABASE_SERVICE_KEY, ENCRYPTION_KEY,
  SENDGRID_API_KEY, SENDGRID_FROM, APP_URL
"""

import os, sys, json, logging
from datetime import datetime, date, timezone

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("qntm.alerts")

# ── CONFIG ────────────────────────────────────────────────────────────────────
LOW_CONFIRM_RUNS = 2                  # consecutive LOW runs required before email
STATE_TABLE      = "intraday_alert_state"
HIGH_CUTOFF      = 60                 # adj_composite >= 60 → HIGH   (matches app)
MOD_CUTOFF       = 45                 # adj_composite >= 45 → MODERATE, else LOW

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:
    ET = None  # falls back to a UTC-offset gate below


# ── MARKET HOURS GATE ─────────────────────────────────────────────────────────

def market_is_open(now=None) -> bool:
    """True only Mon–Fri, 9:30 AM–4:00 PM ET. Render fires the cron on a UTC
    schedule; this is the precise gate (and handles DST when zoneinfo is present).
    NOTE: does not account for market holidays — acceptable; a holiday run just
    re-scores stale data and almost never crosses a threshold. Add a holiday list
    later if desired."""
    if ET is not None:
        now = now or datetime.now(ET)
    else:
        # Fallback: approximate ET as UTC-4 (EDT). Good enough as a coarse gate;
        # the UTC cron window already bounds this.
        from datetime import timedelta
        now = (now or datetime.now(timezone.utc)) - timedelta(hours=4)
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return (9 * 60 + 30) <= mins <= (16 * 60)


def label_of(adj: float) -> str:
    return "HIGH" if adj >= HIGH_CUTOFF else "MODERATE" if adj >= MOD_CUTOFF else "LOW"


# ── SUBSCRIBERS ───────────────────────────────────────────────────────────────

def gather_subscribers(sb):
    """Return (subs, emails):
       subs   = {TICKER: set(user_id)}  — eligible users watching/holding it
       emails = {user_id: decrypted_email}
    Eligible = verified email AND notifications.low_alert_email == True.
    Uses the SERVICE client (RLS-bypassing) for reliable batch reads."""
    from db import decrypt_field
    try:
        users = sb.table("users").select(
            "id,email_encrypted,notifications,email_verified"
        ).execute().data or []
    except Exception as e:
        log.error(f"users read failed: {e}")
        return {}, {}

    emails = {}
    eligible = []
    for u in users:
        notifs = u.get("notifications") or {}
        if isinstance(notifs, str):
            try:
                notifs = json.loads(notifs)
            except Exception:
                notifs = {}
        if u.get("email_verified") and notifs.get("low_alert_email"):
            em = decrypt_field(u.get("email_encrypted", "") or "")
            if em:
                eligible.append(u["id"])
                emails[u["id"]] = em

    if not eligible:
        return {}, {}

    subs = {}
    for uid in eligible:
        tickers = set()
        try:
            for h in (sb.table("holdings").select("ticker")
                      .eq("user_id", uid).execute().data or []):
                if h.get("ticker"):
                    tickers.add(h["ticker"].upper())
        except Exception:
            pass
        try:
            for w in (sb.table("watchlist_items").select("ticker")
                      .eq("user_id", uid).execute().data or []):
                if w.get("ticker"):
                    tickers.add(w["ticker"].upper())
        except Exception:
            pass
        for tk in tickers:
            subs.setdefault(tk, set()).add(uid)
    return subs, emails


# ── RE-SCORE ──────────────────────────────────────────────────────────────────

def _extract_series(data, tk):
    """Pull (closes_oldest_to_newest, vol_ratio) for one ticker from a yfinance
    download frame, handling both single- and multi-ticker shapes."""
    import pandas as pd  # noqa
    close = vol = None
    try:
        sub = data[tk]
        close = sub["Close"].dropna()
        vol   = sub["Volume"].dropna()
    except Exception:
        try:
            close = data["Close"][tk].dropna()
            vol   = data["Volume"][tk].dropna()
        except Exception:
            return None, None
    if close is None or len(close) < 5:
        return None, None
    closes = [round(float(x), 4) for x in close.tolist()]
    vol_ratio = None
    try:
        if vol is not None and len(vol) >= 5:
            recent = float(vol.iloc[-1])
            avg30  = float(vol.tail(30).mean()) or 0.0
            if avg30 > 0:
                vol_ratio = round(recent / avg30, 3)
    except Exception:
        vol_ratio = None
    return closes, vol_ratio


def rescore(tickers):
    """Recompute adj_composite for the given tickers using fresh price/volume and
    cached fundamentals. Returns {TICKER: adj_composite}."""
    import yfinance as yf
    from model_engine import score_stock, apply_macro_overlay, fetch_macro_overlay
    try:
        from data_refresh import load_cached_fundamentals, _load_macro_state
    except Exception:
        load_cached_fundamentals = lambda *a, **k: {}
        _load_macro_state = lambda *a, **k: {}

    tickers = sorted(tickers)
    funda = {}
    try:
        funda = load_cached_fundamentals() or {}
    except Exception as e:
        log.warning(f"fundamentals cache unavailable, using static: {e}")

    log.info(f"Re-scoring {len(tickers)} watched/held tickers")
    try:
        data = yf.download(tickers, period="1y", auto_adjust=True,
                           progress=False, threads=True, group_by="ticker")
    except Exception as e:
        log.error(f"yfinance download failed: {e}")
        return {}

    rows = []
    for tk in tickers:
        try:
            closes, vol_ratio = _extract_series(data, tk)
            if not closes:
                log.warning(f"{tk}: no price data; skipping")
                continue
            rows.append(score_stock(tk, price_history=closes,
                                    live_fundamentals=funda.get(tk),
                                    vol_ratio=vol_ratio))
        except Exception as e:
            log.warning(f"{tk}: score failed: {e}")

    if not rows:
        return {}
    try:
        macro = _load_macro_state() or fetch_macro_overlay(use_live_feeds=False)
        rows = apply_macro_overlay(rows, macro)
    except Exception as e:
        log.warning(f"macro overlay failed, using raw composite: {e}")

    out = {}
    for r in rows:
        adj = r.get("adj_composite")
        if adj is None:
            adj = r.get("composite", 50)
        out[r["ticker"]] = float(adj or 50)
    return out


# ── EMAIL ─────────────────────────────────────────────────────────────────────

def _app_url():
    try:
        import streamlit as st
        return (st.secrets.get("APP_URL") or os.getenv("APP_URL") or "https://qntm.live")
    except Exception:
        return os.getenv("APP_URL") or "https://qntm.live"


def _email_html(ticker, adj, when_et):
    base = _app_url().rstrip("/")
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:0 auto;padding:24px;">'
        '<div style="font-size:22px;font-weight:800;letter-spacing:.04em;color:#0a0b14;">'
        'Q<span style="color:#15a97a;">NTM</span></div>'
        f'<p style="font-size:15px;color:#333;line-height:1.5;">The intraday conviction signal for '
        f'<b>{ticker}</b> has moved to <b>LOW</b> as of {when_et}.</p>'
        f'<p style="font-size:14px;color:#555;line-height:1.5;">{ticker} is on your holdings or watchlist. '
        'This reflects a quantitative change in the model today; it is an algorithmic signal, '
        'not a recommendation to buy or sell.</p>'
        f'<p style="margin:22px 0;"><a href="{base}/" style="display:inline-block;background:#15a97a;'
        'color:#ffffff;text-decoration:none;padding:12px 26px;border-radius:8px;font-weight:700;'
        f'font-size:15px;">Open QNTM</a></p>'
        '<p style="font-size:12px;color:#999;line-height:1.5;">HIGH/MODERATE/LOW conviction signals are '
        'algorithmic outputs, not recommendations. You make your own investment decisions. '
        'Past model performance does not guarantee future results. Intraday signals are based on '
        'partial-day data and are more reactive than the end-of-day signal.</p>'
        '<p style="font-size:12px;color:#aaa;line-height:1.5;margin-top:18px;">'
        f'You are receiving this because you enabled low-conviction alerts and {ticker} is on your '
        'QNTM watchlist or portfolio. To stop these emails, turn off low-conviction alerts in '
        'Account &rarr; Notifications.<br>'
        'QNTM LLC · 35 Laguna Woods Drive, Laguna Niguel, CA 92677</p>'
        '</div>'
    )


def notify(uid, email, ticker, adj):
    from db import send_email, create_notification
    when_et = datetime.now(ET).strftime("%-I:%M %p ET") if ET else datetime.utcnow().strftime("%H:%M UTC")
    res = send_email(
        email,
        f"QNTM: {ticker} conviction moved to LOW",
        _email_html(ticker, adj, when_et),
        text=(f"The intraday conviction signal for {ticker} has moved to LOW as of {when_et}. "
              f"{ticker} is on your holdings or watchlist. This is an algorithmic signal, not a "
              f"recommendation. Open QNTM: {_app_url().rstrip('/')}/"),
    )
    try:
        create_notification(uid, ticker, "conviction_drop",
                            f"{ticker} moved to LOW conviction",
                            f"Intraday conviction for {ticker} dropped to LOW.")
    except Exception:
        pass
    return bool(res.get("success"))


# ── MAIN ──────────────────────────────────────────────────────────────────────

def run():
    if not market_is_open():
        log.info("Market closed — nothing to do.")
        return {"success": True, "skipped": "market_closed"}

    try:
        from data_refresh import _get_supabase
    except Exception as e:
        log.error(f"cannot import _get_supabase: {e}")
        return {"success": False, "error": "no supabase import"}
    sb = _get_supabase()
    if not sb:
        log.error("No Supabase service connection (check SUPABASE_SERVICE_KEY).")
        return {"success": False, "error": "no supabase"}

    subs, emails = gather_subscribers(sb)
    if not subs:
        log.info("No eligible subscribers / watched tickers — done.")
        return {"success": True, "subscribers": 0}

    universe = set(subs.keys())
    log.info(f"{len(emails)} eligible users · {len(universe)} distinct tickers")

    scores = rescore(universe)
    if not scores:
        log.warning("No scores computed — aborting (no state changes written).")
        return {"success": False, "error": "no scores"}

    # Load existing per-ticker state
    try:
        state = {r["ticker"]: r for r in (sb.table(STATE_TABLE).select("*").execute().data or [])}
    except Exception as e:
        log.error(f"state read failed: {e}")
        state = {}

    new_rows, fired = [], []
    now_iso = datetime.now(timezone.utc).isoformat()
    for tk, adj in scores.items():
        lab = label_of(adj)
        prev = state.get(tk, {})
        low_streak = int(prev.get("low_streak") or 0)
        alerted = bool(prev.get("alerted"))
        if lab == "LOW":
            low_streak += 1
            if low_streak >= LOW_CONFIRM_RUNS and not alerted:
                fired.append((tk, adj))
                alerted = True
        else:
            low_streak = 0
            alerted = False
        new_rows.append({
            "ticker": tk, "last_label": lab, "last_adj": round(adj, 1),
            "low_streak": low_streak, "alerted": alerted, "updated_at": now_iso,
        })

    # Persist state first (so a send failure can't cause duplicate alerts next run)
    try:
        if new_rows:
            sb.table(STATE_TABLE).upsert(new_rows, on_conflict="ticker").execute()
    except Exception as e:
        log.error(f"state write failed: {e}")

    sent = 0
    for tk, adj in fired:
        for uid in subs.get(tk, ()):
            em = emails.get(uid)
            if em and notify(uid, em, tk, adj):
                sent += 1
                log.info(f"ALERT {tk} → user {uid[:8]}… (adj={adj:.1f})")

    log.info(f"Run complete: {len(fired)} ticker(s) confirmed LOW, {sent} email(s) sent.")
    return {"success": True, "tickers": len(universe), "fired": len(fired), "emails_sent": sent}


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("success") else 1)
