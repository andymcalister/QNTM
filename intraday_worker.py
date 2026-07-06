#!/usr/bin/env python3
"""
QNTM intraday price worker — always-on freshness for the Model Portfolio.

WHY THIS EXISTS
---------------
The app reads stored prices only (no live yfinance on the request path), so the
Model Portfolio's displayed "today" numbers are exactly as fresh as the last
price write to Supabase. This worker is a tiny ALWAYS-ON loop that refreshes just
the HELD model-portfolio names + SPY every ~90s.

SESSIONS
--------
It now runs across THREE windows (all ET, Mon-Fri):
  pre      04:00-09:30  -> refresh_extended_prices(session="pre")   [pre_price/pre_close]
  regular  09:30-16:00  -> run_intraday_refresh(prices_only=True)   [the real `price` mark]
  post     16:00-20:00  -> refresh_extended_prices(session="post")  [post_price/post_close]
Pre/post writes go to SEPARATE columns and NEVER overwrite the regular `price`
that marks the equity curve — the book's value only changes during the regular
session, extended windows are display-only directional signal.

DEPLOY
------
Render Background Worker. Needs SUPABASE_SERVICE_KEY (env or the secrets.toml
Secret File copied to .streamlit/secrets.toml).
"""
import time
import logging
from datetime import datetime, timezone, timedelta

from data_refresh import _get_supabase, run_intraday_refresh, refresh_extended_prices

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:
    _ET = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [intraday_worker] %(levelname)s %(message)s",
)
log = logging.getLogger("intraday_worker")

REFRESH_SECONDS = 90      # cadence while any session is active
IDLE_SECONDS    = 300     # cadence while fully closed (just re-check the clock)


def market_session(now=None):
    """Return 'pre' | 'regular' | 'post' | None for the current ET time.
    DST-aware when zoneinfo is present. Holiday-agnostic — a holiday run just
    re-pulls flat prices and writes the same values, which is harmless."""
    if _ET is not None:
        now = now or datetime.now(_ET)
    else:
        now = (now or datetime.now(timezone.utc)) - timedelta(hours=4)
    if now.weekday() >= 5:
        return None
    mins = now.hour * 60 + now.minute
    if (4 * 60) <= mins < (9 * 60 + 30):
        return "pre"
    if (9 * 60 + 30) <= mins <= (16 * 60):
        return "regular"
    if (16 * 60) < mins <= (20 * 60):
        return "post"
    return None


def held_tickers():
    """Active model-portfolio holdings — the ~50 names whose freshness drives the
    Model Portfolio page. Returns [] on any failure so the caller skips the cycle
    cleanly rather than refreshing the wrong set."""
    try:
        from model_engine import MODEL_EPOCH as _EPOCH
    except Exception:
        _EPOCH = "live"
    try:
        sb = _get_supabase()
        if not sb:
            return []
        resp = sb.table("model_portfolio_positions") \
            .select("ticker") \
            .eq("is_active", True) \
            .eq("epoch", _EPOCH) \
            .execute()
        return sorted({r["ticker"] for r in (resp.data or []) if r.get("ticker")})
    except Exception as e:
        log.warning(f"held_tickers failed: {e}")
        return []


def main():
    log.info("intraday worker starting (held names + SPY; pre/regular/post, ~%ss active)",
             REFRESH_SECONDS)
    while True:
        try:
            sess = market_session()
            if sess is None:
                time.sleep(IDLE_SECONDS)
                continue
            held = held_tickers()
            if not held:
                log.warning("no held tickers resolved; skipping cycle")
                time.sleep(REFRESH_SECONDS)
                continue
            if sess == "regular":
                # writes held-name prices to signal_log.price AND SPY benchmark;
                # SKIPS exits/entries (freshness only — trading stays nightly/macro).
                res = run_intraday_refresh(tickers=held, prices_only=True)
                log.info("[regular] refreshed %d held + SPY -> %s", len(held), res)
            else:
                # pre/post: writes ONLY the extended columns, never the `price` mark.
                res = refresh_extended_prices(tickers=held, session=sess)
                log.info("[%s] extended refresh %d held + SPY -> %s", sess, len(held), res)
            time.sleep(REFRESH_SECONDS)
        except Exception as e:
            log.error("worker cycle error: %s", e)
            time.sleep(REFRESH_SECONDS)


if __name__ == "__main__":
    main()
