"""
QuantEdge — Conviction Model Engine
Buy-and-hold conviction strategy with hidden gem detection.
Connects to live data via yfinance (free tier).
"""

import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta
import json

# ── UNIVERSE DATA — S&P 500 + Russell 1000 (~846 tickers) ───────────────────
from universe_data import SECTORS, FUNDAMENTALS
try:
    # Small-cap names (top of Russell 2000) explicitly added as gem material.
    from universe_data import SMALL_MID_POOL
except Exception:
    SMALL_MID_POOL = set()   # older universe_data.py with no gem layer


# ── SCORING ENGINE ────────────────────────────────────────────────────────────
# Pillar weights — v2.0 (optimized from walk-forward backtest analysis)
# Changes from v1.0:
#   Quality:  25% → 30% (stickiest quarterly predictor)
#   Value:    15% → 20% (fundamental anchor, low noise)
#   Volume:   20% → 10% (daily signal, stale on quarterly rebalance)
#   Momentum: 30% → 30% (unchanged — top predictor)
#   Sentiment:10% → 10% (unchanged)
PILLAR_W = {"momentum":0.30,"quality":0.30,"volume":0.10,"value":0.20,"sentiment":0.10}

# Momentum lookback weights — v2.0
# Favor 3M and 6M (trend confirmation) over 1M (noise)
MOM_W = {"m1m":0.10,"m3m":0.30,"m6m":0.35,"trend":0.15,"pfh":0.10}

ENTRY_THRESHOLD      = 60
EXIT_THRESHOLD       = 45
MOM_EXIT             = 30
MIN_POSITIONS        = 15   # floor: always hold at least this many positions
DYNAMIC_THRESHOLD_HI = 65   # raise bar when >30 stocks score ≥60 (signal dilution)

# ── Model-portfolio epoch ───────────────────────────────────────────────────
# The track record is partitioned into epochs via the model_portfolio_positions
# .epoch column. The cron and the public Track Record page operate only on
# MODEL_EPOCH, so the live record runs forward from MODEL_INCEPTION. Earlier
# cohorts (e.g. 'inception') stay in the table, sealed and dated, as an internal
# point-in-time reference — never deleted, just not shown live. To roll a new
# epoch later, freeze the current one and bump these two constants together.
MODEL_EPOCH     = "live"
MODEL_INCEPTION = "2026-06-22"

def pf(v, lo, hi):
    if v is None: return 50.0
    try: return max(0.0, min(100.0, (float(v)-lo)/(hi-lo)*100))
    except: return 50.0

def _score_volume_real(vol_ratio: float, price_history: list) -> float:
    """
    Real volume pillar (replaces the math proxy).
    Uses relative volume + OBV direction + price-volume divergence check.
    Returns 0-100.
    """
    scores = []

    # 1. Relative volume (40% weight)
    if vol_ratio is not None:
        if   vol_ratio >= 2.0:  rv = 90
        elif vol_ratio >= 1.5:  rv = 75
        elif vol_ratio >= 1.0:  rv = 55
        elif vol_ratio >= 0.5:  rv = 40
        else:                    rv = 20
        scores.append((rv, 0.4))

    # 2. OBV direction via up-day ratio (40% weight)
    if price_history and len(price_history) >= 10:
        recent   = price_history[-20:]
        up_days  = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i-1])
        obv_pct  = up_days / (len(recent) - 1) * 100 if len(recent) > 1 else 50
        scores.append((obv_pct, 0.4))

        # 3. Price-volume confirmation / divergence (20% weight)
        price_up = price_history[-1] > price_history[-10]
        if price_up and vol_ratio is not None and vol_ratio >= 1.0:
            div = 70   # confirmed uptrend
        elif price_up and vol_ratio is not None and vol_ratio < 0.7:
            div = 35   # divergence — weak hands
        elif not price_up and vol_ratio is not None and vol_ratio >= 1.5:
            div = 30   # distribution
        else:
            div = 50
        scores.append((div, 0.2))

    if not scores:
        return 50.0

    total_w  = sum(w for _, w in scores)
    weighted = sum(s * w for s, w in scores) / total_w
    return round(max(0.0, min(100.0, weighted)), 1)


def score_stock(ticker: str, price_history: list = None,
                live_fundamentals: dict = None, vol_ratio: float = None) -> dict:
    """
    Score a stock using available data.

    Args:
        ticker:            Stock ticker symbol
        price_history:     List of closing prices (oldest → newest)
        live_fundamentals: Fresh fundamentals dict from data_refresh (overrides static)
        vol_ratio:         Current volume / 30-day avg volume (from data_refresh)
    """
    # Merge: live fundamentals take precedence over static universe data
    static_f = FUNDAMENTALS.get(ticker, {})
    f = {**static_f, **(live_fundamentals or {})}

    # Momentum from price history — weighted toward 3M/6M trend confirmation
    if price_history and len(price_history) >= 5:
        hist = price_history
        cur  = hist[-1]
        m1m  = (cur/hist[max(0,len(hist)-22)] -1)*100  if len(hist)>=22  else 0
        m3m  = (cur/hist[max(0,len(hist)-66)] -1)*100  if len(hist)>=66  else m1m
        m6m  = (cur/hist[max(0,len(hist)-126)]-1)*100  if len(hist)>=126 else m3m
        rets = [(hist[i]/hist[i-1]-1) for i in range(1,len(hist))]
        trend = sum(1 for r in rets[-20:] if r>0)/max(len(rets[-20:]),1)*100
        ph    = max(hist[-min(252,len(hist)):])
        pfh   = (cur/ph-1)*100
        mom = (pf(m1m,-20,30)*MOM_W["m1m"] + pf(m3m,-30,60)*MOM_W["m3m"] +
               pf(m6m,-40,80)*MOM_W["m6m"] + trend*MOM_W["trend"] +
               pf(pfh,-30,0)*MOM_W["pfh"])
    else:
        # Estimate from fundamentals if no price history
        eg  = f.get("eg",0) or 0
        rg  = f.get("rg",0) or 0
        mom = np.mean([pf(eg,-30,60), pf(rg,-20,40), 50])

    # Quality
    qa = [pf(f.get("roe"),-20,80), pf(f.get("pm"),-10,50),
          pf(f.get("rg"),-20,50),  pf(f.get("fcf"),-2,8),
          f.get("br",50) or 50]
    quality = np.mean(qa)

    # Volume — real score if vol_ratio available, otherwise price-momentum proxy
    if vol_ratio is not None:
        # Real volume pillar: relative volume + OBV direction from price history
        volume = _score_volume_real(vol_ratio, price_history or [])
    else:
        # Legacy proxy (used when no live data available)
        volume = max(0, min(100, 50 + (mom-50)*0.6))

    # Value
    fpe = f.get("fpe")
    va  = []
    if fpe and fpe>0: va.append(pf(-fpe,-80,-8))
    fcf = f.get("fcf")
    if fcf: va.append(pf(fcf,-2,8))
    value = np.mean(va) if va else 50

    # Sentiment
    sp = f.get("sp",5) or 5
    ib = f.get("ib",40) or 40
    sentiment = np.mean([pf(-sp,-15,-0.3), ib])

    composite = (mom*PILLAR_W["momentum"] + quality*PILLAR_W["quality"] +
                 volume*PILLAR_W["volume"] + value*PILLAR_W["value"] +
                 sentiment*PILLAR_W["sentiment"])

    # Public conviction label — HIGH / MODERATE / LOW only.
    # (Was STRONG ALIGN / HIGH ALIGN / LOW ALIGN / WEAK/NEG — non-compliant
    #  vocabulary that leaked into the DB. Normalized to the published bands.)
    from conviction import conviction_label
    sig = conviction_label(composite)

    return {
        "ticker":ticker, "sector":SECTORS.get(ticker,"Unknown"),
        "composite":round(composite,1), "momentum":round(mom,1),
        "quality":round(quality,1),     "volume":round(volume,1),
        "value":round(value,1),          "sentiment":round(sentiment,1),
        "signal":sig,
        "price": f.get("price"),
        # Market-cap bucket ('large'/'mid'/'small'/None) surfaced from the merged
        # fundamentals so it can be persisted to signal_log and reach the
        # render-time hidden-gem size filter. None when neither live nor static
        # fundamentals carried a cap for this ticker.
        "mktcap": f.get("mktcap"),
        # `action` is an INTERNAL enum (BUY/SELL/HOLD) consumed by
        # apply_macro_overlay / portfolio logic — never shown to users, always
        # converted to HIGH/MODERATE/LOW at display time. Do not surface raw.
        "action": ("BUY" if composite>=ENTRY_THRESHOLD
                   else "SELL" if composite<EXIT_THRESHOLD or mom<MOM_EXIT
                   else "HOLD"),
    }


# ── QNTM VALUATION RANGE  (a.k.a. "Value Position") ───────────────────────────
# DESCRIPTIVE valuation context — explicitly NOT a price target, forecast, or
# expected return. It states where today's price sits relative to a peer-relative
# valuation band derived from QNTM's own data. Anchor = sector-median forward
# earnings multiple, tilted up for quality/momentum so a deserved-premium name is
# not flagged "expensive" purely for trading above its sector. Width = the name's
# own realized volatility, floored/capped, then clamped inside an extended
# 52-week envelope. `val_basis` records how each band was derived, for disclosure.
#
# Tunable knobs (kept here so the methodology is one place, not buried):
VR_VOL_FLOOR     = 0.08   # min half-band (±8%) even for placid names
VR_VOL_CAP       = 0.35   # max half-band (±35%) for very volatile names
VR_VOL_HORIZON   = 0.50   # scales annualized sigma toward a ~quarterly expected move
VR_QUALITY_TILT  = 0.20   # how much quality (0-100) lifts/cuts the fair multiple
VR_MOMENTUM_TILT = 0.10   # how much momentum (0-100) lifts/cuts the fair multiple
VR_PREM_MIN      = 0.70   # premium factor floor
VR_PREM_MAX      = 1.40   # premium factor cap
VR_ENV_LOW       = 0.60   # low bound never below 0.60 x 52-week low
VR_ENV_HIGH      = 1.50   # high bound never above 1.50 x 52-week high


def _realized_sigma(price_history: list):
    """Annualized realized volatility from daily closes. None if too little data."""
    if not price_history or len(price_history) < 20:
        return None
    rets = [(price_history[i] / price_history[i-1] - 1)
            for i in range(1, len(price_history))
            if price_history[i-1]]
    if len(rets) < 15:
        return None
    import statistics
    window = rets[-126:] if len(rets) >= 126 else rets
    return statistics.pstdev(window) * (252 ** 0.5)


