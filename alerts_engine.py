"""
QNTM price / value-position alert engine
========================================
Evaluates user-defined alerts (the `price_alerts` table) and fans out hits to
in-app notifications + email + SMS. Built to mirror intraday_alerts.py:
  • service Supabase client (RLS-bypassing) via data_refresh._get_supabase
  • state written BEFORE sending so a send crash can't double-fire next run
  • per-alert "armed" re-arm gate (fire once on crossing in; re-arm on crossing
    back out) so a hovering value/price doesn't spam every 30 minutes

Alert kinds (price_alerts.kind):
  value_lower      live value_position <= threshold (default 20)   ← Range hero
  value_upper      live value_position >= threshold (default 80)
  price_below      price <= threshold
  price_above      price >= threshold
  conviction_high  conviction_label(adj) == HIGH (rounded >= 65)
  model_portfolio_exit  ticker left the model portfolio (any exit_reason)
  conviction_low   conviction_label(adj) == LOW (rounded <= 55)
  gem              is_hidden_gem becomes true

value_position is recomputed live from the current signal_log price against the
stored band (val_low/val_high), so value alerts track the intraday price the
same way the card's marker does.

Run on a Render cron (see render.yaml: qntm-price-alerts) or locally:
    python3 alerts_engine.py
"""
import os
import json
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("qntm.alerts")

# Threshold defaults for kinds whose threshold is optional.
DEFAULTS = {"value_lower": 20.0, "value_upper": 80.0}

# Human label per kind for the in-app/notification copy.
KIND_LABEL = {
    "value_lower":     "lower value range",
    "value_upper":     "upper value range",
    "price_below":     "price below",
    "price_above":     "price above",
    "conviction_high": "HIGH conviction",
    "model_portfolio_exit": "removed from the model portfolio",
    "conviction_low":  "LOW conviction",
    "gem":             "hidden gem",
}


def _app_url() -> str:
    try:
        import streamlit as st
        return st.secrets.get("APP_URL") or os.getenv("APP_URL") or "https://qntm.live"
    except Exception:
        return os.getenv("APP_URL") or "https://qntm.live"


def _live_value_position(price, lo, hi):
    """Recompute value_position (0–100) from current price vs the stored band."""
    try:
        price, lo, hi = float(price), float(lo), float(hi)
        if hi <= lo:
            return None
        return max(0.0, min(100.0, (price - lo) / (hi - lo) * 100.0))
    except (TypeError, ValueError):
        return None


def load_snapshots(sb, tickers):
    """Latest signal_log row per ticker with the fields predicates need.
    Adds `_live_vp` (live value_position from current price vs band)."""
    out = {}
    tickers = list(tickers)
    if not tickers:
        return out
    try:
        rows = (sb.table("signal_log")
                .select("ticker,price,adj_composite,composite,value_position,"
                        "val_low,val_high,val_basis,is_hidden_gem,signal_date")
                .in_("ticker", tickers)
                .order("signal_date", desc=True)
                .limit(len(tickers) * 3)
                .execute().data or [])
    except Exception as e:
        log.error("snapshot read failed: %s", e)
        return out
    for r in rows:
        tk = r.get("ticker")
        if not tk or tk in out:
            continue
        vp = r.get("value_position")
        live = _live_value_position(r.get("price"), r.get("val_low"), r.get("val_high"))
        r["_live_vp"] = live if live is not None else vp
        out[tk] = r
    return out


# ── Model-portfolio exits (for the model_portfolio_exit alert) ───────────────
# Loaded once per process and cached: the alert engine evaluates many tickers
# per run and the exit set is small. Read-only; never touches portfolio logic.
_MP_EXIT_CACHE = None


def _mp_exits(lookback_days: int = 3) -> dict:
    """{TICKER: {exit_date, exit_score, exit_reason}} for recent exits."""
    global _MP_EXIT_CACHE
    if _MP_EXIT_CACHE is not None:
        return _MP_EXIT_CACHE
    out = {}
    try:
        from datetime import date, timedelta
        from data_refresh import _get_supabase
        sb = _get_supabase()
        if sb:
            since = (date.today() - timedelta(days=lookback_days)).isoformat()
            rows = (sb.table("model_portfolio_positions")
                    .select("ticker,exit_date,exit_score,exit_reason")
                    .gte("exit_date", since).execute().data or [])
            for r in rows:
                t = str(r.get("ticker") or "").upper()
                if not t:
                    continue
                prev = out.get(t)
                if not prev or str(r.get("exit_date")) > str(prev.get("exit_date")):
                    out[t] = r
    except Exception as e:
        print("[alerts] model-portfolio exit load failed: " + repr(e))
    _MP_EXIT_CACHE = out
    return out


