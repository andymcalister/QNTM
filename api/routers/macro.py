"""
QNTM API — macro regime detail.

GET /api/macro
    Full macro overlay for the screener's regime banner: regime + indicators
    (VIX, WTI), the "what's moving the regime" driver breakdown with per-event
    headlines, and the live/source badge. Read from the same persisted overlay
    the Streamlit banner uses, so the two never disagree.
"""

from fastapi import APIRouter

from ..schemas import MacroDetail
from ..data import load_macro_detail

router = APIRouter(prefix="/api", tags=["macro"])


@router.get("/macro", response_model=MacroDetail)
def macro():
    return MacroDetail(**load_macro_detail())
