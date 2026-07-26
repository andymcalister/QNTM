"""QNTM Distribution Copilot harvest.
Scores candidates on DISTRIBUTION value (real metrics, no LLM scoring call) and
fills the queue against follower-tier quotas:
  40% 5k-50k | 30% 50k-250k | 20% small-but-overperforming | 10% very large
"""
import math
import re
import datetime as dt
from . import config, xclient, voice, store

TIERS = [("mid", 0.40), ("large", 0.30), ("small", 0.20), ("mega", 0.10)]


class CreditsDepleted(Exception):
    pass


def _is_credit_error(exc):
    txt = f"{type(exc).__name__} {exc}".lower()
    return any(k in txt for k in ("402", "credit", "429", "toomany",
                                  "rate limit", "forbidden", "403"))


def resolve_target_ids_cached():
    """Handle->id map for TARGET_HANDLES, Supabase-cached with a TTL so the
    get_users read (the 402 cost sink) fires at most once per TARGET_TTL_HRS."""
    want = [h.lower() for h in config.TARGET_HANDLES]
    try:
        synced = store.target_ids_synced_at()
    except Exception:
        synced = None
    if synced is not None and _age_hours(synced) < config.TARGET_TTL_HRS:
        cached = store.target_ids_cached()
        if all(h in cached for h in want):
            return {h: cached[h] for h in want}
    try:
        idmap = xclient.resolve_user_ids(config.TARGET_HANDLES)
    except Exception as e:
        if _is_credit_error(e):
            try:
                cached = store.target_ids_cached()
            except Exception:
                cached = {}
            if cached:
                print("[warn] target resolve hit depleted credits; using cached ids")
                return {h: cached[h] for h in want if h in cached}
            raise CreditsDepleted(str(e))
        raise
    try:
        store.upsert_target_ids(idmap)
    except Exception as e:
        print(f"[warn] target id cache write failed: {e}")
    return idmap


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


def _clean(text):
    text = re.sub(r"https?://\S+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _tier(followers, eng):
    if followers is None:
        return "mid"
    if followers >= 250000:
        return "mega"
    if followers >= 50000:
        return "large"
    if followers >= 5000:
        return "mid"
    return "small" if eng >= config.SMALL_OVERPERFORM else "skip"


def _audience(followers):
    if followers is None:
        return 5.0
    if 5000 <= followers < 50000:
        return 10.0
    if 50000 <= followers < 250000:
        return 8.0
    if 1000 <= followers < 5000:
        return 6.0
    if followers >= 250000:
        return 4.0
    return 3.0


def _visibility(age_hrs, metrics):
    freshness = 10.0 * math.exp(-age_hrs / 4.0)
    replies = metrics.get("reply_count", 0)
    saturation = 10.0 / (1.0 + replies / 25.0)
    return max(1.0, min(10.0, 0.5 * freshness + 0.5 * saturation))


def _followback(followers, metrics):
    if followers is None:
        return 5.0
    base = 10.0 if followers < 50000 else 7.0 if followers < 250000 else 3.0
    replies = metrics.get("reply_count", 0)
    likes = max(1, metrics.get("like_count", 0))
    convo = min(2.0, (replies / likes) * 10.0)
    return max(1.0, min(10.0, base + convo - 1.0))


def _dist_score(followers, age_hrs, metrics):
    a = _audience(followers)
    v = _visibility(age_hrs, metrics)
    f = _followback(followers, metrics)
    return round(a * 0.5 + v * 0.4 + f * 0.1, 2)


def _sync_followers():
    last = store.following_synced_at()
    if last is not None and _age_hours(last) < config.FOLLOW_TTL_HRS and store.following_count() > 0:
        return
    try:
        rows = xclient.followers(xclient.get_my_id())
    except Exception as e:
        print(f"[warn] followers sync: {e}")
        return
    rows.sort(key=lambda r: r.get("followers_count", 0), reverse=True)
    store.replace_targets(rows[:config.FOLLOW_TOP])


def _sync_follows():
    last = store.follows_synced_at()
    if last is not None and _age_hours(last) < config.FOLLOW_TTL_HRS and store.follows_count() > 0:
        return
    try:
        rows = xclient.following(xclient.get_my_id())
    except Exception as e:
        print(f"[warn] follows sync: {e}")
        return
    rows.sort(key=lambda r: r.get("followers_count", 0), reverse=True)
    store.replace_follows(rows[:config.FOLLOWING_TOP])


def _pull(user_id, username, posts):
    try:
        posts.extend(xclient.timeline(str(user_id), username, config.TWEETS_PER_HANDLE))
    except Exception as e:
        print(f"[warn] timeline {username}: {e}")


def _gather():
    posts = []
    idmap = resolve_target_ids_cached()
    for uname, uid in idmap.items():
        _pull(uid, uname, posts)
    for t in store.targets_for_harvest(config.FOLLOW_TOP):
        _pull(t["user_id"], t.get("username"), posts)
    for t in store.follows_for_harvest(config.FOLLOWING_TOP):
        _pull(t["user_id"], t.get("username"), posts)
    return posts


def harvest():
    _sync_followers()
    _sync_follows()
    seen = store.existing_tweet_ids()
    recent_replies = store.recent_posted_texts()

    posts = _gather()
    fc = xclient.author_follower_counts({p.get("author_id") for p in posts})

    cands = []
    for p in posts:
        if p["id"] in seen:
            continue
        text = _clean(p["text"])
        if len(text) < 15:
            continue
        if config.REQUIRE_KEYWORD and _relevance(text) == 0:
            continue
        age = _age_hours(p["created_at"])
        if age > config.MAX_POST_AGE_HRS:
            continue
        m = p["metrics"]
        eng = _engagement(m)
        if eng < config.MIN_ENGAGEMENT:
            continue
        if m.get("reply_count", 0) > config.MAX_REPLIES:
            continue
        followers = fc.get(p.get("author_id"))
        tier = _tier(followers, eng)
        if tier == "skip":
            continue
        score = _dist_score(followers, age, m)
        if score < config.MIN_DIST_SCORE:
            continue
        cands.append({"post": p, "text": text, "eng": eng, "tier": tier,
                      "followers": followers, "age": age,
                      "topic": _topic(text), "score": score})

    cands.sort(key=lambda c: c["score"], reverse=True)

    total = config.CANDIDATES_PER_RUN
    quota = {t: max(1, round(total * share)) for t, share in TIERS}
    picked, used_authors, filled = [], set(), {t: 0 for t, _ in TIERS}

    def take(c):
        a = (c["post"].get("username") or c["post"].get("author_id") or "").lower()
        if a in used_authors:
            return False
        picked.append(c)
        used_authors.add(a)
        filled[c["tier"]] += 1
        return True

    for c in cands:
        if len(picked) >= total:
            break
        if filled[c["tier"]] < quota[c["tier"]]:
            take(c)
    for c in cands:
        if len(picked) >= total:
            break
        if c not in picked:
            take(c)

    queued = 0
    for c in picked:
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
            "author_followers": c["followers"],
            "tier": c["tier"],
            "reply_count": c["post"]["metrics"].get("reply_count", 0),
            "posted_at_x": c["post"]["created_at"].isoformat() if c["post"]["created_at"] else None,
            "status": "pending",
        })
        queued += 1

    result = {"gathered": len(posts), "candidates": len(cands),
              "queued": queued, "by_tier": filled}
    print(result)
    return result


if __name__ == "__main__":
    harvest()