def sector_fair_multiples(rows: list) -> dict:
    """
    Median forward P/E per sector across names with a sane positive fpe.
    Expects each row to carry `_fpe` (raw forward P/E) and `sector`.
    """
    import statistics
    buckets = {}
    for r in rows:
        sec = r.get("sector", "Unknown")
        try:
            fpe = float(r.get("_fpe"))
        except (TypeError, ValueError):
            continue
        if 0 < fpe <= 200:            # drop negative-earnings / nonsense multiples
            buckets.setdefault(sec, []).append(fpe)
    return {sec: statistics.median(v) for sec, v in buckets.items() if v}


def compute_valuation_band(price, fpe, sector_fair_fpe, quality, momentum,
                           price_history=None, w52_hi=None, w52_lo=None) -> dict:
    """
    Returns {val_low, val_high, value_position, val_basis}.
      val_basis = 'valuation'  peer-relative forward-earnings band
                  'technical'  vol band around recent avg price (no usable fpe)
                  'na'         insufficient data
    All outputs are descriptive valuation context, never a forecast.
    """
    out = {"val_low": None, "val_high": None, "value_position": None, "val_basis": "na"}
    try:
        price = float(price)
    except (TypeError, ValueError):
        return out
    if not price or price <= 0:
        return out

    # ---- half-band width from realized volatility ----
    sigma = _realized_sigma(price_history or [])
    if sigma is not None:
        half = min(VR_VOL_CAP, max(VR_VOL_FLOOR, sigma * VR_VOL_HORIZON))
    else:
        half = VR_VOL_FLOOR * 1.5    # no history → modest default band

    # ---- anchor ----
    try:
        fpe_f = float(fpe)
    except (TypeError, ValueError):
        fpe_f = None

    if fpe_f and fpe_f > 0 and sector_fair_fpe and sector_fair_fpe > 0:
        q = (float(quality or 50) - 50.0) / 50.0       # -1..+1
        m = (float(momentum or 50) - 50.0) / 50.0
        prem = 1.0 + VR_QUALITY_TILT * q + VR_MOMENTUM_TILT * m
        prem = max(VR_PREM_MIN, min(VR_PREM_MAX, prem))
        anchor = price * ((sector_fair_fpe * prem) / fpe_f)
        basis  = "valuation"
    elif price_history and len(price_history) >= 20:
        recent = price_history[-min(126, len(price_history)):]
        anchor = sum(recent) / len(recent)
        basis  = "technical"
    else:
        return out

    low  = anchor * (1 - half)
    high = anchor * (1 + half)

    # ---- sanity envelope around the 52-week range ----
    lo52 = hi52 = None
    try:
        if w52_lo is not None: lo52 = float(w52_lo)
        if w52_hi is not None: hi52 = float(w52_hi)
    except (TypeError, ValueError):
        lo52 = hi52 = None
    if (lo52 is None or hi52 is None) and price_history:
        p52  = price_history[-min(252, len(price_history)):]
        lo52 = min(p52); hi52 = max(p52)
    if lo52 and hi52 and hi52 >= lo52 > 0:
        # Clamp the ANCHOR (not the bounds) into the extended envelope, then
        # rebuild — clamping the bounds independently can invert the band when
        # the valuation anchor sits far outside the 52-week range.
        anchor = max(VR_ENV_LOW * lo52, min(VR_ENV_HIGH * hi52, anchor))
        low  = anchor * (1 - half)
        high = anchor * (1 + half)

    if high <= low:
        return out

    pos = max(0.0, min(1.0, (price - low) / (high - low))) * 100.0
    out.update({"val_low": round(low, 2), "val_high": round(high, 2),
                "value_position": round(pos, 1), "val_basis": basis})
    return out


# ── HIDDEN GEM DETECTION ──────────────────────────────────────────────────────
def detect_hidden_gems(scores: list, macro_data: dict = None) -> list:
    """
    Hidden gems: stocks scoring well that are under-owned / under-followed.

    v2.0 changes:
    - Filters on adj_composite (macro-adjusted) not raw composite
    - Uses live fundamentals from score dict if available, falls back to static
    - Tightens threshold in RISK_OFF regime (only highest conviction surfaces)
    - Macro regime context shown in gem reasons

    Criteria:
    1. adj_composite >= threshold (62 standard, 67 in RISK_OFF/HIGH VOLATILITY)
    2. Quality >= 55, Momentum >= 58
    3. Not a mega-cap (less analyst coverage = more alpha opportunity)
    4. At least one fundamental reason (revenue, earnings, insider, short interest)
    """
    regime = (macro_data or {}).get("regime", "NEUTRAL") if macro_data else "NEUTRAL"

    # Gems are a high bar always; tighten further in risk-off so only the
    # highest-conviction names surface. (Previously this LOOSENED in risk-on,
    # which inflated the list exactly when macro dampening eased — backwards for
    # a curated 'hidden gems' shortlist.)
    if regime in ("RISK_OFF", "HIGH VOLATILITY"):
        threshold_composite = 67
        threshold_quality   = 58
        threshold_momentum  = 62
    else:
        threshold_composite = 62
        threshold_quality   = 55
        threshold_momentum  = 58

    # Mega-caps excluded — gems are stocks flying under the radar
    mega_caps = {
        "NVDA","MSFT","AAPL","META","GOOGL","GOOG","AMZN","TSLA","NFLX",
        "JPM","V","MA","UNH","JNJ","ABBV","PG","KO","WMT","COST",
        "XOM","CVX","BAC","GS","MS","BLK","LLY","MRK","TMO","HD","LOW"
    }

    gems = []
    for s in scores:
        tk = s["ticker"]
        if tk in mega_caps:
            continue

        # Defensive float conversion — values from Supabase cache can be strings
        try:
            adj = float(s.get("adj_composite") or s.get("composite") or 0)
            mom = float(s.get("momentum") or 0)
            qua = float(s.get("quality")  or 0)
        except (TypeError, ValueError):
            continue

        if adj < threshold_composite: continue
        if qua < threshold_quality:   continue
        if mom < threshold_momentum:  continue

        # Use live fundamentals from score dict if available, else static
        live_f   = s.get("live_fundamentals") or {}
        static_f = FUNDAMENTALS.get(tk, {})
        f = {**static_f, **live_f}

        # Real size gate — hidden gems are under-followed mid/small caps, not
        # large-caps. Market cap rides on the score row (signal_log.mktcap, set by
        # the nightly run) with `f` as the in-process fallback. FAIL-CLOSED:
        #   • explicit 'large'           → never a gem
        #   • explicit 'mid'/'small'     → eligible
        #   • unknown/None cap           → eligible ONLY if the ticker is in
        #     SMALL_MID_POOL (a name we KNOW is small-cap from Russell 2000
        #     membership), so a genuine small-cap isn't lost to a yfinance gap.
        mktcap = s.get("mktcap") or f.get("mktcap")
        if mktcap == "large":
            continue
        if mktcap not in ("mid", "small") and tk not in SMALL_MID_POOL:
            continue

        reasons = []

        try:
            rg = f.get("rg")
            if rg and rg > 20:
                reasons.append(f"Revenue growing {rg:.0f}% YoY")
            elif rg and rg > 10:
                reasons.append(f"Revenue +{rg:.0f}% YoY")

            # Earnings growth
            eg = f.get("eg")
            if eg and eg > 40:
                reasons.append(f"Earnings accelerating {eg:.0f}% YoY")
            elif eg and eg > 20:
                reasons.append(f"Earnings +{eg:.0f}% YoY")

            # Insider buying
            ib = f.get("ib")
            if ib and ib > 50:
                reasons.append(f"Strong insider buying ({ib:.0f}% buy ratio)")
            elif ib and ib > 35:
                reasons.append(f"Insider buying elevated ({ib:.0f}%)")

            # Low short interest
            sp = f.get("sp")
            if sp is not None and sp < 3:
                reasons.append(f"Low short interest ({sp:.1f}%)")
            elif sp is not None and sp < 5:
                reasons.append(f"Modest short interest ({sp:.1f}%)")

            # Beat rate
            br = f.get("br")
            if br and br == 100:
                reasons.append("Beat estimates all 4 quarters")
            elif br and br >= 75:
                reasons.append(f"Beat estimates {br:.0f}% of quarters")

            # FCF yield
            fcf = f.get("fcf")
            if fcf and fcf > 5:
                reasons.append(f"Strong FCF yield ({fcf:.1f}%)")

            # Pillar-based reasons (when fundamentals are thin)
            if len(reasons) < 2:
                if mom >= 70:
                    reasons.append(f"Strong price momentum (score {mom:.0f})")
                if qua >= 70:
                    reasons.append(f"High quality fundamentals (score {qua:.0f})")
                vol = float(s.get("volume") or 0)
                if vol >= 65:
                    reasons.append(f"Elevated institutional volume (score {vol:.0f})")

                # Macro context
                if regime == "RISK_OFF":
                    reasons.append("Surfaced in RISK-OFF screen — high-conviction filter applied")
                elif regime == "RISK_ON":
                    reasons.append("Strong signal in risk-on environment")

        except Exception:
            pass  # skip this stock if any field causes an error

        if not reasons:
            continue

        s["is_hidden_gem"] = True
        s["gem_reasons"]   = reasons[:4]
        s["gem_regime"]    = regime
        s["gem_adj_score"] = adj
        gems.append(s)

    # Sort by adj_composite descending, then cap — 'hidden gems' is a curated
    # shortlist, not a screen. Keeping it tight preserves the signal value.
    gems.sort(key=lambda x: float(x.get("adj_composite") or x.get("composite") or 0), reverse=True)
    return gems[:12]


# ── LIVE PRICE FETCH ──────────────────────────────────────────────────────────
def fetch_price_data(tickers: list, period: str = "1y") -> dict:
    """Fetch price history. Returns {ticker: [prices]} or demo data if blocked."""
    try:
        import yfinance as yf
        result = {}
        for tk in tickers:
            try:
                hist = yf.Ticker(tk).history(period=period)
                if not hist.empty:
                    result[tk] = hist["Close"].tolist()
            except:
                pass
        return result
    except:
        return {}


