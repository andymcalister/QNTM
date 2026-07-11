"""Thin X (Twitter) v2 wrapper. OAuth 1.0a user context only (the 4 keys)."""
import os
import tweepy

_TWEET_FIELDS = ["created_at", "public_metrics", "author_id", "lang", "reply_settings"]


def _client():
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def _norm(tw, username=None):
    return {
        "id": str(tw.id),
        "text": tw.text or "",
        "author_id": str(tw.author_id) if tw.author_id else None,
        "username": username,
        "created_at": tw.created_at,
        "metrics": tw.public_metrics or {},
        "reply_settings": getattr(tw, "reply_settings", None),
    }


def get_my_id():
    return str(_client().get_me(user_auth=True).data.id)


def followers(user_id, cap_pages=6):
    """This user's followers, each with their own follower_count (for ranking)."""
    c = _client()
    out, token = [], None
    for _ in range(cap_pages):
        resp = c.get_users_followers(id=user_id, max_results=1000,
                                     pagination_token=token,
                                     user_fields=["username", "public_metrics"],
                                     user_auth=True)
        for u in (resp.data or []):
            pm = getattr(u, "public_metrics", None) or {}
            out.append({"user_id": str(u.id), "username": u.username,
                        "followers_count": pm.get("followers_count", 0)})
        token = (resp.meta or {}).get("next_token")
        if not token:
            break
    return out


def resolve_user_ids(handles):
    resp = _client().get_users(usernames=handles, user_auth=True)
    return {u.username.lower(): u.id for u in (resp.data or [])}


def timeline(user_id, username, max_results=8):
    resp = _client().get_users_tweets(
        id=user_id, max_results=max(5, min(int(max_results), 100)),
        tweet_fields=_TWEET_FIELDS, exclude=["retweets", "replies"], user_auth=True)
    return [_norm(t, username) for t in (resp.data or [])]


def search_recent(query, max_results=30):
    resp = _client().search_recent_tweets(
        query=query, max_results=max(10, min(int(max_results), 100)),
        tweet_fields=_TWEET_FIELDS, expansions=["author_id"],
        user_fields=["username"], user_auth=True)
    users = {}
    if resp.includes and resp.includes.get("users"):
        users = {u.id: u.username for u in resp.includes["users"]}
    return [_norm(t, users.get(t.author_id)) for t in (resp.data or [])]


def like(tweet_id):
    return _client().like(tweet_id, user_auth=True)


def reply(tweet_id, text):
    return _client().create_tweet(
        text=text, in_reply_to_tweet_id=tweet_id, user_auth=True)
