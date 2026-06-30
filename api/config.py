"""
QNTM API — configuration.

Plain os.getenv so we don't add pydantic-settings as a dependency. All values
come from the Render service's environment. The screener endpoint is read-only,
so the ANON key (RLS-protected, read-only) is all it needs — never put the
service_role key on a public read API.
"""

import os


def _csv(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings:
    # Supabase — anon key only for read endpoints (least privilege).
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")

    # CORS — the front-ends allowed to call this API. app.qntm.live is the app;
    # qntm.live is the marketing apex; localhost for local Next dev.
    ALLOWED_ORIGINS: list[str] = _csv(
        "ALLOWED_ORIGINS",
        "https://app.qntm.live,https://qntm.live,http://localhost:3000",
    )

    # How long to hold the scored universe in process before re-reading Supabase.
    # signal_log only changes a few times a day (crons), so a short TTL collapses
    # a burst of screener page-loads into one DB read without serving stale data.
    CACHE_TTL_SECONDS: int = int(os.getenv("API_CACHE_TTL", "60"))


settings = Settings()
