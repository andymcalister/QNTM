"""Public: latest Market Outlook / Day Wrap / Week Wrap for the site + app.
Reads the append-only daily_outlook ledger. No auth — same content public + in-app."""
import logging

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/outlook", tags=["outlook"])


@router.get("")
def outlook(kind: str = Query(None), limit: int = Query(20, le=90)):
    from ..data import _get_supabase_admin
    sb = _get_supabase_admin()
    if not sb:
        return {"items": []}
    try:
        q = (sb.table("daily_outlook")
             .select("outlook_date,kind,regime,conviction,model_return,spy_return,narrative,created_at")
             .order("outlook_date", desc=True).order("created_at", desc=True).limit(limit))
        if kind:
            q = q.eq("kind", kind)
        return {"items": q.execute().data or []}
    except Exception as e:
        logging.warning("outlook read failed: %s", e)
        return {"items": []}