def evaluate(kind, threshold, snap):
    """Return (condition_met: bool, value: float|None, headline: str)."""
    try:
        price = float(snap.get("price")) if snap.get("price") is not None else None
    except (TypeError, ValueError):
        price = None
    adj_raw = snap.get("adj_composite")
    if adj_raw is None:
        adj_raw = snap.get("composite")
    try:
        adj = float(adj_raw) if adj_raw is not None else None
    except (TypeError, ValueError):
        adj = None
    vp = snap.get("_live_vp")
    gem = bool(snap.get("is_hidden_gem"))
    th = threshold if threshold is not None else DEFAULTS.get(kind)

    if kind == "value_lower":
        if vp is None or th is None:
            return False, vp, ""
        return (vp <= th, vp, f"entered the lower value range ({vp:.0f}%)")
    if kind == "value_upper":
        if vp is None or th is None:
            return False, vp, ""
        return (vp >= th, vp, f"entered the upper value range ({vp:.0f}%)")
    if kind == "price_below":
        if price is None or th is None:
            return False, price, ""
        return (price <= th, price, f"fell to ${price:,.2f} (\u2264 ${th:,.2f})")
    if kind == "price_above":
        if price is None or th is None:
            return False, price, ""
        return (price >= th, price, f"rose to ${price:,.2f} (\u2265 ${th:,.2f})")
    if kind == "conviction_high":
        if adj is None:
            return False, adj, ""
        return (__import__("conviction").conviction_label(adj) == "HIGH", adj, f"moved to HIGH conviction ({adj:.0f})")
    if kind == "conviction_low":
        if adj is None:
            return False, adj, ""
        return (__import__("conviction").conviction_label(adj) == "LOW", adj, f"dropped to LOW conviction ({adj:.0f})")
    if kind == "model_portfolio_exit":
        tk = snap.get("ticker")
        ex = _mp_exits().get(str(tk).upper()) if tk else None
        if not ex:
            return False, None, ""
        reason = str(ex.get("exit_reason") or "").upper()
        sc = ex.get("exit_score")
        if reason == "THRESHOLD_CHANGE":
            tail = "conviction thresholds were updated"
        elif reason == "RECONSTITUTION":
            tail = "the universe was reconstituted"
        elif sc is not None:
            tail = "conviction fell to %.0f" % float(sc)
        else:
            tail = "conviction fell below the hold range"
        val = float(sc) if sc is not None else None
        return (True, val, "was removed from the model portfolio \u2014 " + tail)
    if kind == "gem":
        return (gem, 1.0 if gem else 0.0, "was flagged a hidden gem \U0001F48E")
    return False, None, ""


def load_users(sb, uids):
    """Return {user_id: {email, email_verified, phone, phone_verified, notifs}}."""
    from db import decrypt_field
    out = {}
    uids = list(uids)
    if not uids:
        return out
    try:
        rows = (sb.table("users")
                .select("id,email_encrypted,phone,phone_verified,email_verified,notifications")
                .in_("id", uids).execute().data or [])
    except Exception as e:
        log.error("users read failed: %s", e)
        return out
    for u in rows:
        notifs = u.get("notifications") or {}
        if isinstance(notifs, str):
            try:
                notifs = json.loads(notifs)
            except Exception:
                notifs = {}
        out[u["id"]] = {
            "email":          decrypt_field(u.get("email_encrypted", "") or ""),
            "email_verified": bool(u.get("email_verified")),
            "phone":          u.get("phone"),
            "phone_verified": bool(u.get("phone_verified")),
            "notifs":         notifs,
        }
    return out


