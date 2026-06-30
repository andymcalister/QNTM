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

    # ── Auth bridge ───────────────────────────────────────────────────────────
    # Shared HMAC secret for the cross-app token. MUST be set identically on the
    # Streamlit service (which mints) and this API (which verifies). Generate one
    # with:  python -c "import secrets; print(secrets.token_urlsafe(48))"
    BRIDGE_SECRET: str = os.getenv("QNTM_BRIDGE_SECRET", "")
    # Bridge token lifetime in seconds. Short — it only has to carry a logged-in
    # user from Streamlit into the Next app, which then holds its own session.
    BRIDGE_TOKEN_TTL: int = int(os.getenv("BRIDGE_TOKEN_TTL", "900"))  # 15 min

    # ── Service-role key (authed writes only) ─────────────────────────────────
    # Privileged key that BYPASSES RLS — required for per-user writes (watchlist,
    # later portfolio), since this app authenticates with its own JWT, not
    # Supabase Auth, so the anon role has no auth.uid() and RLS blocks its writes.
    # NEVER reaches the browser; per-user scoping is enforced in code from the
    # verified token's `sub`. Same key db.py uses. Reads still use the anon key.
    SERVICE_KEY: str = (
        os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SECRET_KEY")
        or ""
    )


settings = Settings()
