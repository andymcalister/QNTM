"""
QNTM — Freeze the inception model-portfolio cohort.
================================================================================
Seals the original ("inception") model portfolio as a point-in-time reference so
a corrected cohort can run forward from today. This:

  1. Closes every still-active position at today's mark (is_active=False,
     exit_date=today, exit_price=current, exit_reason='EPOCH_FREEZE').
  2. Leaves epoch='inception' on those rows (the migration default), so they stay
     in model_portfolio_positions, sealed and dated — NOT deleted.

Nothing is erased. The frozen inception record remains fully queryable (e.g. for
an internal/admin view) but, once the Track Record page and cron are scoped to
epoch='live', it no longer appears on the live record.

Run AFTER applying migrations/add_model_portfolio_epoch.sql, and BEFORE
seed_live_portfolio.py.

    SUPABASE_URL='https://...' SUPABASE_SERVICE_KEY='...' python3 freeze_inception.py
    SUPABASE_URL='https://...' SUPABASE_SERVICE_KEY='...' python3 freeze_inception.py --execute
"""
import os, sys, argparse
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _get_supabase():
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url:
        try:
            import toml
            s = toml.load(".streamlit/secrets.toml")
            s = s.get("default", s) if isinstance(s, dict) else s
            url = s.get("SUPABASE_URL", "")
        except Exception:
            pass
    if not url or not key:
        print("ERROR: set SUPABASE_URL and SUPABASE_SERVICE_KEY (service key) in the environment.")
        sys.exit(1)
    from supabase import create_client
    return create_client(url, key)


def _live_price(ticker):
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        try:
            p = float(tk.fast_info.last_price)
            if p and p > 0:
                return p
        except Exception:
            pass
        h = tk.history(period="5d")
        if len(h):
            return float(h["Close"].iloc[-1])
    except Exception:
        pass
    return None


def main(execute: bool):
    sb = _get_supabase()
    today = date.today().isoformat()

    active = sb.table("model_portfolio_positions") \
        .select("id,ticker,entry_date,entry_price,epoch") \
        .eq("is_active", True).execute().data or []

    if not active:
        print("No active positions — nothing to freeze. (Already sealed?)")
        return

    # Latest scored day for price fallback
    md = sb.table("signal_log").select("signal_date") \
        .order("signal_date", desc=True).limit(1).execute().data
    sig_date = md[0]["signal_date"] if md else today
    score_rows = sb.table("signal_log").select("ticker,price") \
        .eq("signal_date", sig_date).range(0, 9999).execute().data or []
    price_map = {r["ticker"]: r.get("price") for r in score_rows}

    print(f"\nSealing {len(active)} active position(s) as the frozen 'inception' cohort (mark date {today}).\n")
    sealed, realized = [], 0.0
    for p in active:
        tk = p["ticker"]
        px = _live_price(tk)
        src = "live"
        if px is None and price_map.get(tk):
            px, src = float(price_map[tk]), "last signal_log"
        if px is None and p.get("entry_price"):
            px, src = float(p["entry_price"]), "entry (est)"
        ep = float(p["entry_price"]) if p.get("entry_price") is not None else None
        ret = ((px / ep - 1.0) * 100.0) if (px and ep) else None
        if ret is not None:
            realized += 2000.0 * (ret / 100.0)
        sealed.append({"id": p["id"], "ticker": tk, "exit": px, "ret": ret, "src": src})
        r = f"{ret:+.1f}%" if ret is not None else "  n/a"
        xp = f"${px:.2f}" if px else "  n/a"
        print(f"  {tk:6} -> exit {xp:>8}  {r:>8}  ({src})")

    print(f"\n  inception realized P/L on sealed positions: ${realized:,.0f}")

    if not execute:
        print("\nDRY RUN — no writes. Re-run with --execute to seal the inception cohort.")
        return

    print("\nWriting...")
    for s in sealed:
        sb.table("model_portfolio_positions").update({
            "is_active":   False,
            "exit_date":   today,
            "exit_price":  s["exit"],
            "exit_reason": "EPOCH_FREEZE",
            "epoch":       "inception",
        }).eq("id", s["id"]).execute()
    print(f"Done. Sealed {len(sealed)} positions. The inception cohort is now frozen at {today}.")
    print("Next: run seed_live_portfolio.py to start the live cohort.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="Write (default is a dry run)")
    main(execute=ap.parse_args().execute)
