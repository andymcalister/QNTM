"""Supabase REST access: comment_queue + copilot_following (service key, no ORM)."""
import os
import datetime as dt
import requests

_URL = os.environ["SUPABASE_URL"].rstrip("/")
_KEY = (os.environ.get("SUPABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ["SUPABASE_KEY"])
_H = {"apikey": _KEY, "Authorization": f"Bearer {_KEY}",
      "Content-Type": "application/json"}
_T = f"{_URL}/rest/v1/comment_queue"
_F = f"{_URL}/rest/v1/copilot_following"


def _utc_midnight():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT00:00:00Z")


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _parse(ts):
    if not ts:
        return None
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ---------------- comment_queue ----------------
def existing_tweet_ids():
    r = requests.get(_T, headers=_H, params={"select": "tweet_id"}, timeout=30)
    r.raise_for_status()
    return {row["tweet_id"] for row in r.json()}


def insert_candidate(row):
    h = {**_H, "Prefer": "return=representation"}
    r = requests.post(_T, headers=h, json=row, timeout=30)
    r.raise_for_status()
    return r.json()


def list_pending(limit=50):
    r = requests.get(_T, headers=_H, params={
        "status": "eq.pending", "order": "score.desc",
        "limit": str(limit), "select": "*"}, timeout=30)
    r.raise_for_status()
    return r.json()


def get(cid):
    r = requests.get(_T, headers=_H, params={
        "id": f"eq.{cid}", "select": "*"}, timeout=30)
    r.raise_for_status()
    rows = r.json()
    return rows[0] if rows else None


def update(cid, patch):
    h = {**_H, "Prefer": "return=representation"}
    r = requests.patch(_T, headers=h, params={"id": f"eq.{cid}"},
                       json=patch, timeout=30)
    r.raise_for_status()
    return r.json()


def posted_today_count():
    h = {**_H, "Prefer": "count=exact"}
    r = requests.get(_T, headers=h, params={
        "status": "eq.posted", "posted_at": f"gte.{_utc_midnight()}",
        "select": "id"}, timeout=30)
    r.raise_for_status()
    return int(r.headers.get("content-range", "*/0").split("/")[-1])


def recent_posted_texts(limit=25):
    r = requests.get(_T, headers=_H, params={
        "status": "eq.posted", "order": "posted_at.desc",
        "limit": str(limit), "select": "final_text"}, timeout=30)
    r.raise_for_status()
    return [row["final_text"] for row in r.json() if row.get("final_text")]


def queued_topics_today():
    r = requests.get(_T, headers=_H, params={
        "created_at": f"gte.{_utc_midnight()}", "select": "topic"}, timeout=30)
    r.raise_for_status()
    return {row["topic"] for row in r.json() if row.get("topic")}


# ---------------- copilot_following ----------------
def following_synced_at():
    r = requests.get(_F, headers=_H, params={
        "select": "synced_at", "order": "synced_at.desc", "limit": "1"}, timeout=30)
    r.raise_for_status()
    rows = r.json()
    return _parse(rows[0]["synced_at"]) if rows else None


def following_count():
    h = {**_H, "Prefer": "count=exact"}
    r = requests.get(_F, headers=h, params={"select": "user_id", "limit": "1"}, timeout=30)
    r.raise_for_status()
    return int(r.headers.get("content-range", "*/0").split("/")[-1])


def upsert_following(rows):
    """Merge-upsert on user_id; preserves last_harvested_at (not sent)."""
    now = now_iso()
    h = {**_H, "Prefer": "resolution=merge-duplicates,return=minimal"}
    payload = [{"user_id": x["user_id"], "username": x.get("username"),
                "synced_at": now} for x in rows]
    for i in range(0, len(payload), 500):
        r = requests.post(_F + "?on_conflict=user_id", headers=h,
                          json=payload[i:i + 500], timeout=60)
        r.raise_for_status()


def targets_for_harvest(limit):
    r = requests.get(_F, headers=_H, params={
        "select": "user_id,username",
        "order": "last_harvested_at.asc.nullsfirst",
        "limit": str(limit)}, timeout=30)
    r.raise_for_status()
    return r.json()


def mark_harvested(user_ids):
    if not user_ids:
        return
    h = {**_H, "Prefer": "return=minimal"}
    ids = ",".join(str(u) for u in user_ids)
    r = requests.patch(_F, headers=h, params={"user_id": f"in.({ids})"},
                       json={"last_harvested_at": now_iso()}, timeout=30)
    r.raise_for_status()


def replace_targets(rows):
    """Delete all target rows, then insert the given set (for top-followers refresh)."""
    h = {**_H, "Prefer": "return=minimal"}
    d = requests.delete(_F, headers=h, params={"user_id": "not.is.null"}, timeout=30)
    d.raise_for_status()
    if not rows:
        return
    now = now_iso()
    payload = [{"user_id": x["user_id"], "username": x.get("username"),
                "synced_at": now} for x in rows]
    for i in range(0, len(payload), 500):
        r = requests.post(_F, headers=h, json=payload[i:i + 500], timeout=60)
        r.raise_for_status()