def get_current_price(ticker: str) -> float:
    """Get current price or estimate from fundamentals."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        return info.get("currentPrice") or info.get("regularMarketPrice") or 0
    except:
        return 0


# ── FULL UNIVERSE SCAN ────────────────────────────────────────────────────────
def run_full_scan(use_live_prices: bool = True) -> list:
    """
    Score all stocks in universe. Returns sorted list.

    Priority order:
      1. Today's pre-computed scores from Supabase signal_log (fastest, most accurate)
      2. Live fundamentals from Supabase fundamentals_cache + yfinance price histories
      3. Static fundamentals from universe_data.py (fallback, no external calls)
    """
    tickers = list(SECTORS.keys())

    # ── Try Supabase cached scores first ────────────────────────────────────
    try:
        from data_refresh import load_cached_scores, load_cached_fundamentals, cache_is_fresh
        if cache_is_fresh():
            cached = load_cached_scores()
            if cached and len(cached) >= len(tickers) * 0.5:
                # Cache has at least 50% of universe — good enough to use
                # Fill in sector from SECTORS map (signal_log doesn't store it)
                for s in cached:
                    s.setdefault("sector", SECTORS.get(s["ticker"], "Unknown"))
                # Add any tickers not in cache using static scoring
                cached_tickers = {s["ticker"] for s in cached}
                for tk in tickers:
                    if tk not in cached_tickers:
                        s = score_stock(tk)
                        s["has_live_price"] = False
                        s["pct_rank"] = 50.0
                        cached.append(s)
                cached.sort(key=lambda x: x.get("adj_composite", x["composite"]), reverse=True)
                return cached
    except ImportError:
        pass  # data_refresh not available yet
    except Exception:
        pass  # cache unavailable — fall through

    # ── Load live fundamentals from cache if available ───────────────────────
    live_fundamentals = {}
    try:
        from data_refresh import load_cached_fundamentals
        live_fundamentals = load_cached_fundamentals()
    except Exception:
        pass

    # ── Fetch price histories (rate-limited) ─────────────────────────────────
    prices = fetch_price_data(tickers) if use_live_prices else {}

    # ── Score each ticker ────────────────────────────────────────────────────
    scores = []
    for tk in tickers:
        hist     = prices.get(tk, [])
        live_f   = live_fundamentals.get(tk, {})
        vol_ratio = live_f.get("vol_ratio")
        s        = score_stock(tk, hist, live_fundamentals=live_f, vol_ratio=vol_ratio)
        s["has_live_price"] = len(hist) > 0
        scores.append(s)

    # Cross-sectional percentile ranking
    composites = [s["composite"] for s in scores]
    for s in scores:
        rank = sum(1 for c in composites if c <= s["composite"]) / len(composites) * 100
        s["pct_rank"] = round(rank, 1)

    scores.sort(key=lambda x: x["composite"], reverse=True)
    return scores


# ── MACRO & SENTIMENT OVERLAY ────────────────────────────────────────────────
# Event-based sector adjustment layer. Blends RSS news + keyword detection
# with quant factor scores. 75% quant / 25% macro overlay.
# In demo mode (no live feeds): uses estimated current regime from BACKTEST_DATA.

SECTOR_EVENT_MAP = {
    "tariff_broad":    {"Technology":-0.4,"Consumer Discretionary":-0.6,"Industrials":-0.5,
                        "Materials":-0.4,"Energy":0.0,"Financials":-0.3,"Healthcare":-0.1,
                        "Consumer Staples":-0.3,"Comm Services":-0.2,"Real Estate":-0.1,"Utilities":0.0},
    "tariff_relief":   {"Technology":+0.5,"Consumer Discretionary":+0.4,"Industrials":+0.4,
                        "Materials":+0.3,"Energy":0.0,"Financials":+0.2,"Healthcare":+0.1,
                        "Consumer Staples":+0.2,"Comm Services":+0.2,"Real Estate":+0.1,"Utilities":0.0},
    "fed_hawkish":     {"Technology":-0.5,"Consumer Discretionary":-0.4,"Industrials":-0.2,
                        "Materials":-0.2,"Energy":+0.1,"Financials":+0.3,"Healthcare":-0.1,
                        "Consumer Staples":-0.1,"Comm Services":-0.3,"Real Estate":-0.6,"Utilities":-0.5},
    "fed_dovish":      {"Technology":+0.5,"Consumer Discretionary":+0.4,"Industrials":+0.3,
                        "Materials":+0.2,"Energy":+0.1,"Financials":-0.2,"Healthcare":+0.2,
                        "Consumer Staples":+0.1,"Comm Services":+0.3,"Real Estate":+0.6,"Utilities":+0.5},
    "recession_signal":{"Technology":-0.4,"Consumer Discretionary":-0.6,"Industrials":-0.5,
                        "Materials":-0.4,"Energy":-0.3,"Financials":-0.5,"Healthcare":+0.2,
                        "Consumer Staples":+0.3,"Comm Services":-0.3,"Real Estate":-0.4,"Utilities":+0.2},
    "war_escalation":  {"Technology":-0.3,"Consumer Discretionary":-0.4,"Industrials":-0.2,
                        "Materials":+0.3,"Energy":+0.5,"Financials":-0.3,"Healthcare":+0.1,
                        "Consumer Staples":+0.2,"Comm Services":-0.2,"Real Estate":-0.2,"Utilities":+0.1},
    "war_deescalation":{"Technology":+0.3,"Consumer Discretionary":+0.4,"Industrials":+0.2,
                        "Materials":-0.3,"Energy":-0.5,"Financials":+0.3,"Healthcare":-0.1,
                        "Consumer Staples":-0.2,"Comm Services":+0.2,"Real Estate":+0.2,"Utilities":-0.1},
    "chip_export_ban": {"Technology":-0.7,"Consumer Discretionary":-0.1,"Industrials":-0.1,
                        "Materials":0.0,"Energy":0.0,"Financials":-0.1,"Healthcare":0.0,
                        "Consumer Staples":0.0,"Comm Services":-0.2,"Real Estate":0.0,"Utilities":0.0},
    "oil_spike":       {"Technology":-0.3,"Consumer Discretionary":-0.4,"Industrials":-0.3,
                        "Materials":+0.2,"Energy":+0.7,"Financials":-0.1,"Healthcare":-0.1,
                        "Consumer Staples":-0.2,"Comm Services":-0.2,"Real Estate":-0.1,"Utilities":+0.1},
    "fed_cut_expected":{"Technology":+0.5,"Consumer Discretionary":+0.4,"Industrials":+0.3,
                        "Materials":+0.2,"Energy":+0.1,"Financials":-0.2,"Healthcare":+0.2,
                        "Consumer Staples":+0.1,"Comm Services":+0.3,"Real Estate":+0.6,"Utilities":+0.5},
    "fed_hike_expected":{"Technology":-0.5,"Consumer Discretionary":-0.4,"Industrials":-0.2,
                        "Materials":-0.2,"Energy":+0.1,"Financials":+0.3,"Healthcare":-0.1,
                        "Consumer Staples":-0.1,"Comm Services":-0.3,"Real Estate":-0.6,"Utilities":-0.5},
    "fed_hold_expected":{"Technology":0.0,"Consumer Discretionary":0.0,"Industrials":0.0,
                        "Materials":0.0,"Energy":0.0,"Financials":0.0,"Healthcare":0.0,
                        "Consumer Staples":0.0,"Comm Services":0.0,"Real Estate":0.0,"Utilities":0.0},
    "inflation_cool":  {"Technology":+0.4,"Consumer Discretionary":+0.4,"Industrials":+0.3,
                        "Materials":+0.1,"Energy":-0.1,"Financials":-0.1,"Healthcare":+0.2,
                        "Consumer Staples":+0.1,"Comm Services":+0.3,"Real Estate":+0.5,"Utilities":+0.4},
    "inflation_hot":   {"Technology":-0.5,"Consumer Discretionary":-0.4,"Industrials":-0.2,
                        "Materials":+0.3,"Energy":+0.3,"Financials":+0.2,"Healthcare":-0.1,
                        "Consumer Staples":-0.1,"Comm Services":-0.3,"Real Estate":-0.5,"Utilities":-0.3},
    "jobs_weak":       {"Technology":-0.3,"Consumer Discretionary":-0.5,"Industrials":-0.4,
                        "Materials":-0.3,"Energy":-0.2,"Financials":-0.4,"Healthcare":+0.2,
                        "Consumer Staples":+0.3,"Comm Services":-0.2,"Real Estate":-0.2,"Utilities":+0.2},
    "jobs_strong":     {"Technology":+0.2,"Consumer Discretionary":+0.3,"Industrials":+0.3,
                        "Materials":+0.2,"Energy":+0.1,"Financials":+0.3,"Healthcare":0.0,
                        "Consumer Staples":-0.1,"Comm Services":+0.1,"Real Estate":+0.1,"Utilities":-0.1},
}

EVENT_KEYWORDS = {
    "tariff_broad":    ["tariff","import tax","trade war","reciprocal tariff"],
    "tariff_relief":   ["tariff pause","trade deal","tariff exemption","tariff suspended"],
    "fed_hawkish":     ["rate hike","hawkish fed","inflation concern","higher for longer"],
    "fed_dovish":      ["rate cut","fed cuts","dovish","fed pivot","rate reduction"],
    "recession_signal":["recession","gdp contraction","economic slowdown","yield curve invert"],
    "war_escalation":  ["airstrike","air strike","missile strike","missile attack",
                        "military strike","drone strike","shelling","bombard","invasion",
                        "invade","ground offensive","armed conflict","conflict escalates",
                        "launches strikes","strikes on","war erupts","nuclear strike",
                        "retaliatory strike","new strikes","fresh strikes","resume strikes",
                        "renewed fighting","opened fire","close the strait","closes the strait",
                        "close hormuz","closes hormuz","block the strait","mine the strait",
                        "seize ship","seizes ship","attack tanker","attacks tanker"],
    "war_deescalation":["ceasefire","cease-fire","peace deal","peace agreement",
                        "peace talks","peace accord","truce","war ends","ends war",
                        "de-escalation","de-escalate","hostilities end","withdraw troops",
                        "deal to end","deal signed","sign the deal","deal to be signed",
                        "deal set to be signed","reopen","blockade lifted","lift the blockade",
                        "lifting the blockade","memorandum","cessation of hostilities",
                        "end the war","ends the war","end the conflict","negotiat"],
    "chip_export_ban": ["chip export","semiconductor ban","nvidia export","export control semiconductor"],
    "oil_spike":       ["oil spike","crude surge","opec cut","oil price jump","brent surge"],
}

# ── Forward-looking expectations (Tier-1 headline proxy) ─────────────────────
# Markets price expectations, so the overlay reads what's being *reported to
# come*, not just what already broke. This is a HEADLINE PROXY for consensus —
# the credible version reads CME FedWatch (rate-move probabilities) + an
# economic calendar (consensus vs actual). Kept behind one function so a data
# feed can replace it without touching the regime logic.
ANTICIPATION_CUES = ["expected to","expectation","forecast","economists expect",
    "economists forecast","analysts expect","likely to","ahead of","odds of",
    "priced in","pricing in","bets on","betting on","anticipat","projected",
    "poised to","set to","consensus","fedwatch","fed watch","traders expect",
    "markets expect","probability of","odds favor","odds favour","seen cutting",
    "seen raising","seen holding"]

_FED_CONTEXT = ["fed","fomc","powell","interest rate","rate decision","central bank"]
_DIR_CUT  = ["rate cut","cut rates","cutting rates","lower rates","rate reduction",
             "reduce rates","ease rates","easing cycle","cuts rates","dovish"]
_DIR_HIKE = ["rate hike","hike rates","raise rates","raising rates","higher for longer",
             "tighten","tightening","hikes rates","another hike","hawkish"]
_DIR_HOLD = ["hold rates","rates steady","keep rates","rates unchanged","pause",
             "stand pat","no change","leave rates","on hold","steady rates",
             "hold steady"]

_JOBS_CTX    = ["payroll","jobs report","jobless claims","unemployment","nonfarm",
                "labor market","employment report","hiring"]
_JOBS_WEAK   = ["layoff","job cuts","jobless claims rose","jobless claims jump",
                "rising unemployment","unemployment rose","unemployment climbed",
                "payrolls miss","weak jobs","jobs miss","hiring slow","labor market cool",
                "jobs disappoint","fewer jobs"]
_JOBS_STRONG = ["payrolls beat","strong jobs","jobs beat","robust hiring","hiring surge",
                "unemployment fell","blowout jobs","jobs surge","jobs surprise","hot jobs"]

_INFL_HOT  = ["inflation rose","inflation accelerat","hot inflation","cpi rose",
              "cpi jump","prices rose","inflation higher","sticky inflation",
              "inflation surprise","reinflation","inflation heats","inflation pick"]
_INFL_COOL = ["inflation cool","inflation eas","disinflation","cpi fell","cpi eas",
              "prices fell","inflation slow","softer inflation","inflation lower",
              "cooling inflation","inflation fell","inflation retreat"]


def _detect_anticipation(headlines):
    """Forward-looking expectations from the balance of reporting. Returns
    (scores, meta): scores merge into event_scores and flow through the regime
    math like any other event; meta carries the Fed consensus split for the
    narrative. Headline proxy — swap for CME FedWatch + economic-calendar data
    later behind this same call without touching anything downstream."""
    scores, meta = {}, {}

    # ── Fed rate path: tally forward-looking calls, take the majority ────────
    cut = hold = hike = 0
    for h in headlines:
        if not any(c in h for c in ANTICIPATION_CUES):
            continue
        if not any(f in h for f in _FED_CONTEXT):
            continue
        if   any(d in h for d in _DIR_HOLD): hold += 1
        elif any(d in h for d in _DIR_CUT):  cut  += 1
        elif any(d in h for d in _DIR_HIKE): hike += 1
    total = cut + hold + hike
    # Require a real cluster of forward-looking calls — a 2-headline "consensus"
    # is noise, not signal. Weight then reflects BOTH how lopsided the split is
    # AND how many calls support it (conviction), so a thin read can never reach
    # max dampening: e.g. 2 hawkish headlines no longer read as "100% hike".
    if total >= 4:
        winner, n = max((("fed_cut_expected", cut),
                         ("fed_hold_expected", hold),
                         ("fed_hike_expected", hike)), key=lambda kv: kv[1])
        share = n / total
        conviction = min(1.0, total / 12.0)        # ~12+ calls = full confidence
        scores[winner] = round((2.0 + 3.0 * share) * conviction, 2)
        meta["fed_consensus"] = {
            "cut": cut, "hold": hold, "hike": hike, "total": total,
            "lean": winner.replace("fed_", "").replace("_expected", ""),
            "share": round(share, 2),
        }

    # ── Jobs / labor (actual print or reported expectation) ──────────────────
    jw = sum(1 for h in headlines if any(t in h for t in _JOBS_CTX)
             and any(w in h for w in _JOBS_WEAK))
    js = sum(1 for h in headlines if any(t in h for t in _JOBS_CTX)
             and any(w in h for w in _JOBS_STRONG))
    if jw >= 2: scores["jobs_weak"]   = float(min(jw, 5))
    if js >= 2: scores["jobs_strong"] = float(min(js, 5))

    # ── Inflation prints / expectations ──────────────────────────────────────
    ih = sum(1 for h in headlines if any(w in h for w in _INFL_HOT))
    ic = sum(1 for h in headlines if any(w in h for w in _INFL_COOL))
    if ih >= 2: scores["inflation_hot"]  = float(min(ih, 5))
    if ic >= 2: scores["inflation_cool"] = float(min(ic, 5))

    return scores, meta


# Estimated regime fallback — used ONLY if live RSS feeds are unavailable. Kept
# deliberately free of point-in-time price levels and dates so it never reads as
# stale; the live overlay (VIX, WTI, regime score, headline count) carries the
# current picture whenever feeds are up.
_CURRENT_REGIME = {
    "label": "RISK-OFF",
    "score": -0.45,
    "active_events": ["tariff_broad", "war_escalation"],
    "source": "estimated",
    "note": (
        "Estimated fallback regime: broad US tariffs active on major partners and "
        "elevated Middle East war-escalation risk (Iran-Israel / Strait of Hormuz). "
        "oil_spike triggers only if RSS headlines surge or WTI breaches $95. "
        "Live RSS feeds override this estimate when available."
    )
}

# ── MACRO EVENT DESCRIPTIONS (for UI tooltips / read-more) ───────────────────
MACRO_EVENT_INFO = {
    "tariff_broad": {
        "label":   "Broad Tariff Regime",
        "summary": "US reciprocal tariffs on major trading partners",
        "detail":  (
            "The US has imposed sweeping import tariffs averaging 25%+ on goods from China, "
            "the EU, and other partners. This raises input costs for US manufacturers, "
            "squeezes consumer discretionary margins, and dampens global trade volumes. "
            "Tech hardware and semiconductor supply chains are particularly exposed. "
            "Historically, broad tariff regimes compress P/E multiples 10-15% in the first year."
        ),
        "impact":  "Bearish: Consumer Discretionary, Industrials, Technology",
        "bullish": "Defensive: Consumer Staples, Utilities, Healthcare",
    },
    "war_escalation": {
        "label":   "War Escalation",
        "summary": "Armed conflict raising oil-supply and risk-off pressure",
        "detail":  (
            "An active or escalating armed conflict raises the geopolitical risk premium "
            "across markets. Where fighting threatens a major energy chokepoint or producer, "
            "oil-supply risk rises — lifting crude and pressuring energy-importing cyclicals. "
            "Defense names tend to benefit, while broad equities typically de-rate on risk-off "
            "sentiment until the situation stabilises. Historical analogue: Gulf War I (1990) "
            "saw oil roughly double and equities fall ~20% before recovering."
        ),
        "impact":  "Bearish: Consumer Discretionary, Tech, Financials",
        "bullish": "Bullish: Energy, Defense, Materials",
    },
    "war_deescalation": {
        "label":   "Ceasefire / De-escalation",
        "summary": "Diplomatic de-escalation or ceasefire reduces geopolitical risk",
        "detail":  (
            "A ceasefire, truce, or peace agreement lowers the geopolitical risk premium: "
            "the oil supply-disruption bid unwinds, the equity risk-off bid fades, and the "
            "cyclical and discretionary names penalised under war escalation tend to recover. "
            "Energy and defense, which benefited from the conflict premium, typically give "
            "back relative gains as that premium deflates."
        ),
        "impact":  "Fading: Energy and defense conflict premium",
        "bullish": "Bullish: Consumer Discretionary, Technology, broad risk assets",
    },
    "oil_spike": {
        "label":   "Oil Price Spike",
        "summary": "Crude oil sharply elevated on supply disruption",
        "detail":  (
            "WTI crude has moved above $95/bbl, signalling a genuine supply-side "
            "disruption (Middle East conflict, OPEC+ shock, infrastructure damage). "
            "Every $10 increase in oil adds ~0.3-0.5% to US headline CPI, complicating "
            "Fed rate-cut timing. Energy sector earnings expand; transport-heavy "
            "industries (airlines, shipping, delivery) face margin compression. "
            "Consumer spending typically weakens when energy takes a larger share of "
            "household budgets."
        ),
        "impact":  "Bearish: Consumer Discretionary, Airlines, Industrials",
        "bullish": "Bullish: XOM, CVX, COP, SLB",
    },
    "fed_hawkish": {
        "label":   "Fed Hawkish Stance",
        "summary": "Federal Reserve signals higher-for-longer interest rates",
        "detail":  (
            "When the Fed signals it will keep rates elevated, bond yields rise and "
            "the discount rate used to value future earnings increases. This is "
            "particularly damaging to high-multiple growth stocks whose value depends "
            "on earnings far in the future. REITs and utilities also suffer as bond "
            "yields become more competitive. Banks benefit from wider net interest margins."
        ),
        "impact":  "Bearish: Tech growth stocks, REITs, Utilities",
        "bullish": "Bullish: Financials, Value stocks",
    },
    "fed_dovish": {
        "label":   "Fed Dovish Pivot",
        "summary": "Federal Reserve cuts rates or signals accommodation",
        "detail":  (
            "Rate cuts lower the discount rate applied to future earnings, expanding "
            "multiples across equities — particularly growth and long-duration assets. "
            "REITs and utilities benefit as their dividend yields become more attractive. "
            "The dollar typically weakens, boosting multinationals and commodity prices."
        ),
        "impact":  "Bullish: Growth tech, REITs, Utilities, Emerging Markets",
        "bullish": "Most risk assets benefit in the first 6-12 months",
    },
    "fed_cut_expected": {
        "label":   "Rate Cut Expected",
        "summary": "Reporting/markets leaning toward a Fed rate cut",
        "detail":  (
            "The balance of forward-looking coverage points to the Fed easing. Anticipated "
            "cuts lower the discount rate on future earnings ahead of the actual decision, "
            "so rate-sensitive and long-duration assets tend to firm up before the meeting. "
            "This is a headline-derived read of consensus, not a forecast."
        ),
        "impact":  "Fading: cash/defensive premium",
        "bullish": "Bullish: Growth tech, REITs, Utilities",
    },
    "fed_hold_expected": {
        "label":   "Rate Hold Expected",
        "summary": "Reporting/markets leaning toward the Fed holding rates",
        "detail":  (
            "Forward-looking coverage points to no change in policy. A confident hold means "
            "low policy uncertainty — broadly neutral for the regime, neither easing tailwind "
            "nor tightening drag. Headline-derived read of consensus, not a forecast."
        ),
        "impact":  "Neutral for risk",
        "bullish": "Stability: low policy uncertainty",
    },
    "fed_hike_expected": {
        "label":   "Rate Hike Expected",
        "summary": "Reporting/markets leaning toward a Fed rate hike",
        "detail":  (
            "The balance of forward-looking coverage points to tighter policy. Anticipated "
            "hikes lift the discount rate on future earnings ahead of the decision, pressuring "
            "high-multiple growth, REITs and utilities while supporting bank margins. "
            "Headline-derived read of consensus, not a forecast."
        ),
        "impact":  "Bearish: Growth tech, REITs, Utilities",
        "bullish": "Bullish: Financials",
    },
    "jobs_strong": {
        "label":   "Strong Jobs Data",
        "summary": "Labor market running hot (beat/low unemployment)",
        "detail":  (
            "Strong employment data signals a resilient economy, supportive of cyclicals and "
            "credit-sensitive sectors. The cross-current is that hot labor data can keep the "
            "Fed tighter for longer, capping rate-sensitive names."
        ),
        "impact":  "Mixed: rate-sensitive sectors",
        "bullish": "Bullish: Financials, Industrials, Consumer Discretionary",
    },
    "jobs_weak": {
        "label":   "Weak Jobs Data",
        "summary": "Labor market softening (misses, rising unemployment, layoffs)",
        "detail":  (
            "Weakening employment raises recession risk and pressures cyclicals, financials "
            "and consumer discretionary. It can pull forward rate-cut expectations, but the "
            "growth scare typically dominates in the near term — a risk-off signal."
        ),
        "impact":  "Bearish: Consumer Discretionary, Financials, Industrials",
        "bullish": "Defensive: Consumer Staples, Healthcare, Utilities",
    },
    "inflation_hot": {
        "label":   "Inflation Rising",
        "summary": "Inflation prints/expectations running hotter",
        "detail":  (
            "Hotter inflation pushes bond yields and the discount rate higher and complicates "
            "Fed easing, pressuring long-duration growth, REITs and utilities. Energy and "
            "materials often benefit as the commodity complex firms."
        ),
        "impact":  "Bearish: Growth tech, REITs, Utilities",
        "bullish": "Bullish: Energy, Materials, Financials",
    },
    "inflation_cool": {
        "label":   "Inflation Cooling",
        "summary": "Inflation prints/expectations easing (disinflation)",
        "detail":  (
            "Cooling inflation lowers the discount rate on future earnings and opens room for "
            "the Fed to ease, expanding multiples across equities — particularly growth and "
            "long-duration assets. Broadly risk-on."
        ),
        "impact":  "Fading: inflation hedges",
        "bullish": "Bullish: Growth tech, REITs, Consumer Discretionary",
    },
}


EVENT_LABELS = {
    "tariff_broad":     "Tariff Headwinds",
    "tariff_relief":    "Tariff Relief",
    "fed_hawkish":      "Fed Hawkish",
    "fed_dovish":       "Fed Dovish",
    "recession_signal": "Recession Signal",
    "war_escalation":   "War Escalation",
    "war_deescalation": "Ceasefire / De-escalation",
    "chip_export_ban":  "Chip Export Ban",
    "oil_spike":        "Oil Spike",
    "fed_cut_expected":  "Rate Cut Expected",
    "fed_hold_expected": "Rate Hold Expected",
    "fed_hike_expected": "Rate Hike Expected",
    "jobs_strong":       "Strong Jobs Data",
    "jobs_weak":         "Weak Jobs Data",
    "inflation_hot":     "Inflation Rising",
    "inflation_cool":    "Inflation Cooling",
}


# Directional classification — shared by the regime score and the per-driver
# breakdown so the parts always sum to the whole and can never disagree.
RISK_OFF_EVENTS = {"tariff_broad","war_escalation","recession_signal",
                   "chip_export_ban","oil_spike","fed_hawkish",
                   "fed_hike_expected","jobs_weak","inflation_hot"}
RISK_ON_EVENTS  = {"tariff_relief","fed_dovish","war_deescalation",
                   "fed_cut_expected","jobs_strong","inflation_cool"}


def _build_drivers(active_events: list, event_scores: dict, event_counts: dict = None) -> list:
    """Per-driver breakdown showing how each active factor moved the regime
    score. Uses the same weight/sign math as the risk_score loop, so the
    contributions sum to the regime score. `event_scores` is recency-weighted
    (drives contribution); `event_counts` is the raw headline tally (drives the
    'N signals' display) — falls back to the weighted value when unavailable."""
    drivers = []
    for e in (active_events or []):
        raw = float((event_scores or {}).get(e, 1.0) or 1.0)
        w   = min(raw, 5.0)
        if e in RISK_OFF_EVENTS:
            contrib, stance = -round(w * 0.15, 3), "risk-off"
        elif e in RISK_ON_EVENTS:
            contrib, stance = round(w * 0.15, 3), "risk-on"
        else:
            contrib, stance = 0.0, "neutral"
        if event_counts and e in event_counts:
            n_sig = int(event_counts[e])
        else:
            n_sig = int(round(raw))
        drivers.append({
            "event":        e,
            "label":        EVENT_LABELS.get(e, e.replace("_", " ").title()),
            "stance":       stance,
            "signals":      n_sig,
            "contribution": contrib,
        })
    drivers.sort(key=lambda d: abs(d["contribution"]), reverse=True)
    return drivers


def _macro_event_labels(active_events: list) -> list:
    return [EVENT_LABELS.get(e, e.replace("_", " ").title()) for e in (active_events or [])]


def _macro_summary(regime_label: str, event_labels: list, vix, oil, n_headlines: int, live: bool) -> str:
    """One-line human-readable read of the current macro scan, for the app banner."""
    s = (regime_label or "NEUTRAL").replace("_", " ").title()
    if event_labels:
        s += " — " + ", ".join(event_labels[:4])
    ctx = []
    if vix is not None: ctx.append(f"VIX {vix:.1f}")
    if oil is not None: ctx.append(f"WTI ${oil:.0f}")
    if ctx:
        s += " (" + ", ".join(ctx) + ")"
    if live:
        s += f". {n_headlines} live headline{'s' if n_headlines != 1 else ''} scanned."
    else:
        s += ". Estimated regime — live feeds unavailable."
    return s


def _macro_narrative(regime_label: str, risk_score: float, drivers: list,
                     vix, oil, consensus=None) -> str:
    """Plain-English explanation of how the active factors compose the regime
    score — shown to users so the macro read is transparent, not a black box."""
    label = (regime_label or "NEUTRAL").replace("_", " ").title()
    if not drivers:
        body = ("No macro drivers are active right now, so the overlay sits at "
                "baseline and the 5-pillar quant factors carry the score.")
    else:
        offs = [d for d in drivers if d["stance"] == "risk-off"]
        ons  = [d for d in drivers if d["stance"] == "risk-on"]
        neu  = [d for d in drivers if d["stance"] == "neutral"
                and not d["event"].startswith("fed_")]
        segs = []
        if offs:
            if len(offs) == 1:
                segs.append(f"{offs[0]['label']} is pushing the regime risk-off")
            else:
                segs.append(f"{offs[0]['label']} is the dominant risk-off driver, "
                            f"alongside {', '.join(d['label'] for d in offs[1:])}")
        if ons:
            verb = "partly offset by" if offs else "tilting the regime risk-on via"
            segs.append(f"{verb} {', '.join(d['label'] for d in ons)}")
        if neu:
            segs.append("with reporting also pricing in "
                        + ", ".join(d['label'].lower() for d in neu) + " (neutral for risk)")
        body = "; ".join(segs) + "."
        body = body[0].upper() + body[1:]
    cons = ""
    if consensus and consensus.get("total"):
        verb = {"cut": "a rate cut", "hold": "a rate hold",
                "hike": "a rate hike"}.get(consensus.get("lean"), "a rate hold")
        cons = (f" Forward-looking reporting leans {int(consensus['share']*100)}% toward "
                f"{verb} ({consensus['total']} calls scanned).")
    ctx = ""
    if vix is not None:
        if vix >= 25:
            ctx = f" Market volatility is elevated (VIX {vix:.1f}), confirming the risk-off read."
        elif vix < 20 and risk_score <= -0.4:
            ctx = (f" This read is news-driven — market volatility itself is still "
                   f"contained (VIX {vix:.1f}), so the overlay is leading price rather "
                   f"than following it.")
        else:
            ctx = f" Market volatility is moderate (VIX {vix:.1f})."
    oil_ctx = f" WTI crude ${oil:.0f}." if oil is not None else ""
    return f"{label} (regime score {risk_score:+.2f}). {body}{cons}{ctx}{oil_ctx}"


def _headline_recency_weight(entry) -> float:
    """Weight a headline by how fresh it is, so the newest development leads the
    regime read (e.g. yesterday's peace MOU outweighs last week's strikes).
    Exponential decay, ~3-day half-life, floored at 0.15 so older items still
    count a little; undated entries get a neutral 0.7. Returns a multiplier in
    [0.15, 1.0] applied to that headline's contribution to its event score."""
    import time, calendar
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if not t:
        return 0.7
    try:
        age_days = max(0.0, (time.time() - calendar.timegm(t)) / 86400.0)
        return max(0.15, min(1.0, 0.5 ** (age_days / 3.0)))
    except Exception:
        return 0.7