def _email_html(ticker, headline):
    base = _app_url().rstrip("/")
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:0 auto;padding:24px;">'
        '<div style="font-size:22px;font-weight:800;letter-spacing:.04em;color:#0a0b14;">'
        'Q<span style="color:#15a97a;">NTM</span></div>'
        f'<p style="font-size:15px;color:#333;line-height:1.5;"><b>{ticker}</b> {headline}.</p>'
        '<p style="font-size:14px;color:#555;line-height:1.5;">This is an alert you set on QNTM. '
        'It reflects a quantitative change in the model today; it is an algorithmic signal, not a '
        'recommendation to buy or sell.</p>'
        f'<p style="margin:22px 0;"><a href="{base}/" style="display:inline-block;background:#15a97a;'
        'color:#ffffff;text-decoration:none;padding:12px 26px;border-radius:8px;font-weight:700;'
        'font-size:15px;">Open QNTM</a></p>'
        '<p style="font-size:12px;color:#999;line-height:1.5;">You set this alert in QNTM. Manage or remove '
        'your alerts on the Alerts page. Valuation range and conviction are algorithmic outputs, not '
        'recommendations. You make your own investment decisions. Past model performance does not guarantee '
        'future results.</p>'
        '<p style="font-size:12px;color:#aaa;line-height:1.5;margin-top:18px;">'
        'QNTM LLC \u00b7 35 Laguna Woods Drive, Laguna Niguel, CA 92677</p>'
        '</div>'
    )


def notify(user, ticker, headline):
    """Fan out one fired alert to in-app + email + SMS per the user's verified
    channels and notification prefs. Returns the list of channels delivered."""
    from db import send_email, create_notification
    sent = []
    # In-app bell — always (cheap, no verification needed).
    try:
        create_notification(user["_id"], ticker, "price_alert",
                            f"{ticker} {headline}",
                            f"Your QNTM alert on {ticker}: {headline}.")
        sent.append("app")
    except Exception:
        pass
    n = user.get("notifs") or {}
    # Email — verified address + alert_email pref (default on).
    if user.get("email_verified") and user.get("email") and n.get("alert_email", True):
        r = send_email(
            user["email"],
            f"QNTM alert: {ticker} {headline}",
            _email_html(ticker, headline),
            text=f"{ticker} {headline}. Open QNTM: {_app_url().rstrip('/')}/",
        )
        if r.get("success"):
            sent.append("email")
    # SMS — verified phone + explicit alert_sms opt-in (default off).
    if user.get("phone_verified") and user.get("phone") and n.get("alert_sms"):
        try:
            from sms import send_sms
            r = send_sms(user["phone"], f"QNTM: {ticker} {headline}. {_app_url().rstrip('/')}")
            if r.get("success"):
                sent.append("sms")
        except Exception:
            pass
    return sent


def _collection_tickers(sb, scope, user_id):
    """Resolve the tickers a collection-scope alert covers.
      watchlist -> the user's watchlist_items
      portfolio -> the user's holdings
      model     -> the active model portfolio (global, epoch-gated)"""
    out = set()
    try:
        if scope == "watchlist":
            rows = (sb.table("watchlist_items").select("ticker")
                    .eq("user_id", user_id).execute().data or [])
        elif scope == "portfolio":
            rows = (sb.table("holdings").select("ticker")
                    .eq("user_id", user_id).execute().data or [])
        elif scope == "model":
            try:
                from model_engine import MODEL_EPOCH
            except Exception:
                MODEL_EPOCH = "live"
            rows = (sb.table("model_portfolio_positions").select("ticker")
                    .eq("is_active", True).eq("epoch", MODEL_EPOCH).execute().data or [])
        else:
            rows = []
        for r in rows:
            t = (r.get("ticker") or "").upper().strip()
            if t:
                out.add(t)
    except Exception as e:
        log.error("collection resolve failed (scope=%s): %s", scope, e)
    return out


