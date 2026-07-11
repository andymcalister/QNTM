"""Backfill RSP daily closes (QQQ already done). Retries on yfinance rate-limit.
Run from Render qntm-api Shell (service key writes):  python3 backfill_rsp.py"""
import sys, time
from datetime import date

INCEPTION = "2026-06-22"

def fetch_rsp():
    import yfinance as yf
    for attempt in range(6):
        try:
            df = yf.download("RSP", start=INCEPTION, end=date.today().isoformat(),
                             auto_adjust=True, progress=False)
            if df is not None and not df.empty:
                return df
            print(f"  attempt {attempt+1}: empty result")
        except Exception as e:
            print(f"  attempt {attempt+1} failed: {str(e)[:80]}")
        wait = 20 * (attempt + 1)
        print(f"  waiting {wait}s before retry...")
        time.sleep(wait)
    return None

def main():
    from data_refresh import _get_supabase
    sb = _get_supabase()
    if not sb:
        print("no supabase"); sys.exit(1)

    df = fetch_rsp()
    if df is None or df.empty:
        print("RSP: no data after retries — wait a few minutes and re-run"); sys.exit(1)

    closes = df["Close"]
    try:
        series = closes["RSP"] if "RSP" in closes.columns else closes.iloc[:, 0]
    except Exception:
        series = closes

    ok = total = 0
    for idx, val in series.items():
        d = idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]
        if val is None:
            continue
        try:
            px = float(val)
        except Exception:
            continue
        total += 1
        try:
            sb.table("benchmark_price").update({"rsp_close": round(px, 4)}).eq("d", d).execute()
            ok += 1
        except Exception as e:
            print(f"  {d} failed: {str(e)[:60]}")
    print(f"RSP: wrote {ok}/{total}")

    r = sb.table("benchmark_price").select("d,close,rsp_close,qqq_close").order("d").execute().data
    rf = len([x for x in r if x.get("rsp_close") is not None])
    qf = len([x for x in r if x.get("qqq_close") is not None])
    print(f"VERIFY: total={len(r)} rsp_filled={rf} qqq_filled={qf}")
    # show a filled sample
    filled = [x for x in r if x.get("rsp_close") and x.get("qqq_close")]
    if filled:
        print("sample:", filled[-1])

if __name__ == "__main__":
    main()
