"""Admin-only business metrics. Gated by ADMIN_EMAILS (comma-separated env
allowlist, checked against the caller's session email)."""
import os

from fastapi import APIRouter, Depends, HTTPException

from .auth import current_user
from ..data import get_admin_stats

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _is_admin(user: dict) -> bool:
    _raw = os.getenv("ADMIN_EMAILS") or os.getenv("ADMIN_EMAIL") or ""
    allow = [e.strip().lower() for e in _raw.split(",") if e.strip()]
    email = (user.get("email") or "").lower()
    return bool(email) and email in allow


@router.get("/stats")
def stats(user: dict = Depends(current_user)):
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Not authorized")
    return get_admin_stats()
