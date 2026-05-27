"""
Rebuild model portfolio from 2026-05-19 with correct regime-aware thresholds.
Run from your local QNTM directory:
  python rebuild_model_portfolio.py
"""
import os, sys
from datetime import date

# Load secrets from streamlit
try:
    import streamlit as st
    SUPABASE_URL = st.secrets.get("SUPABASE_URL", "") or os.getenv("SUPABASE_URL","")
    SUPABASE_KEY = st.secrets.get("SUPABASE_ANON_KEY", "") or os.getenv("SUPABASE_ANON_KEY","")
except:
    SUPABASE_URL = os.getenv("SUPABASE_URL","")
    SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY","")

if not SUPABASE_URL:
    try:
        import toml
        s = toml.load('.streamlit/secrets.toml')
        SUPABASE_URL = s.get("SUPABASE_URL","")
        SUPABASE_KEY = s.get("SUPABASE_ANON_KEY","")
    except:
        pass

if not SUPABASE_URL:
    print("ERROR: No SUPABASE_URL found. Set env vars or run from QNTM directory.")
    sys.exit(1)

from supabase import create_client
sb = create_client(SUPABASE_URL, SUPABASE_KEY)
print(f"Connected to Supabase")

TARGET   = 50
POS_SIZE = 2000.0
SECT_CAP = 15

try:
    from universe_data import SECTORS
except:
    SECTORS = {}
    print("Warning: could not load SECTORS — sector cap won't apply")

# ── Step 1: Clear existing portfolio ─────────────────────────────────────────
print("\nClearing existing portfolio...")
existing = sb.table("model_portfolio_positions").select("id").execute()
if existing.data:
    ids = [r["id"] for r in existing.data]
    # Delete in batches
    for i in range(0, len(ids), 100):
        batch = ids[i:i+100]
        sb.table("model_portfolio_positions").delete().in_("id", batch).execute()
    print(f"  Deleted {len(ids)} positions")
else:
    print("  Nothing to clear")

# ── Step 2: Get all signal dates from 2026-05-19 ─────────────────────────────
print("\nFetching signal dates from 2026-05-19...")
dates_resp = sb.table("signal_log") \
    .select("signal_date") \
    .gte("signal_date", "2026-05-19") \
    .order("signal_date", desc=False) \
    .execute()

dates = sorted(set(r["signal_date"] for r in (dates_resp.data or [])))
print(f"  Found {len(dates)} dates: {dates}")

active_tickers = set()
sector_counts  = {}
total_entered  = 0
total_exited   = 0

for sig_date in dates:
    print(f"\n--- {sig_date} ---")

    # Load scores
    resp = sb.table("signal_log") \
        .select("ticker,adj_composite,composite,price,momentum,quality,volume,value,sentiment") \
        .eq("signal_date", sig_date) \
        .execute()

    if not resp.data:
        print(f"  No data")
        continue

    scores = resp.data
    score_map = {r["ticker"]: r for r in scores}

    # Detect regime: compare adj_composite to composite
    # HIGH VOLATILITY = macro dampening heavily applied (avg ratio < 0.90)
    ratios = []
    for r in scores:
        adj  = float(r.get("adj_composite") or 0)
        comp = float(r.get("composite") or 0)
        if comp > 0 and adj > 0:
            ratios.append(adj / comp)
    avg_ratio = sum(ratios) / len(ratios) if ratios else 1.0
    is_high_vol = avg_ratio < 0.90
    entry_thresh = 67 if is_high_vol else 60
    exit_thresh  = 45

    regime_label = "HIGH VOLATILITY (67+)" if is_high_vol else "NORMAL (60+)"
    print(f"  Regime: {regime_label} | ratio={avg_ratio:.3f} | {len(scores)} tickers")

    # ── Exit collapsed positions ──────────────────────────────────────────────
    exited = []
    for tk in list(active_tickers):
        sc  = score_map.get(tk)
        if not sc: continue
        adj = float(sc.get("adj_composite") or 0)
        if adj < exit_thresh:
            active_tickers.discard(tk)
            sec = SECTORS.get(tk, "Unknown")
            sector_counts[sec] = max(0, sector_counts.get(sec, 1) - 1)
            exited.append(tk)
    if exited:
        print(f"  Exit: {exited}")
        total_exited += len(exited)

    # ── Fill open slots ───────────────────────────────────────────────────────
    slots = TARGET - len(active_tickers)
    if slots <= 0:
        print(f"  Full {len(active_tickers)}/{TARGET}")
        continue

    candidates = sorted(
        [r for r in scores
         if float(r.get("adj_composite") or 0) >= entry_thresh
         and r["ticker"] not in active_tickers
         and r.get("price")],
        key=lambda x: float(x.get("adj_composite") or 0),
        reverse=True
    )

    entered = []
    inserts = []
    for r in candidates:
        if len(entered) >= slots: break
        tk  = r["ticker"]
        sec = SECTORS.get(tk, "Unknown")
        if sector_counts.get(sec, 0) >= SECT_CAP: continue
        adj = float(r.get("adj_composite") or 0)
        inserts.append({
            "ticker":        tk,
            "entry_date":    sig_date,
            "entry_price":   r.get("price"),
            "entry_score":   round(adj, 1),
            "position_size": POS_SIZE,
            "is_active":     True,
        })
        sector_counts[sec] = sector_counts.get(sec, 0) + 1
        active_tickers.add(tk)
        entered.append(tk)

    if inserts:
        sb.table("model_portfolio_positions").insert(inserts).execute()
        total_entered += len(inserts)
        print(f"  Enter ({len(entered)}): {entered[:8]}{'...' if len(entered)>8 else ''}")

    print(f"  Portfolio: {len(active_tickers)}/{TARGET} | {slots - len(entered)} slots still open")

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'='*50}")
print(f"REBUILD COMPLETE")
print(f"  Entered total: {total_entered}")
print(f"  Exited total:  {total_exited}")
print(f"  Final active:  {len(active_tickers)}/{TARGET}")
print(f"  Active tickers: {sorted(active_tickers)}")

# Show sector breakdown
sec_breakdown = {}
for tk in active_tickers:
    sec = SECTORS.get(tk, "Unknown")
    sec_breakdown[sec] = sec_breakdown.get(sec, 0) + 1
print(f"\nSector breakdown:")
for sec, cnt in sorted(sec_breakdown.items(), key=lambda x: x[1], reverse=True):
    print(f"  {sec}: {cnt}")
