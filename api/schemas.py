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


class ScreenerResponse(BaseModel):
    as_of: Optional[str] = None     # signal_date of the data, ISO yyyy-mm-dd
    regime: Regime
    total: int                      # rows matching the filters (pre-pagination)
    count: int                      # rows in THIS page
    offset: int
    limit: int
    rows: list[ScreenerRow]
