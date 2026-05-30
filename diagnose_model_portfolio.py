"""
Diagnose model_portfolio_positions table state.
Run from the QNTM directory: python3 diagnose_model_portfolio.py
"""
import os, sys

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = (
    os.getenv("SUPABASE_SERVICE_KEY")
    or os.getenv("SUPABASE_ANON_KEY")
    or os.getenv("SUPABASE_KEY")
    or ""
)

if not SUPABASE_URL or not SUPABASE_KEY:
    try:
        import toml
        s = toml.load('.streamlit/secrets.toml')
        if "default" in s and isinstance(s["default"], dict):
            s = s["default"]
        SUPABASE_URL = SUPABASE_URL or s.get("SUPABASE_URL", "")
        SUPABASE_KEY = (
            SUPABASE_KEY
            or s.get("SUPABASE_SERVICE_KEY")
            or s.get("SUPABASE_ANON_KEY")
            or s.get("SUPABASE_KEY")
            or ""
        )
    except Exception as e:
        print(f"Could not load secrets.toml: {e}")

print(f"URL loaded: {'yes' if SUPABASE_URL else 'no'}")
print(f"KEY loaded: {'yes' if SUPABASE_KEY else 'no'} (length={len(SUPABASE_KEY) if SUPABASE_KEY else 0})")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("\nERROR: secrets not loaded. Run this to inspect your secrets file:")
    print('  python3 -c "import toml; d=toml.load(\'.streamlit/secrets.toml\'); print(list(d.keys()))"')
    sys.exit(1)

from supabase import create_client
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

resp = sb.table("model_portfolio_positions") \
    .select("ticker,entry_date,entry_price,position_size,is_active") \
    .eq("is_active", True) \
    .order("entry_date") \
    .execute()

rows = resp.data or []
print(f"\nTotal active rows: {len(rows)}\n")

from collections import Counter
ticker_counts = Counter(r["ticker"] for r in rows)
dupes = {tk: n for tk, n in ticker_counts.items() if n > 1}
print(f"Unique tickers: {len(ticker_counts)}")
print(f"Tickers with duplicates: {len(dupes)}")
if dupes:
    for tk, n in sorted(dupes.items(), key=lambda x: -x[1]):
        print(f"  {tk}: {n} active rows")

sizes = Counter(r.get("position_size") for r in rows)
print(f"\nPosition sizes:")
for size, n in sorted(sizes.items(), key=lambda x: x[0] if x[0] else 0):
    print(f"  ${size}: {n} positions")

total = sum(float(r.get("position_size") or 0) for r in rows)
print(f"\nTotal cost basis: ${total:,.0f}")
print(f"Expected (50 x $2000): $100,000")
print(f"Excess: ${total - 100000:,.0f}")
