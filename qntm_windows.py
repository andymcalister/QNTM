"""Shared date-window + signal_log helpers.

Single source of truth for the two bug classes that recurred all week:
  1. Week windows computed differently in each generator (Mon-Fri vs a rolling
     N-day span), so the wrap and the recap disagreed.
  2. Unbounded signal_log selects silently truncating at PostgREST's 1000-row
     cap (~1000 rows PER date), returning only the newest date.

Every generator should import from here rather than rolling its own.
"""
import datetime as _dt


def week_bounds(as_of=None):
    """(monday_iso, friday_iso) for the ISO week containing as_of.
    as_of may be a 'YYYY-MM-DD' string or a date; defaults to UTC today.
    A Saturday/Sunday run still returns the just-completed week's Mon-Fri."""
    if as_of is None:
        ref = _dt.datetime.now(_dt.timezone.utc).date()
    elif isinstance(as_of, str):
        ref = _dt.date.fromisoformat(as_of[:10])
    else:
        ref = as_of
    monday = ref - _dt.timedelta(days=ref.weekday())
    friday = monday + _dt.timedelta(days=4)
    return monday.isoformat(), friday.isoformat()


def week_start_iso(as_of=None):
    """Just the Monday of as_of's ISO week (convenience for `since` filters)."""
    return week_bounds(as_of)[0]


def signal_dates_between(sb, start_iso, end_iso, table="signal_log",
                         date_col="signal_date", cap_pages=15):
    """Distinct dates present in `table` between start and end (inclusive),
    newest first. Pages past the 1000-row cap so a table with ~1000 rows per
    date does not silently return only the most recent day."""
    seen, out, page = set(), [], 0
    while page < cap_pages:
        batch = (sb.table(table).select(date_col)
                 .gte(date_col, start_iso).lte(date_col, end_iso)
                 .order(date_col, desc=True)
                 .range(page * 1000, (page + 1) * 1000 - 1).execute().data or [])
        if not batch:
            break
        for r in batch:
            d = str(r.get(date_col))[:10]
            if d and d not in seen:
                seen.add(d); out.append(d)
        if len(batch) < 1000:
            break
        page += 1
    return sorted(out, reverse=True)


def week_session_dates(sb, as_of=None, **kw):
    """Distinct signal_log dates for as_of's Mon-Fri week, newest first."""
    monday, friday = week_bounds(as_of)
    return signal_dates_between(sb, monday, friday, **kw)
