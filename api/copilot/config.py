import os

# Big-reach finance/investing accounts, MIXED with your top followers at harvest.
# Manual posting via intent link, so we target for AUDIENCE. Unresolvable handles
# are silently skipped. Prune/add freely.
TARGET_HANDLES = [
    "BrianFeroldi", "morganhousel", "SJosephBurns", "TheTradingGeek",
    "AlphaArchitect", "AswathDamodaran", "awealthofcs", "EricBalchunas",
    "charliebilello", "LizAnnSonders", "bespokeinvest", "SoberLook",
    "ReformedBroker", "michaelbatnick", "RampCapitalLLC", "hmeisler",
    "allstarcharts", "TheStalwart", "KoyfinCharts", "OphirGottlieb",
    "mark_dow", "TheMotleyFool", "stlouisfed", "EconguyRosie",
    "KobeissiLetter", "unusual_whales", "StockMKTNewz", "Barchart",
    "DeItaone", "biancoresearch", "GerberKawasaki", "elerianm",
    "Schuldensuehner", "WallStreetSilv", "Mayhem4Markets", "jimcramer",
    "markets", "Investingcom", "FirstSquawk",
]

KEYWORDS = ["investing", "stocks", "ETF", "market", "quant", "risk", "trading",
            "discipline", "psychology", "stock", "earnings", "portfolio",
            "valuation", "fed", "rates", "inflation", "economy", "bonds",
            "yield", "returns", "buy", "sell", "bull", "bear", "recession",
            "dividend", "growth", "value", "index", "S&P", "nasdaq", "macro"]

DAILY_POST_CAP      = int(os.getenv("COPILOT_DAILY_CAP", "12"))
MIN_ENGAGEMENT      = int(os.getenv("COPILOT_MIN_ENGAGEMENT", "50"))
MAX_POST_AGE_HRS    = int(os.getenv("COPILOT_MAX_AGE_HRS", "18"))
CANDIDATES_PER_RUN  = int(os.getenv("COPILOT_CANDIDATES", "15"))
DRAFTS_PER_POST     = int(os.getenv("COPILOT_DRAFTS", "3"))
TWEETS_PER_HANDLE   = int(os.getenv("COPILOT_TWEETS_PER_HANDLE", "6"))
REQUIRE_KEYWORD     = os.getenv("COPILOT_REQUIRE_KEYWORD", "0") == "1"

FOLLOW_SAMPLE       = int(os.getenv("COPILOT_FOLLOW_SAMPLE", "25"))
FOLLOW_TOP          = int(os.getenv("COPILOT_FOLLOW_TOP", "25"))
FOLLOW_TTL_HRS      = int(os.getenv("COPILOT_FOLLOW_TTL_HRS", "24"))
KEYWORD_SEARCH      = os.getenv("COPILOT_KEYWORD_SEARCH", "0") == "1"
KEYWORD_MAX_RESULTS = int(os.getenv("COPILOT_KEYWORD_MAX", "30"))

MODEL = os.getenv("COPILOT_MODEL", "claude-sonnet-5")