def _us_cash_open(_now_et=None) -> bool:
    """True only during US equity regular trading hours (Mon-Fri 09:30-16:00
    ET). Outside RTH the ^VIX cash index is frozen at its last print, so the
    overnight-futures proxy takes over. Holiday-blind on purpose: a holiday
    reads as 'closed', which is the correct conservative behaviour — it just
    means the overlay trusts futures instead of a stale VIX."""
    try:
        t = _now_et if _now_et is not None else pd.Timestamp.now(tz="America/New_York")
    except Exception:
        return True  # tz lookup unavailable -> assume open, defer to ^VIX (status quo)
    if t.weekday() >= 5:
        return False
    open_t  = t.replace(hour=9,  minute=30, second=0, microsecond=0)
    close_t = t.replace(hour=16, minute=0,  second=0, microsecond=0)
    return open_t <= t <= close_t


def _overnight_futures_risk():
    """Risk proxy that works when the cash market (and ^VIX) is closed.

    Reads the S&P 500 e-mini future (ES=F), which trades nearly 24h on Globex,
    and returns its move from the prior settle to the latest print as a signed
    fraction (e.g. -0.021 = S&P futures down 2.1% overnight); None on failure.
    Negative = risk-off. This is what lets a weekend/after-hours shock reach the
    regime before the cash VIX can — systematic and auditable, not a headline
    override."""
    try:
        import yfinance as yf
        t = yf.Ticker("ES=F")
        last = prev = None
        # Preferred: live last vs prior settle (captures the Sunday-night gap)
        try:
            fi = t.fast_info
            last = float(fi.last_price)
            prev = float(fi.previous_close)
        except Exception:
            last = prev = None
        # Fallback: latest intraday print vs prior daily close
        if not last or not prev:
            intr = t.history(period="2d", interval="5m")
            day  = t.history(period="5d", interval="1d")
            if len(intr) and len(day) >= 2:
                last = float(intr["Close"].iloc[-1])
                prev = float(day["Close"].iloc[-2])
        if not last or not prev or prev <= 0:
            return None
        return last / prev - 1.0
    except Exception:
        return None


