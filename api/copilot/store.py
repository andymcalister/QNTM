"""Supabase REST access for the comment_queue table (service key, no ORM)."""
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


def _utc_midnight():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT00:00:00Z")


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


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
