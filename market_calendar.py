"""US equity market calendar — the single source of truth for "did the market
trade on this date?".

Why this exists: the scorer/cron runs every day, including weekends and market
holidays. On a closed day prices are re-stamped from the prior session while
scores still drift (the macro overlay recomputes), so the portfolio can execute
real trades on a day the market never opened (HST sold Sat 2026-07-18, BORR
Sat 2026-05-30). Gate anything that trades or measures sessions on this.

Holidays are computed from the NYSE rules, not hardcoded per year, so this
keeps working without maintenance. Ad-hoc closures (national days of mourning,
weather) can't be derived — add them via QNTM_EXTRA_MARKET_CLOSURES as a
comma-separated list of ISO dates.
"""
from __future__ import annotations
import os
from datetime import date, timedelta

_EXTRA = {d.strip() for d in os.getenv("QNTM_EXTRA_MARKET_CLOSURES", "").split(",") if d.strip()}


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th <weekday> of the month (Mon=0). n=-1 means the last one."""
    if n > 0:
        d = date(year, month, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    d = date(year, month, 28)
    while (d + timedelta(days=1)).month == month:
        d += timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _easter(year: int) -> date:
    """Meeus/Jones/Butcher Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    lz = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lz) // 451
    month, day = divmod(h + lz - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _observed(d: date, shift_saturday: bool = True) -> date:
    """NYSE: Sat holiday -> preceding Fri, Sun holiday -> following Mon."""
    if d.weekday() == 5 and shift_saturday:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def market_holidays(year: int) -> set:
    """Full-day NYSE closures for the given year."""
    h = set()
    # New Year's Day — NOT pulled back to Dec 31 when Jan 1 is a Saturday.
    h.add(_observed(date(year, 1, 1), shift_saturday=False))
    h.add(_nth_weekday(year, 1, 0, 3))            # MLK — 3rd Mon Jan
    h.add(_nth_weekday(year, 2, 0, 3))            # Presidents — 3rd Mon Feb
    h.add(_easter(year) - timedelta(days=2))      # Good Friday
    h.add(_nth_weekday(year, 5, 0, -1))           # Memorial — last Mon May
    h.add(_observed(date(year, 6, 19)))           # Juneteenth
    h.add(_observed(date(year, 7, 4)))            # Independence Day
    h.add(_nth_weekday(year, 9, 0, 1))            # Labor — 1st Mon Sep
    h.add(_nth_weekday(year, 11, 3, 4))           # Thanksgiving — 4th Thu Nov
    h.add(_observed(date(year, 12, 25)))          # Christmas
    return {d for d in h if d.year == year}


def is_trading_day(d=None) -> bool:
    """True only if the US equity market was open (regular session) that day."""
    if d is None:
        d = date.today()
    if isinstance(d, str):
        try:
            d = date.fromisoformat(str(d)[:10])
        except Exception:
            return True          # unparseable -> don't silently drop data
    if d.weekday() > 4:
        return False
    if d.isoformat() in _EXTRA:
        return False
    return d not in market_holidays(d.year)


def why_closed(d=None) -> str:
    if d is None:
        d = date.today()
    if isinstance(d, str):
        d = date.fromisoformat(str(d)[:10])
    if d.weekday() > 4:
        return "weekend"
    if d.isoformat() in _EXTRA:
        return "ad-hoc closure (QNTM_EXTRA_MARKET_CLOSURES)"
    if d in market_holidays(d.year):
        return "market holiday"
    return ""
