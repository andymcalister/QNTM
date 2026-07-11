import os

# --- Curated accounts. Reply permission on X is PER-POST, so big accounts still
#     yield postable replies on some posts. Mix of your originals + mid-size,
#     reply-friendly finance accounts. Unresolvable handles are silently skipped. ---
TARGET_HANDLES = [
    # originals
    "BrianFeroldi", "morganhousel", "SJosephBurns", "TheTradingGeek",
    "AlphaArchitect", "AswathDamodaran", "awealthofcs", "EricBalchunas",
    # broadened set (mid-size / reply-open leaning)
    "charliebilello", "LizAnnSonders", "bespokeinvest", "SoberLook",
    "ReformedBroker", "michaelbatnick", "RampCapitalLLC", "hmeisler",
    "allstarcharts", "TheStalwart", "KoyfinCharts", "OphirGottlieb",
    "mark_dow", "TheMotleyFool", "stlouisfed", "EconguyRosie",
]

# Keyword net (OFF by default; costs more reads). Enable: COPILOT_KEYWORD_SEARCH=1
KEYWORDS = ["investing", "stocks", "ETF", "market", "quant",
            "risk", "trading", "discipline", "psychology"]

# --- Guardrails ---
DAILY_POST_CAP      = int(os.getenv("COPILOT_DAILY_CAP", "12"))
MIN_ENGAGEMENT      = int(os.getenv("COPILOT_MIN_ENGAGEMENT", "25"))
MAX_POST_AGE_HRS    = int(os.getenv("COPILOT_MAX_AGE_HRS", "18"))
CANDIDATES_PER_RUN  = int(os.getenv("COPILOT_CANDIDATES", "10"))
DRAFTS_PER_POST     = int(os.getenv("COPILOT_DRAFTS", "3"))
TWEETS_PER_HANDLE   = int(os.getenv("COPILOT_TWEETS_PER_HANDLE", "8"))
KEYWORD_SEARCH      = os.getenv("COPILOT_KEYWORD_SEARCH", "0") == "1"
KEYWORD_MAX_RESULTS = int(os.getenv("COPILOT_KEYWORD_MAX", "30"))

MODEL = os.getenv("COPILOT_MODEL", "claude-sonnet-5")
