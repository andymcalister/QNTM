"""Harvest from big-reach accounts (TARGET_HANDLES) MIXED with your top followers.
Manual posting via intent link. Run: python -m api.copilot.harvest"""
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


def _sync_top_followers_if_stale():
    last = store.following_synced_at()
    fresh = last is not None and _age_hours(last) < config.FOLLOW_TTL_HRS
    if fresh and store.following_count() > 0:
        return {"synced": False, "top_followers": store.following_count()}
    try:
        rows = xclient.followers(xclient.get_my_id())
    except Exception as e:
        print(f"[warn] followers sync: {e}")
        return {"synced": False, "top_followers": store.following_count(), "error": str(e)}
    rows.sort(key=lambda r: r.get("followers_count", 0), reverse=True)
    top = rows[:config.FOLLOW_TOP]
    store.replace_targets(top)
    return {"synced": True, "top_followers": len(top)}


def _gather():
    posts = []
    idmap = xclient.resolve_user_ids(config.TARGET_HANDLES)
    for uname, uid in idmap.items():
        try:
            posts.extend(xclient.timeline(str(uid), uname, config.TWEETS_PER_HANDLE))
        except Exception as e:
            print(f"[warn] timeline {uname}: {e}")
    fol = store.targets_for_harvest(config.FOLLOW_TOP)
    for t in fol:
        try:
            posts.extend(xclient.timeline(t["user_id"], t.get("username"),
                                          config.TWEETS_PER_HANDLE))
        except Exception as e:
            print(f"[warn] timeline {t.get('username')}: {e}")
    return posts, len(idmap), len(fol)


def harvest():
    sync = _sync_top_followers_if_stale()
    seen = store.existing_tweet_ids()
    recent_replies = store.recent_posted_texts()

    posts, big, fol = _gather()
    off_topic = 0
    scored = []
    for p in posts:
        if p["id"] in seen:
            continue
        text = _clean(p["text"])
        if len(text) < 15:
            continue
        rel = _relevance(text)
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

    result = {"big_accounts": big, "top_followers": fol, "synced": sync.get("synced"),
              "gathered": len(posts), "off_topic": off_topic,
              "eligible": len(scored), "queued": queued}
    print(result)
    return result


if __name__ == "__main__":
    harvest()