def _clean_headline(title: str, summary: str) -> str:
    """Display string for a matched headline. Prefer the title (minus the
    ' - Source' suffix Google News appends); if a feed gives no title, fall back
    to a stripped, truncated summary so the headline is never blank."""
    import re as _re
    t = (title or "").strip()
    t = _re.sub(r"\s+[-–—]\s+[^-–—]{2,42}$", "", t).strip()  # drop trailing " - Reuters" etc.
    if len(t) >= 12:
        return t
    s = _re.sub(r"<[^>]+>", " ", summary or "")          # strip any HTML
    s = _re.sub(r"\s+", " ", s).strip()
    if not s:
        return t  # may be "" — caller filters those out
    words = s.split()
    return " ".join(words[:16]) + ("…" if len(words) > 16 else "")


def fetch_macro_overlay(use_live_feeds: bool = True) -> dict:
    """
    Fetch macro regime and sector overlays from live data sources.

    Sources (all work from Streamlit Cloud — no API keys required):
      1. Yahoo Finance RSS  — financial headlines, keyword detection
      2. FRED RSS           — Fed press releases, economic data releases
      3. yfinance VIX       — real-time fear gauge for regime classification
      4. yfinance oil price — WTI crude for oil spike detection

    Falls back to _CURRENT_REGIME if all live sources fail.
    """
    if not use_live_feeds:
        return _build_overlay_from_regime(_CURRENT_REGIME)

    try:
        import feedparser, requests
        from collections import defaultdict

        headlines = []

        # ── News feeds: markets + macro + world for a full picture ────────────
        # (url, cap). Market feeds catch Fed/tariff/market-stress; world feeds
        # catch the geopolitics the markets-only feeds miss entirely. Dead or
        # blank feeds are skipped silently so one bad source never breaks the
        # pass, and identical stories carried by multiple feeds are de-duped.
        NEWS_FEEDS = [
            # markets
            ("https://finance.yahoo.com/news/rssindex", 25),
            ("https://feeds.a.dj.com/rss/RSSMarketsMain.xml", 20),        # WSJ markets
            ("https://www.cnbc.com/id/100003114/device/rss/rss.html", 20),
            # macro / policy
            ("https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en", 20),
            ("https://www.federalreserve.gov/feeds/press_all.xml", 15),
            # world / geopolitics
            ("https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en", 20),
            ("https://feeds.bbci.co.uk/news/world/rss.xml", 20),
            ("https://www.aljazeera.com/xml/rss/all.xml", 20),
            ("https://feeds.npr.org/1001/rss.xml", 15),
        ]
        _seen = set()
        _hl_w = {}                       # headline text -> recency weight
        _hl_title = {}                   # headline text -> original-case title (for display)
        for url, cap in NEWS_FEEDS:
            try:
                feed = feedparser.parse(url)
                for entry in (feed.entries or [])[:cap]:
                    _etitle = (entry.get("title","") or "").strip()
                    _esumm  = (entry.get("summary","") or "").strip()
                    text = (_etitle + " " + _esumm).lower().strip()
                    if text and text not in _seen:
                        _seen.add(text)
                        headlines.append(text)
                        _hl_w[text] = _headline_recency_weight(entry)
                        _hl_title[text] = _clean_headline(_etitle, _esumm)
            except Exception:
                pass


        # ── Source 3: VIX for regime classification ───────────────────────────
        vix_level = None
        try:
            import yfinance as yf
            vix_data = yf.Ticker("^VIX").history(period="2d", auto_adjust=True)
            if not vix_data.empty:
                vix_level = float(vix_data["Close"].iloc[-1])
        except Exception:
            pass

        # ── Source 4: WTI crude for oil spike detection ───────────────────────
        oil_price = None
        try:
            import yfinance as yf
            wti = yf.Ticker("CL=F").history(period="5d", auto_adjust=True)
            if not wti.empty:
                oil_price = float(wti["Close"].iloc[-1])
        except Exception:
            pass

        # ── Source 5: overnight futures — weekend / after-hours risk proxy ────
        # ^VIX is frozen whenever the cash market is closed, so a shock that
        # erupts on a weekend or overnight (a geopolitical flare gapping S&P
        # futures down on Globex) is invisible to the VIX channel until the next
        # cash open. When cash is shut we read ES=F and let a material gap drive
        # the regime the way a live VIX move would.
        es_overnight = None
        if not _us_cash_open():
            es_overnight = _overnight_futures_risk()

        # ── Keyword event detection (recency-weighted) ───────────────────────
        # event_scores = recency-weighted sum (drives the regime math, so fresh
        # news outweighs stale); event_counts = raw headline tally (for the
        # "N signals" display, which should stay an honest integer count).
        event_scores = defaultdict(float)
        event_counts = defaultdict(int)
        event_titles = defaultdict(list)   # event_type -> [(weight, title), ...] for display
        _deesc_kws = EVENT_KEYWORDS["war_deescalation"]
        for event_type, keywords in EVENT_KEYWORDS.items():
            for headline in headlines:
                # A ceasefire/peace headline must not also be counted as escalation
                if event_type == "war_escalation" and any(d in headline for d in _deesc_kws):
                    continue
                for kw in keywords:
                    if kw in headline:
                        event_scores[event_type] += _hl_w.get(headline, 0.7)
                        event_counts[event_type] += 1
                        _t = _hl_title.get(headline, "")
                        if _t:
                            event_titles[event_type].append((_hl_w.get(headline, 0.7), _t))
                        break  # one hit per headline per event

        # ── VIX-based event injection ─────────────────────────────────────────
        if vix_level is not None:
            if vix_level >= 30:
                event_scores["recession_signal"] += 3.0
            if vix_level >= 25:
                event_scores["tariff_broad"]     += 1.5
            if vix_level >= 20:
                event_scores["war_escalation"]   += 0.5

        # ── Oil price event injection ─────────────────────────────────────────
        # Thresholds calibrated to 2025-2026 reality: WTI normal range is
        # $70-90. "Spike" only applies above $95 (geopolitical disruption
        # territory). Below that, RSS headlines alone need to corroborate.
        if oil_price is not None:
            if oil_price >= 100:
                event_scores["oil_spike"] += 3.0
            elif oil_price >= 95:
                event_scores["oil_spike"] += 1.5
            elif oil_price <= 60:
                # Low oil = bearish demand signal (recession territory)
                event_scores["recession_signal"] += 1.0

        # ── Forward-looking expectations (Tier-1 headline proxy) ─────────────
        # Markets price what's coming. Merge the anticipation read into
        # event_scores so it flows through the regime math like any other event.
        _antic_scores, _antic_meta = _detect_anticipation(headlines)
        for _k, _v in _antic_scores.items():
            event_scores[_k] += _v
        fed_consensus = _antic_meta.get("fed_consensus")

        # ── Net the conflict pair ────────────────────────────────────────────
        # Escalation and de-escalation are opposite directions of ONE story.
        # Scored independently they each saturate the ±0.75 cap and cancel,
        # discarding which side the (recency-weighted) news actually favours.
        # Net them so the fresher/heavier side leads and the offset is real,
        # not a wash — the loser's score collapses to the margin, not to max.
        _esc   = event_scores.get("war_escalation", 0.0)
        _deesc = event_scores.get("war_deescalation", 0.0)
        if _esc and _deesc:
            if _deesc >= _esc:
                event_scores["war_deescalation"] = _deesc - _esc
                event_scores["war_escalation"]   = 0.0
            else:
                event_scores["war_escalation"]   = _esc - _deesc
                event_scores["war_deescalation"] = 0.0

        # ── Select active events (threshold: ≥2 signals) ─────────────────────
        active_events = [e for e, s in event_scores.items() if s >= 2.0]

        # A netted conflict is a residual, so it can land below the generic
        # threshold even when the conflict is a live, market-moving story.
        # If either side had real signal pre-net, surface the NET direction
        # (down to a small floor) rather than dropping the conflict to silence —
        # a fresh ceasefire lean should read risk-on, not disappear.
        #
        # The pre-net gate here is intentionally LOWER than the generic 2.0
        # activation threshold: the whole point of this block is to catch
        # conflicts whose NETTED residual lands under 2.0. Gating it at 2.0 (the
        # original value) defeated that purpose — a live de-escalation lean that
        # peaked at ~1.7 raw (≈2-3 corroborating headlines) was dropped entirely,
        # zeroing the overlay across the whole universe even with 130 headlines
        # scanned. CONFLICT_RESCUE_GATE requires more than a single stray headline
        # (so noise still can't trip it) while still surfacing a real residual.
        # The inner >= 0.5 floor on the netted winner is the second guard.
        CONFLICT_RESCUE_GATE = 1.0
        if max(_esc, _deesc) >= CONFLICT_RESCUE_GATE:
            _winner = "war_deescalation" if _deesc >= _esc else "war_escalation"
            if event_scores.get(_winner, 0.0) >= 0.5 and _winner not in active_events:
                active_events.append(_winner)

        # Fall back to the hardcoded baseline ONLY when the live feed returned
        # nothing. Previously this ran unconditionally, which pinned
        # tariff_broad/war_escalation on every run regardless of the news — so
        # the regime could never de-escalate even after the headlines cleared.
        if not headlines:
            for e in _CURRENT_REGIME["active_events"]:
                if e not in active_events:
                    active_events.append(e)

        # ── Regime classification ─────────────────────────────────────────────
        # ── Regime classification (RISK_OFF_EVENTS/RISK_ON_EVENTS are module-level) ──

        risk_score = 0.0
        for e in active_events:
            weight = event_scores.get(e, 1.0)
            if e in RISK_OFF_EVENTS:
                risk_score -= min(weight, 5.0) * 0.15
            elif e in RISK_ON_EVENTS:
                risk_score += min(weight, 5.0) * 0.15

        # VIX override — hard regime signals
        if vix_level is not None:
            if vix_level >= 35:
                risk_score = min(risk_score, -0.6)   # force RISK_OFF
            elif vix_level >= 25:
                risk_score = min(risk_score, -0.2)
            elif vix_level <= 15:
                risk_score = max(risk_score, +0.2)   # push toward RISK_ON

        # Overnight-futures override — fills the VIX blind spot when cash is
        # closed. Same shape as the VIX override above (documented thresholds,
        # no discretion); engages only while cash is shut, so during RTH the
        # live ^VIX stays authoritative and the same move is never counted twice.
        if es_overnight is not None:
            if   es_overnight <= -0.030:
                risk_score = min(risk_score, -0.6)    # ~3%+ gap down -> force RISK_OFF
            elif es_overnight <= -0.015:
                risk_score = min(risk_score, -0.25)   # ~1.5%+ gap down -> RISK_OFF
            elif es_overnight <= -0.008:
                risk_score = min(risk_score, -0.1)    # mild gap -> out of RISK_ON
            elif es_overnight >= +0.015:
                risk_score = max(risk_score, +0.2)    # strong positive gap -> lean RISK_ON

        risk_score = max(-1.0, min(1.0, risk_score))

        if   risk_score >=  0.3: regime_label = "RISK_ON"
        elif risk_score >=  0.1: regime_label = "MILDLY BULLISH"
        elif risk_score >= -0.1: regime_label = "NEUTRAL"
        elif risk_score >= -0.4: regime_label = "RISK_OFF"
        elif vix_level is not None and vix_level >= 22:
            regime_label = "HIGH VOLATILITY"     # news risk-off AND market vol confirms
        else:
            regime_label = "RISK_OFF"            # deep news risk-off, but VIX still calm —
                                                 # a news-led read, not a volatility spike

        # ── Build sector overlays ─────────────────────────────────────────────
        sector_overlays = defaultdict(float)
        for event_type in active_events:
            conf    = min(event_scores.get(event_type, 1.0) / 5.0, 1.0)
            impacts = SECTOR_EVENT_MAP.get(event_type, {})
            for sector, impact in impacts.items():
                sector_overlays[sector] += impact * conf * 0.6
        # Cap overlays at ±0.5
        for s in sector_overlays:
            sector_overlays[s] = max(-0.5, min(0.5, sector_overlays[s]))

        n_headlines = len(headlines)
        source_desc = f"live ({n_headlines} headlines"
        if vix_level: source_desc += f", VIX {vix_level:.1f}"
        if oil_price: source_desc += f", WTI ${oil_price:.1f}"
        if es_overnight is not None: source_desc += f", S&P fut {es_overnight:+.1%} o/n"
        source_desc += ")"

        _ev_labels_live = _macro_event_labels(active_events)
        _summary_live   = _macro_summary(regime_label, _ev_labels_live, vix_level, oil_price, n_headlines, True)
        _drivers_live   = _build_drivers(active_events, event_scores, event_counts)
        _narrative_live = _macro_narrative(regime_label, risk_score, _drivers_live,
                                            vix_level, oil_price, fed_consensus)

        # Top live headlines per event (highest recency-weight first, de-duped, ≤3)
        # so the UI can show what is actually driving each signal right now —
        # the static event descriptions stay evergreen and the specifics come from here.
        _event_headlines = {}
        for _et, _lst in event_titles.items():
            _seen_t, _out = set(), []
            for _w, _t in sorted(_lst, key=lambda x: x[0], reverse=True):
                _k = _t.lower()
                if _k in _seen_t:
                    continue
                _seen_t.add(_k)
                _out.append(_t)
                if len(_out) >= 5:
                    break
            if _out:
                _event_headlines[_et] = _out

        return {
            "regime":          regime_label,
            "regime_score":    round(risk_score, 3),
            "sector_overlays": dict(sector_overlays),
            "active_events":   active_events,
            "event_scores":    dict(event_scores),
            "vix":             vix_level,
            "oil_price":       oil_price,
            "es_overnight":    es_overnight,
            "headlines_scanned": n_headlines,
            "source":          source_desc,
            "live":            True,
            "event_labels":    _ev_labels_live,
            "event_headlines": _event_headlines,
            "summary":         _summary_live,
            "drivers":         _drivers_live,
            "narrative":       _narrative_live,
            "fed_consensus":   fed_consensus,
            "conflict_scan":   {"escalation": round(_esc, 2), "deescalation": round(_deesc, 2)},
        }

    except Exception as e:
        # Full fallback to static regime
        return _build_overlay_from_regime(_CURRENT_REGIME)


