"""Harvest -> score -> dedup -> draft -> queue. Run: python -m api.copilot.harvest"""
import math
import re
import datetime as dt
from . import config, xclient, voice, store


def _engagement(m):
    return (m.get("like_count", 0) + m.get("retweet_count", 0)
            + m.get("reply_count", 0) + m.get("quote_count", 0))


def _age_hours(created_at):
    if created_at is None:
        return 9999.0
    now = dt.datetime.now(dt.timezone.utc)
    return (now - created_at).total_seconds() / 3600.0


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


def _gather():
    posts = []
    id_map = xclient.resolve_user_ids(config.TARGET_HANDLES)
    for uname, uid in id_map.items():
        try:
            posts.extend(xclient.timeline(uid, uname, config.TWEETS_PER_HANDLE))
        except Exception as e:
            print(f"[warn] timeline {uname}: {e}")
    if config.KEYWORD_SEARCH:
        q = "(" + " OR ".join(config.KEYWORDS) + ") lang:en -is:retweet -is:reply"
        try:
            posts.extend(xclient.search_recent(q, config.KEYWORD_MAX_RESULTS))
        except Exception as e:
            print(f"[warn] search: {e}")
    return posts


def harvest():
    seen = store.existing_tweet_ids()
    used_topics = set(store.queued_topics_today())
    recent_replies = store.recent_posted_texts()

    posts = _gather()
    scored = []
    for p in posts:
        if p["id"] in seen:
            continue
        eng = _engagement(p["metrics"])
        if eng < config.MIN_ENGAGEMENT:
            continue
        age = _age_hours(p["created_at"])
        if age > config.MAX_POST_AGE_HRS:
            continue
        text = _clean(p["text"])
        if len(text) < 15:
            continue
        rel = _relevance(text)
        scored.append({
            "post": p, "text": text, "eng": eng,
            "topic": _topic(text), "score": _score(eng, age, rel),
        })
    scored.sort(key=lambda x: x["score"], reverse=True)

    queued = 0
    for c in scored:
        if queued >= config.CANDIDATES_PER_RUN:
            break
        if c["topic"] != "general" and c["topic"] in used_topics:
            continue
        try:
            drafts = voice.draft(c["text"], c["post"]["username"],
                                 recent_replies, config.DRAFTS_PER_POST)
        except Exception as e:
            print(f"[warn] draft {c['post']['id']}: {e}")
            continue
        if not drafts:
            continue
        uname = c["post"]["username"] or "i"
        store.insert_candidate({
            "tweet_id": c["post"]["id"],
            "author": c["post"]["username"],
            "post_text": c["text"],
            "post_url": f"https://x.com/{uname}/status/{c['post']['id']}",
            "engagement": c["eng"],
            "topic": c["topic"],
            "score": c["score"],
            "drafts": drafts,
            "status": "pending",
        })
        used_topics.add(c["topic"])
        queued += 1

    result = {"gathered": len(posts), "eligible": len(scored), "queued": queued}
    print(result)
    return result


if __name__ == "__main__":
    harvest()