def run():
    try:
        from data_refresh import _get_supabase
    except Exception as e:
        log.error("cannot import _get_supabase: %s", e)
        return {"success": False, "error": "no supabase import"}
    sb = _get_supabase()
    if not sb:
        log.error("No Supabase service connection (check SUPABASE_SERVICE_KEY).")
        return {"success": False, "error": "no supabase"}

    try:
        alerts = (sb.table("price_alerts").select("*").eq("active", True).execute().data or [])
    except Exception as e:
        log.error("alerts read failed: %s", e)
        return {"success": False, "error": "alerts read"}
    if not alerts:
        log.info("No active alerts — done.")
        return {"success": True, "alerts": 0}

    uids = {a.get("user_id") for a in alerts if a.get("user_id")}
    ticker_alerts = [a for a in alerts if (a.get("scope") or "ticker") == "ticker"]
    coll_alerts = [a for a in alerts if (a.get("scope") or "ticker") != "ticker"]

    # Resolve collection memberships once per (scope, user). Model scope is global.
    coll_cache = {}

    def _members(scope, user_id):
        key = (scope, "_" if scope == "model" else user_id)
        if key not in coll_cache:
            coll_cache[key] = _collection_tickers(sb, scope, user_id)
        return coll_cache[key]

    # Snapshot universe = every ticker any alert needs.
    universe = {(a.get("ticker") or "").upper() for a in ticker_alerts if a.get("ticker")}
    for a in coll_alerts:
        universe |= _members(a.get("scope"), a.get("user_id"))

    snaps = load_snapshots(sb, universe)
    users = load_users(sb, uids)
    now_iso = datetime.now(timezone.utc).isoformat()
    log.info("%d alerts (%d ticker, %d collection) · %d tickers · %d users",
             len(alerts), len(ticker_alerts), len(coll_alerts), len(universe), len(uids))

    fires = []  # (alert, ticker, headline)

    # ── Ticker-scope: dedupe via price_alerts.armed ────────────────────────────
    pa_updates = []
    for a in ticker_alerts:
        tk = (a.get("ticker") or "").upper()
        snap = snaps.get(tk)
        if not snap:
            continue
        met, val, headline = evaluate(a.get("kind"), a.get("threshold"), snap)
        armed = bool(a.get("armed", True))
        if met and armed:
            pa_updates.append({"id": a["id"], "armed": False,
                               "last_triggered_at": now_iso, "last_triggered_value": val})
            fires.append((a, tk, headline))
        elif (not met) and (not armed):
            pa_updates.append({"id": a["id"], "armed": True})

    for u in pa_updates:
        _id = u.pop("id")
        try:
            sb.table("price_alerts").update(u).eq("id", _id).execute()
        except Exception as e:
            log.error("state update failed for alert %s: %s", _id, e)

    # ── Collection-scope: dedupe via price_alert_state (alert_id, ticker) ───────
    if coll_alerts:
        coll_ids = [a["id"] for a in coll_alerts]
        try:
            st_rows = (sb.table("price_alert_state").select("*")
                       .in_("alert_id", coll_ids).execute().data or [])
        except Exception as e:
            log.error("alert_state read failed: %s", e)
            st_rows = []
        state = {(r["alert_id"], r["ticker"]): r for r in st_rows}
        st_upserts = []
        fired_parents = set()
        for a in coll_alerts:
            for tk in _members(a.get("scope"), a.get("user_id")):
                snap = snaps.get(tk)
                if not snap:
                    continue
                met, val, headline = evaluate(a.get("kind"), a.get("threshold"), snap)
                prev = state.get((a["id"], tk), {})
                armed = bool(prev.get("armed", True))
                if met and armed:
                    st_upserts.append({"alert_id": a["id"], "ticker": tk, "armed": False,
                                       "last_triggered_at": now_iso, "last_triggered_value": val})
                    fires.append((a, tk, headline))
                    fired_parents.add(a["id"])
                elif (not met) and (not armed):
                    st_upserts.append({"alert_id": a["id"], "ticker": tk, "armed": True})

        if st_upserts:
            try:
                sb.table("price_alert_state").upsert(st_upserts, on_conflict="alert_id,ticker").execute()
            except Exception as e:
                log.error("alert_state upsert failed: %s", e)
        # Stamp the parent row so the Alerts-page "last fired" reflects collections too.
        for pid in fired_parents:
            try:
                sb.table("price_alerts").update({"last_triggered_at": now_iso}).eq("id", pid).execute()
            except Exception:
                pass

    # ── Fan out ────────────────────────────────────────────────────────────────
    delivered = 0
    for a, tk, headline in fires:
        u = users.get(a.get("user_id"))
        if not u:
            continue
        u = dict(u)
        u["_id"] = a["user_id"]
        ch = notify(u, tk, headline)
        if ch:
            delivered += 1
            log.info("fired %s/%s (scope=%s) -> user %s via %s",
                     tk, a.get("kind"), a.get("scope") or "ticker", a.get("user_id"), ",".join(ch))

    log.info("done: %d alerts, %d fired, %d delivered", len(alerts), len(fires), delivered)
    return {"success": True, "alerts": len(alerts), "fired": len(fires), "delivered": delivered}


if __name__ == "__main__":
    run()