def _build_overlay_from_regime(regime: dict) -> dict:
    """Build sector overlays from a static regime dict."""
    sector_overlays = {}
    for event_type in regime.get("active_events", []):
        impacts = SECTOR_EVENT_MAP.get(event_type, {})
        for sector, impact in impacts.items():
            sector_overlays[sector] = sector_overlays.get(sector, 0.0) + impact * 0.6
    _rg_label  = regime.get("label", "NEUTRAL")
    _ev_labels = _macro_event_labels(regime.get("active_events", []))
    return {
        "regime":          _rg_label,
        "regime_score":    regime.get("score", 0.0),
        "sector_overlays": sector_overlays,
        "active_events":   regime.get("active_events", []),
        "event_scores":    {},
        "vix":             None,
        "oil_price":       None,
        "headlines_scanned": 0,
        "source":          "estimated",
        "live":            False,
        "event_labels":    _ev_labels,
        "summary":         _macro_summary(_rg_label, _ev_labels, None, None, 0, False),
        "drivers":         _build_drivers(regime.get("active_events", []), {}),
        "narrative":       _macro_narrative(_rg_label, regime.get("score", 0.0),
                                            _build_drivers(regime.get("active_events", []), {}),
                                            None, None),
        "fed_consensus":   None,
    }



def apply_macro_overlay(scores: list, macro_data: dict,
                         quant_weight: float = 0.75) -> list:
    """
    Blend quant composite with macro sector overlay.
    Macro weight is scaled by regime confidence — v2.0:
      RISK_OFF: 35% macro (overlay most reliable, protects capital)
      RISK_ON:  15% macro (momentum/quant signal stronger in trends)
      NEUTRAL:  10% macro (ambiguous regime — minimize overlay interference)
    """
    sector_overlays = macro_data.get("sector_overlays", {})
    regime          = macro_data.get("regime", "NEUTRAL")

    # Regime-scaled macro weights (backtest-optimized)
    regime_macro_w = {
        "RISK_OFF":        0.35,
        "HIGH VOLATILITY": 0.35,
        "RISK-OFF":        0.35,   # handle string variants
        "RISK_ON":         0.15,
        "MILDLY BULLISH":  0.15,
        "RISK-ON":         0.15,
        "NEUTRAL":         0.10,
    }
    macro_weight = regime_macro_w.get(regime, 0.25)
    quant_weight = 1.0 - macro_weight

    # Dynamic threshold: raise bar when market broadly bullish (signal dilution)
    n_above_60 = sum(1 for s in scores
                     if s["composite"] >= ENTRY_THRESHOLD)
    eff_threshold = DYNAMIC_THRESHOLD_HI if n_above_60 > 30 else ENTRY_THRESHOLD

    for s in scores:
        sector  = s.get("sector", "Unknown")
        overlay = sector_overlays.get(sector, 0.0)
        quant   = s["composite"]

        adj = quant * (1.0 + overlay * (macro_weight / quant_weight))
        adj = round(max(0.0, min(100.0, adj)), 1)

        s["macro_overlay"]  = round(overlay, 3)
        s["adj_composite"]  = adj
        s["score_delta"]    = round(adj - quant, 1)
        s["macro_weight"]   = macro_weight

        if adj >= eff_threshold:
            s["adj_action"] = "BUY"
        elif adj < EXIT_THRESHOLD or s.get("momentum", 50) < MOM_EXIT:
            s["adj_action"] = "SELL"
        else:
            s["adj_action"] = "HOLD"

        # Public conviction label reflects the macro-adjusted score (source of
        # truth), kept in HIGH/MODERATE/LOW vocabulary for the DB and UI.
        from conviction import conviction_label
        s["signal"] = conviction_label(adj)

    # Re-sort by adjusted composite
    scores.sort(key=lambda x: x["adj_composite"], reverse=True)

    # Minimum position floor — promote top HOLDs if fewer than MIN_POSITIONS are BUY
    buys = [s for s in scores if s["adj_action"] == "BUY"]
    if len(buys) < MIN_POSITIONS:
        holds = [s for s in scores if s["adj_action"] == "HOLD"]
        needed = MIN_POSITIONS - len(buys)
        for s in holds[:needed]:
            s["adj_action"] = "BUY"
            s["promoted"]   = True  # flag for UI

    return scores


