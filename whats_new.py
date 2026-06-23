"""
QNTM — "What's new" changelog.
================================================================================
Curated, user-facing feature/enhancement log. The login banner shows every entry
a user hasn't seen yet (newer than their stored marker), so shipping a feature +
adding one entry here = an automatic "what's new" for every user, with no
per-release wiring.

CONVENTION (do this every time you ship something user-facing):
  Prepend ONE entry below, in the SAME change as the feature. Keep it short,
  plain, and benefit-oriented — what the user can now do, not how it was built.

DO NOT add entries that make performance or track-record claims, or that
describe the model portfolio's returns. Those are compliance-sensitive and must
go through review before any user-facing surfacing. Keep this log to plain
product features and UX improvements only.

Format (newest first):
  id    — unique, monotonically increasing; use "YYYY-MM-DD.N" (string-sortable)
  date  — human label shown in the banner
  tag   — "new" (new capability) or "improved" (enhancement)
  title — short headline
  body  — one or two plain sentences
"""

WHATS_NEW = [
    {
        "id":    "2026-06-23.2",
        "date":  "Jun 23, 2026",
        "tag":   "new",
        "title": "Add positions by dollars or shares",
        "body":  "Track fractional positions: enter a dollar amount and QNTM "
                 "computes the shares, or enter a share count directly. The price "
                 "prefills from the latest platform price and is fully editable.",
    },
    {
        "id":    "2026-06-23.1",
        "date":  "Jun 23, 2026",
        "tag":   "improved",
        "title": "Faster watchlist and portfolio",
        "body":  "Adding to your watchlist and building your portfolio no longer "
                 "reloads the whole page — changes apply instantly.",
    },
]


def latest_id() -> str:
    """The newest entry id, or '' if the log is empty."""
    return WHATS_NEW[0]["id"] if WHATS_NEW else ""


def unseen_entries(last_seen_id, limit: int = 6) -> list:
    """Entries newer than last_seen_id, newest-first, capped at `limit`.

    A falsy last_seen_id (new user, or first rollout before the marker exists)
    returns the most recent `limit` entries — so the inaugural launch and brand
    new sign-ins both see the current highlights once, then nothing until a newer
    entry ships.
    """
    last = last_seen_id or ""
    return [e for e in WHATS_NEW if str(e.get("id", "")) > last][:limit]
