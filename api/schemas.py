"""
QNTM API — response schemas.

These define the JSON contract the Next.js front-end consumes. Keeping them in
one place means the front-end types can be generated/mirrored from here, and any
field change is a deliberate, visible edit to the contract.
"""

from typing import Optional
from pydantic import BaseModel


class Regime(BaseModel):
    label: str                      # e.g. "MILDLY BULLISH", "RISK_OFF", "NEUTRAL"
    vix: Optional[float] = None
    event: Optional[str] = None     # top active macro event label, if any
    summary: Optional[str] = None   # one-line human-readable macro read


class ScreenerRow(BaseModel):
    ticker: str
    sector: str
    conviction: str                 # HIGH | MODERATE | LOW
    action: str = "HOLD"            # BUY | HOLD | SELL (derived from conviction)
    score: float                    # adj_composite (macro-adjusted, the headline)
    composite: float                # raw quant composite (pre-overlay)
    momentum: float
    quality: float
    volume: float
    value: float
    sentiment: float
    macro_overlay: Optional[float] = None
    price: Optional[float] = None
    value_position: Optional[float] = None  # 0-100, low = cheaper in its range
    is_hidden_gem: bool = False
    # ── card fields ──
    mktcap: Optional[str] = None            # "large" | "mid" | "small"
    val_low: Optional[float] = None         # valuation band floor ($)
    val_high: Optional[float] = None        # valuation band ceiling ($)
    val_basis: Optional[str] = None         # "valuation" | "technical" | "na"
    signal_date: Optional[str] = None       # ISO date of this score row


class MacroDriver(BaseModel):
    label: str = ""
    contribution: float = 0.0
    signals: int = 0
    event: Optional[str] = None


class MacroDetail(BaseModel):
    regime: str = "NEUTRAL"
    vix: Optional[float] = None
    oil_price: Optional[float] = None
    active_events: list[str] = []
    source: Optional[str] = None
    live: bool = False
    headlines_scanned: int = 0
    narrative: Optional[str] = None
    summary: Optional[str] = None
    regime_score: Optional[float] = None
    drivers: list[MacroDriver] = []
    event_headlines: dict[str, list[str]] = {}


class ScreenerResponse(BaseModel):
    as_of: Optional[str] = None     # signal_date of the data, ISO yyyy-mm-dd
    regime: Regime
    total: int                      # rows matching the filters (pre-pagination)
    count: int                      # rows in THIS page
    offset: int
    limit: int
    rows: list[ScreenerRow]
