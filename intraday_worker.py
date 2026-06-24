#!/usr/bin/env python3
"""
QNTM intraday price worker — always-on freshness for the Model Portfolio.

WHY THIS EXISTS
---------------
The app reads stored prices only (no live yfinance on the request path), so the
Model Portfolio's displayed "today" numbers are exactly as fresh as the last
price write to Supabase. The full-universe refresh runs on a ~15-min GitHub
Actions cron, but scheduled GH Actions are unreliable (frequently delayed or
skipped), which repeatedly left stored prices stale mid-session — and in
stored-only mode that shows up directly as a frozen "today".

This worker is a tiny ALWAYS-ON loop that, during US market hours, refreshes
just the HELD model-portfolio names + SPY every ~90s. It's cheap (~50 tickers,
one yfinance batch) and depends on no external scheduler. The full-universe
cron stays as-is for the screener; this only keeps the names that actually drive
the Model Portfolio fresh.

DEPLOY
------
Runs as a Render Background Worker (type: worker) — see render.yaml. Needs
SUPABASE_SERVICE_KEY (RLS-bypassing) available to the process, same as the other
jobs: either as an env var, or via the secrets.toml Secret File that the start
command copies to .streamlit/secrets.toml. data_refresh._get_supabase reads env
first, then falls back to that secrets file.
"""
import time
import logging
from datetime import datetime, timezone, timedelta

from data_refresh import _get_supabase, run_intraday_refresh

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

REFRESH_SECONDS = 90      # cadence while the market is open
IDLE_SECONDS    = 300     # cadence while closed (just re-check the clock)


def market_is_open(now=None) -> bool:
    """Mon-Fri, 9:30 AM-4:00 PM ET (DST-aware when zoneinfo is present).
    Mirrors intraday_alerts.market_is_open. Holiday-agnostic — a holiday run just
    re-pulls flat prices and writes the same values, which is harmless."""
    if _ET is not None:
        now = now or datetime.now(_ET)
    else:
        now = (now or datetime.now(timezone.utc)) - timedelta(hours=4)
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return (9 * 60 + 30) <= mins <= (16 * 60)


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
    log.info("intraday worker starting (held names + SPY, ~%ss while open)",
             REFRESH_SECONDS)
    while True:
        try:
            if market_is_open():
                held = held_tickers()
                if held:
                    # run_intraday_refresh(prices_only=True) writes held-name
                    # prices to signal_log AND refreshes SPY benchmark_price (with
                    # updated_at) — but SKIPS exits/entries. The worker's job is
                    # freshness, not trading; portfolio decisions stay on the
                    # nightly / macro cadence. It self-skips names not scored for
                    # today, so an early pre-batch cycle is a harmless no-op.
                    res = run_intraday_refresh(tickers=held, prices_only=True)
                    log.info("refreshed %d held + SPY -> %s", len(held), res)
                else:
                    log.warning("no held tickers resolved; skipping cycle")
                time.sleep(REFRESH_SECONDS)
            else:
                time.sleep(IDLE_SECONDS)
        except Exception as e:
            log.error("worker cycle error: %s", e)
            time.sleep(REFRESH_SECONDS)


if __name__ == "__main__":
    main()