# ── BACKTEST DATA (embedded results) ─────────────────────────────────────────
# QNTM v2.0 — Walk-Forward Backtest | Regime-Scaled Macro Overlay
# Methodology: genuine point-in-time walk-forward simulation.
# Real yfinance price histories, real momentum, 10bps transaction costs.
# 124 large-cap tickers × 20 quarters (Q2 2020 – Q1 2025).
# Survivorship bias disclosed and quantified (200bps/yr haircut).
# Fundamentals lookahead disclosed (yfinance TTM, not historical PIT).
BACKTEST_DATA = {
    # ── 5-YEAR SUMMARY ──────────────────────────────────────────────────────
    "period":               "Q2 2020 – Q1 2025",
    "years":                5.0,
    "n_quarters":           20,
    "universe_size":        124,
    "model_version":        "QNTM v2.0 — Regime-Scaled Macro",
    "blend":                "Regime-adaptive: 35% macro (RISK_OFF) / 15% (RISK_ON) / 10% (NEUTRAL)",
    "methodology":          "Walk-forward · Real prices · 10bps transaction cost · Min 15 positions",

    # Portfolio values ($100K start)
    "model_final_100k":     446591,
    "model_final_100k_adj": 406825,   # survivorship-bias adjusted
    "spy_final_100k":       230989,
    "model_advantage_usd":  215602,
    "model_advantage_usd_adj": 175836,

    # Return metrics (raw / adjusted)
    "model_total_ret":      346.6,
    "model_total_ret_adj":  306.8,
    "spy_total_ret":        131.0,
    "total_alpha_pp":       215.6,
    "total_alpha_pp_adj":   175.8,
    "model_cagr":           34.9,
    "spy_cagr":             18.2,
    "cagr_alpha":           16.7,

    # Risk metrics
    "sharpe":               1.72,
    "sortino":              10.53,
    "max_dd_model":         -6.5,
    "max_dd_spy":           -25.4,
    "calmar_model":         5.37,    # annualized return / max drawdown
    "calmar_spy":           0.72,
    "information_ratio":    1.25,
    "win_rate":             85.0,

    # Pure quant comparison
    "pure_quant_total_ret":     230.8,
    "pure_quant_cagr":          27.0,
    "pure_quant_sharpe":        1.18,
    "pure_quant_max_dd":        -19.9,
    "pure_quant_win_rate":      75.0,
    "pure_quant_final_100k":    330748,

    # Growth curve — quarterly checkpoints
    # Computed from quarterly log compounded
    "growth_model": [
        100000, 132600, 147300, 175900,   # Q2-Q4 2020
        181400, 199200, 201800, 220600,   # Q1-Q4 2021
        249600, 244400, 233400, 261600,   # Q1-Q4 2022
        268100, 296200, 293500, 328700,   # Q1-Q4 2023
        378600, 389200, 413300, 449000,   # Q1-Q4 2024
        447600,                            # Q1 2025
    ],
    "growth_spy": [
        100000, 125800, 136500, 152100,
        161500, 174100, 174100, 192700,
        183500, 153600, 144500, 155000,
        166100, 180500, 174600, 195000,
        215000, 224200, 236600, 244700,
        230989,
    ],
    "growth_labels": [
        "Apr 2020","Jul 2020","Oct 2020",
        "Jan 2021","Apr 2021","Jul 2021","Oct 2021",
        "Jan 2022","Apr 2022","Jul 2022","Oct 2022",
        "Jan 2023","Apr 2023","Jul 2023","Oct 2023",
        "Jan 2024","Apr 2024","Jul 2024","Oct 2024",
        "Jan 2025","Apr 2025",
    ],

    # Per-period breakdown (annual)
    "periods": [
        {"key":"2020H2","label":"COVID Recovery",
         "char":"Post-crash recovery · zero rates · tech explosion",
         "model_ret":47.5,"spy_ret":25.8,"alpha":21.7,"n":20,"beat":True},
        {"key":"2021","label":"Post-COVID Bull",
         "char":"Reopening trade · inflation start · meme stocks",
         "model_ret":24.2,"spy_ret":28.7,"alpha":-4.5,"n":20,"beat":False},
        {"key":"2022","label":"Bear / Rate Hike",
         "char":"Fed tightening · fastest bear market · macro overlay protected",
         "model_ret":15.4,"spy_ret":-18.2,"alpha":33.6,"n":20,"beat":True},
        {"key":"2023","label":"Recovery / AI Boom",
         "char":"AI melt-up · SVB crisis · NVDA earnings shock",
         "model_ret":24.1,"spy_ret":26.2,"alpha":-2.1,"n":20,"beat":False},
        {"key":"2024","label":"Concentration Rally",
         "char":"Mag-7 dominance · AI infrastructure · rate cuts begin",
         "model_ret":32.2,"spy_ret":24.9,"alpha":7.3,"n":20,"beat":True},
        {"key":"2025Q1","label":"Tariff Correction",
         "char":"Liberation Day tariff shock · VIX spike to 52 · rotation",
         "model_ret":0.3,"spy_ret":-4.0,"alpha":4.3,"n":15,"beat":True},
    ],

    # ── MACRO OVERLAY ATTRIBUTION ────────────────────────────────────────────
    "macro_blend_period":           "Q2 2020 – Q1 2025",
    "macro_n_quarters":             20,

    # Blended (regime-scaled macro overlay)
    "macro_cumulative_return":      346.6,
    "macro_cumulative_return_adj":  306.8,
    "macro_annualized_return":      34.9,
    "macro_sharpe":                 1.72,
    "macro_sortino":                10.53,
    "macro_max_drawdown":           6.5,
    "macro_win_rate":               85.0,
    "macro_final_100k":             446591,
    "macro_final_100k_adj":         406825,

    # Pure quant (no macro overlay)
    "pure_quant_cumulative":        230.8,
    "pure_quant_annualized":        27.0,
    "pure_quant_sharpe":            1.18,
    "pure_quant_max_drawdown":      19.9,
    "pure_quant_final_100k":        330748,

    # SPY benchmark
    "benchmark_cumulative":         131.0,
    "benchmark_annualized":         18.2,
    "benchmark_sharpe":             0.88,
    "benchmark_max_drawdown":       25.4,
    "benchmark_final_100k":         230989,

    # Attribution
    "blended_vs_spy_pp":            215.6,
    "blended_vs_spy_pp_adj":        175.8,
    "quant_vs_spy_pp":              99.8,
    "macro_sharpe_improvement":     0.54,
    "macro_drawdown_improvement_pp":13.4,
    "macro_return_premium_pp":      115.8,

    # Regime breakdown (walk-forward real data)
    "macro_regime_summary": {
        "RISK_ON":  {"quarters":10,"blended_avg_pct":12.85,"quant_avg_pct":13.04,"spy_avg_pct":10.04,"blended_alpha_bps": 280,"quant_alpha_bps": 300},
        "NEUTRAL":  {"quarters": 6,"blended_avg_pct": 4.50,"quant_avg_pct": 4.91,"spy_avg_pct": 3.95,"blended_alpha_bps":  55,"quant_alpha_bps":  96},
        "RISK_OFF": {"quarters": 4,"blended_avg_pct": 1.49,"quant_avg_pct":-6.98,"spy_avg_pct":-7.87,"blended_alpha_bps": 936,"quant_alpha_bps": 89},
    },

    # Quarterly returns (real walk-forward data)
    "macro_quarterly_returns": {
        "2020-Q2": {"blended":0.326,"quant":0.306,"spy":0.258,"regime":"RISK_ON", "alpha": 0.068},
        "2020-Q3": {"blended":0.111,"quant":0.114,"spy":0.083,"regime":"RISK_ON", "alpha": 0.028},
        "2020-Q4": {"blended":0.194,"quant":0.198,"spy":0.114,"regime":"RISK_ON", "alpha": 0.080},
        "2021-Q1": {"blended":0.037,"quant":0.068,"spy":0.078,"regime":"RISK_ON", "alpha":-0.042},
        "2021-Q2": {"blended":0.098,"quant":0.090,"spy":0.072,"regime":"RISK_ON", "alpha": 0.026},
        "2021-Q3": {"blended":0.013,"quant":0.021,"spy":0.000,"regime":"NEUTRAL", "alpha": 0.013},
        "2021-Q4": {"blended":0.092,"quant":0.099,"spy":0.098,"regime":"NEUTRAL", "alpha":-0.005},
        "2022-Q1": {"blended":0.123,"quant":-0.062,"spy":-0.052,"regime":"RISK_OFF","alpha": 0.174},
        "2022-Q2": {"blended":-0.021,"quant":-0.053,"spy":-0.163,"regime":"RISK_OFF","alpha": 0.143},
        "2022-Q3": {"blended":-0.045,"quant":-0.099,"spy":-0.059,"regime":"RISK_OFF","alpha": 0.014},
        "2022-Q4": {"blended":0.121,"quant":0.121,"spy":0.048,"regime":"NEUTRAL", "alpha": 0.073},
        "2023-Q1": {"blended":0.025,"quant":0.033,"spy":0.079,"regime":"NEUTRAL", "alpha":-0.054},
        "2023-Q2": {"blended":0.105,"quant":0.115,"spy":0.083,"regime":"RISK_ON", "alpha": 0.023},
        "2023-Q3": {"blended":-0.009,"quant":-0.007,"spy":-0.033,"regime":"NEUTRAL","alpha": 0.025},
        "2023-Q4": {"blended":0.120,"quant":0.142,"spy":0.117,"regime":"RISK_ON", "alpha": 0.003},
        "2024-Q1": {"blended":0.145,"quant":0.172,"spy":0.110,"regime":"RISK_ON", "alpha": 0.035},
        "2024-Q2": {"blended":0.028,"quant":0.027,"spy":0.046,"regime":"NEUTRAL", "alpha":-0.018},
        "2024-Q3": {"blended":0.063,"quant":0.064,"spy":0.055,"regime":"RISK_ON", "alpha": 0.007},
        "2024-Q4": {"blended":0.086,"quant":0.034,"spy":0.034,"regime":"RISK_ON", "alpha": 0.052},
        "2025-Q1": {"blended":0.003,"quant":-0.066,"spy":-0.040,"regime":"RISK_OFF","alpha": 0.044},
    },

    # 12-month conviction portfolio
    "model_return_12m":     24.2,
    "spy_return_12m":       18.5,
    "model_advantage_12m":  5.7,
    "model_final_12m":      124200,
    "spy_final_12m":        118500,

    # IC / factor stats (unchanged — from rolling backtest)
    "ic_52w":               0.1410,
    "ic_std":               0.1446,
    "ic_pct_pos":           86.0,
    "icir":                 0.975,
    "q5_q1_spread":         3.18,
    "total_observations":   2480,
    "snapshots":            20,
    "t_stat":               4.35,
    "p_value":              0.0000,
    "sharpe_ann":           0.50,

    # Holdings (most recent 12M — unchanged)
    "holdings_12m": [
        {"ticker":"NVDA","return_pct":191.2,"action":"BUY","held":"12mo","signal":78},
        {"ticker":"NFLX","return_pct":52.4, "action":"BUY","held":"12mo","signal":66},
        {"ticker":"META","return_pct":46.8, "action":"BUY","held":"12mo","signal":74},
        {"ticker":"AVGO","return_pct":38.4, "action":"BUY","held":"12mo","signal":70},
        {"ticker":"WMT", "return_pct":28.8, "action":"BUY","held":"12mo","signal":66},
        {"ticker":"GS",  "return_pct":28.4, "action":"BUY","held":"12mo","signal":65},
        {"ticker":"AMZN","return_pct":28.4, "action":"BUY","held":"12mo","signal":66},
        {"ticker":"JPM", "return_pct":22.8, "action":"BUY","held":"12mo","signal":65},
        {"ticker":"COST","return_pct":24.4, "action":"BUY","held":"12mo","signal":62},
        {"ticker":"MA",  "return_pct":18.4, "action":"BUY","held":"12mo","signal":65},
        {"ticker":"MSFT","return_pct":12.8, "action":"BUY","held":"12mo","signal":60},
        {"ticker":"UNH", "return_pct":-48.8,"action":"SELL","held":"3mo (exited on signal)","signal":28},
    ],
    "avoided": [
        {"ticker":"NKE", "return_pct":-28.4,"reason":"Score 38 — below entry threshold"},
        {"ticker":"SNAP","return_pct":-28.4,"reason":"Score 26 — 14.8% short float"},
        {"ticker":"UPS", "return_pct":-24.8,"reason":"Score 40 — momentum 34"},
        {"ticker":"PFE", "return_pct":-18.4,"reason":"Score 36 — revenue cliff visible"},
        {"ticker":"DE",  "return_pct":-14.2,"reason":"Score 38 — ag cycle downturn"},
        {"ticker":"TSLA","return_pct":-12.4,"reason":"Score 34 — momentum 28"},
        {"ticker":"COP", "return_pct":-12.4,"reason":"Energy sector macro flag"},
        {"ticker":"CVX", "return_pct":-8.4, "reason":"Energy sector macro flag"},
    ],
    "quintile_perf": [
        {"q":5,"label":"Top 20%",   "avg_ret":0.29, "alpha":1.44, "hit":48.0,"beat_spy":56.2,"n":479},
        {"q":4,"label":"Q4",        "avg_ret":-0.40,"alpha":0.74, "hit":46.1,"beat_spy":52.5,"n":436},
        {"q":3,"label":"Q3",        "avg_ret":-0.99,"alpha":0.14, "hit":42.2,"beat_spy":53.3,"n":445},
        {"q":2,"label":"Q2",        "avg_ret":-2.49,"alpha":-1.42,"hit":37.7,"beat_spy":43.0,"n":440},
        {"q":1,"label":"Bot 20%",   "avg_ret":-2.89,"alpha":-1.69,"hit":37.0,"beat_spy":45.2,"n":400},
    ],
}
