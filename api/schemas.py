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


class PricePoint(BaseModel):
    d: str
    v: float


class PriceSeriesResponse(BaseModel):
    ticker: str
    days: int
    stock: list[PricePoint] = []
    spy: list[PricePoint] = []
    stock_ret_pct: Optional[float] = None
    spy_ret_pct: Optional[float] = None


class StockChangePillar(BaseModel):
    key: str
    label: str
    delta: int


class StockChanges(BaseModel):
    prev_date: Optional[str] = None
    prev_score: Optional[int] = None
    now_score: Optional[int] = None
    pillars: list[StockChangePillar] = []
    macro_delta: Optional[int] = None
    macro_unchanged: bool = False


class StockResponse(ScreenerRow):
    pct_rank: int = 0
    changes: Optional[StockChanges] = None


class WatchlistItem(ScreenerRow):
    price_at_add: Optional[float] = None
    added_at: Optional[str] = None
    change_pct: Optional[float] = None


class WatchlistResponse(BaseModel):
    regime: Regime
    count: int
    items: list[WatchlistItem] = []


class TickerRequest(BaseModel):
    ticker: str


class HoldingItem(ScreenerRow):
    shares: float = 0.0
    avg_cost: float = 0.0
    entry_date: Optional[str] = None
    notes: Optional[str] = None
    market_value: Optional[float] = None
    cost_basis: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None


class PortfolioSummary(BaseModel):
    count: int = 0
    hi: int = 0
    mo: int = 0
    lo: int = 0
    avg_score: Optional[float] = None
    total_value: float = 0.0
    total_cost: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: Optional[float] = None


class PortfolioResponse(BaseModel):
    regime: Regime
    summary: PortfolioSummary
    holdings: list[HoldingItem] = []


class AddHoldingRequest(BaseModel):
    ticker: str
    shares: float
    avg_cost: float


class Mover(BaseModel):
    kind: str = "mover"                 # "mover" | "macro_summary"
    # regular mover
    ticker: Optional[str] = None
    now: Optional[float] = None
    prev: Optional[float] = None
    delta: Optional[float] = None
    quant_delta: Optional[float] = None
    macro_only: bool = False
    now_tier: Optional[str] = None
    prev_tier: Optional[str] = None
    driver: Optional[str] = None
    driver_delta: Optional[float] = None
    # macro_summary
    count: Optional[int] = None
    up: Optional[bool] = None
    lo: Optional[float] = None
    hi: Optional[float] = None


class MoversResponse(BaseModel):
    regime: str = "NEUTRAL"
    movers: list[Mover] = []


class ScreenerResponse(BaseModel):
    as_of: Optional[str] = None     # signal_date of the data, ISO yyyy-mm-dd
    regime: Regime
    total: int                      # rows matching the filters (pre-pagination)
    count: int                      # rows in THIS page
    offset: int
    limit: int
    rows: list[ScreenerRow]


# ── Model portfolio / track record ──────────────────────────────────────────────
class EquityPoint(BaseModel):
    d: str
    model: float
    spy: float


class ModelStats(BaseModel):
    inception: Optional[str] = None
    model_value: float = 0.0
    spy_value: float = 0.0
    model_ret: float = 0.0
    spy_ret: float = 0.0
    alpha: float = 0.0
    day_model: float = 0.0
    day_spy: float = 0.0
    basis: float = 100000.0
    n_sessions: int = 0


class ModelPosition(ScreenerRow):
    entry_date: Optional[str] = None
    entry_price: Optional[float] = None
    entry_score: Optional[float] = None
    current_price: Optional[float] = None
    ret_since_entry: Optional[float] = None


class ExitTrade(BaseModel):
    ticker: str
    sector: str = "\u2014"
    entry_date: str
    exit_date: str
    ret: float = 0.0
    reason: str = "\u2014"


class SectorCount(BaseModel):
    sector: str
    count: int


class DayMove(BaseModel):
    model_now: float = 0.0
    model_prev: float = 0.0
    model_pct: float = 0.0
    model_dollar: float = 0.0
    spy_now: float = 0.0
    spy_prev: float = 0.0
    spy_pct: float = 0.0
    spy_dollar: float = 0.0
    vs_spy_pct: float = 0.0


class ModelPortfolioResponse(BaseModel):
    inception: Optional[str] = None
    curve: list[EquityPoint] = []
    stats: Optional[ModelStats] = None
    day: Optional[DayMove] = None
    prices_as_of: Optional[str] = None
    positions: list[ModelPosition] = []
    exits: list[ExitTrade] = []
    sector_counts: list[SectorCount] = []
