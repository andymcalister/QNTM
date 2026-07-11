import os

# Fallback curated handles (used only if the following list hasn't synced yet).
TARGET_HANDLES = [
    "BrianFeroldi", "morganhousel", "SJosephBurns", "TheTradingGeek",
    "AlphaArchitect", "AswathDamodaran", "awealthofcs", "EricBalchunas",
    "charliebilello", "LizAnnSonders", "bespokeinvest", "SoberLook",
    "ReformedBroker", "michaelbatnick", "RampCapitalLLC", "hmeisler",
    "allstarcharts", "TheStalwart", "KoyfinCharts", "OphirGottlieb",
    "mark_dow", "TheMotleyFool", "stlouisfed", "EconguyRosie",
]

# A post must contain at least one of these to be queued (kills off-topic posts).
KEYWORDS = ["investing", "stocks", "ETF", "market", "quant",
            "risk", "trading", "discipline", "psychology"]

# --- Guardrails ---
DAILY_POST_CAP      = int(os.getenv("COPILOT_DAILY_CAP", "12"))
MIN_ENGAGEMENT      = int(os.getenv("COPILOT_MIN_ENGAGEMENT", "25"))
MAX_POST_AGE_HRS    = int(os.getenv("COPILOT_MAX_AGE_HRS", "18"))
CANDIDATES_PER_RUN  = int(os.getenv("COPILOT_CANDIDATES", "10"))
DRAFTS_PER_POST     = int(os.getenv("COPILOT_DRAFTS", "3"))
TWEETS_PER_HANDLE   = int(os.getenv("COPILOT_TWEETS_PER_HANDLE", "8"))
REQUIRE_KEYWORD     = os.getenv("COPILOT_REQUIRE_KEYWORD", "1") == "1"

# --- Following-based targeting ---
FOLLOW_SAMPLE       = int(os.getenv("COPILOT_FOLLOW_SAMPLE", "25"))   # accounts per harvest (rotating)
FOLLOW_TTL_HRS      = int(os.getenv("COPILOT_FOLLOW_TTL_HRS", "24"))  # re-sync following list after this

# Keyword search net (OFF by default). Enable: COPILOT_KEYWORD_SEARCH=1
KEYWORD_SEARCH      = os.getenv("COPILOT_KEYWORD_SEARCH", "0") == "1"
KEYWORD_MAX_RESULTS = int(os.getenv("COPILOT_KEYWORD_MAX", "30"))

MODEL = os.getenv("COPILOT_MODEL", "claude-sonnet-5")
