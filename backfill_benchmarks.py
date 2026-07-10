"""Backfill RSP + QQQ daily closes into benchmark_price for every trading day
from model-portfolio inception (2026-06-22) to today, matching the stored SPY
series. Run ONCE from ~/qntm after adding the columns (see SQL):
    python3 backfill_benchmarks.py
Re-runnable (upserts). Requires SUPABASE_SERVICE_KEY."""
import sys
from datetime import date

INCEPTION = "2026-06-22"

def main():
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance needed"); sys.exit(1)
    from data_refresh import _get_supabase
    sb = _get_supabase()
    if not sb:
        print("no supabase"); sys.exit(1)

    today = date.today().isoformat()
    print(f"fetching RSP + QQQ from {INCEPTION} to {today}...")

    for ticker, col in [("RSP", "rsp_close"), ("QQQ", "qqq_close")]:
        df = yf.download(ticker, start=INCEPTION, end=today, auto_adjust=True, progress=False)
        if df is None or df.empty:
            print(f"  {ticker}: no data"); continue
        closes = df["Close"]
        # handle multi/single column frame
        try:
            series = closes[ticker] if ticker in closes.columns else closes.iloc[:, 0]
        except Exception:
            series = closes
        rows = []
        for idx, val in series.items():
            d = idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]
            if val is None:
                continue
            try:
                px = float(val)
            except Exception:
                continue
            rows.append({"d": d, col: round(px, 4)})
        print(f"  {ticker}: {len(rows)} days")
        # UPDATE each row (benchmark_price.close is NOT NULL; can't upsert partial)
        ok = 0
        for r in rows:
            d = r["d"]
            try:
                upd = sb.table("benchmark_price").update({col: r[col]}).eq("d", d).execute()
                if upd.data:
                    ok += 1
                else:
                    # no SPY row for that date (e.g. RSP/QQQ traded but our SPY row missing) — skip
                    pass
            except Exception as e:
                print(f"    {d} failed: {e}")
        print(f"  {ticker}: updated {ok}/{len(rows)} existing benchmark rows")

    print("done.")

if __name__ == "__main__":
    main()
