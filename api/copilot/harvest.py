"""Harvest from the accounts you follow (auto-synced), draft, queue.
Run: python -m api.copilot.harvest"""
import math
import re
import datetime as dt
from . import config, xclient, voice, store


def _engagement(m):
    return (m.get("like_count", 0) + m.get("retweet_count", 0)
            + m.get("reply_count", 0) + m.get("quote_count", 0))


def _age_hours(when):
    if when is None:
        return 9999.0
    return (dt.datetime.now(dt.timezone.utc) - when).total_seconds() / 3600.0


def _relevance(text):
    t = text.lower()
    return sum(1 for k in config.KEYWORDS if k.lower() in t)


def _topic(text):
    t = text.lower()
    hits = [k for k in config.KEYWORDS if k.lower() in t]
    return hits[0] if hits else "general"


def _score(eng, age_hrs, rel):
    recency = math.exp(-age_hrs / 12.0)
    return round(eng * (0.5 + 0.5 * recency) + rel * 5, 2)


def _clean(text):
    text = re.sub(r"https?://\S+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _sync_following_if_stale():
    last = store.following_synced_at()
    fresh = last is not None and _age_hours(last) < config.FOLLOW_TTL_HRS
    if fresh and store.following_count() > 0:
        return {"synced": False, "following": store.following_count()}
    try:
        rows = xclient.following(xclient.get_my_id())
    except Exception as e:
        print(f"[warn] following sync: {e}")
        return {"synced": False, "following": store.following_count(), "error": str(e)}
    if rows:
        store.upsert_following(rows)
    return {"synced": True, "following": store.following_count()}


def _gather():
    targets = store.targets_for_harvest(config.FOLLOW_SAMPLE)
    if not targets:
        idmap = xclient.resolve_user_ids(config.TARGET_HANDLES)
        targets = [{"user_id": str(uid), "username": uname}
                   for uname, uid in idmap.items()]
    posts, harvested = [], []
    for t in targets:
        try:
            posts.extend(xclient.timeline(t["user_id"], t.get("username"),
                                          config.TWEETS_PER_HANDLE))
            harvested.append(t["user_id"])
        except Exception as e:
            print(f"[warn] timeline {t.get('username')}: {e}")
    store.mark_harvested(harvested)
    return posts


def harvest():
    sync = _sync_following_if_stale()
    seen = store.existing_tweet_ids()
    recent_replies = store.recent_posted_texts()

    posts = _gather()
    off_topic = 0
    scored = []
    for p in posts:
        if p["id"] in seen:
            continue
        text = _clean(p["text"])
        if len(text) < 15:
            continue
        rel = _relevance(text)
        # Keyword requirement is OFF by default now: posts from accounts you
        # follow are presumed relevant. Flip COPILOT_REQUIRE_KEYWORD=1 to re-enable.
        if config.REQUIRE_KEYWORD and rel == 0:
            off_topic += 1
            continue
        eng = _engagement(p["metrics"])
        if eng < config.MIN_ENGAGEMENT:
            continue
        if _age_hours(p["created_at"]) > config.MAX_POST_AGE_HRS:
            continue
        scored.append({
            "post": p, "text": text, "eng": eng,
            "topic": _topic(text),
            "score": _score(eng, _age_hours(p["created_at"]), rel),
        })
    scored.sort(key=lambda x: x["score"], reverse=True)

    # No topic-dedup: queue the top N eligible posts directly.
    queued = 0
    for c in scored:
        if queued >= config.CANDIDATES_PER_RUN:
            break
        try:
            drafts = voice.draft(c["text"], c["post"].get("username"),
                                 recent_replies, config.DRAFTS_PER_POST)
        except Exception as e:
            print(f"[warn] draft {c['post']['id']}: {e}")
            continue
        if not drafts:
            continue
        uname = c["post"].get("username") or "i"
        store.insert_candidate({
            "tweet_id": c["post"]["id"],
            "author": c["post"].get("username"),
            "post_text": c["text"],
            "post_url": f"https://x.com/{uname}/status/{c['post']['id']}",
            "engagement": c["eng"],
            "topic": c["topic"],
            "score": c["score"],
            "drafts": drafts,
            "status": "pending",
        })
        queued += 1

    result = {"following": sync.get("following"), "synced": sync.get("synced"),
              "gathered": len(posts), "off_topic": off_topic,
              "eligible": len(scored), "queued": queued}
    print(result)
    return result


if __name__ == "__main__":
    harvest()
