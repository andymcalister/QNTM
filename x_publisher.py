"""X (Twitter) publisher for QNTM. Posts to @QNTMLive via OAuth1 user context.
Requires env: X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET.
Uses tweepy (pip install tweepy). Write-only, own-account posting."""
import os, logging

log = logging.getLogger("x_publisher")


def _client():
    """Build an authenticated tweepy client, or None if creds/lib missing."""
    try:
        import tweepy
    except ImportError:
        log.error("tweepy not installed (add 'tweepy' to requirements.txt)")
        return None
    ck = os.getenv("X_API_KEY")
    cs = os.getenv("X_API_SECRET")
    at = os.getenv("X_ACCESS_TOKEN")
    ats = os.getenv("X_ACCESS_TOKEN_SECRET")
    if not all([ck, cs, at, ats]):
        log.error("X credentials missing (need X_API_KEY/SECRET, X_ACCESS_TOKEN/SECRET)")
        return None
    # v2 Client with OAuth1 user context (required to post as the account)
    return tweepy.Client(
        consumer_key=ck, consumer_secret=cs,
        access_token=at, access_token_secret=ats,
    )


def post_to_x(text: str) -> dict:
    """Post a single tweet. Returns {ok, id|error}. Never raises."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "empty text"}
    if len(text) > 280:
        return {"ok": False, "error": f"too long ({len(text)} chars)"}
    c = _client()
    if c is None:
        return {"ok": False, "error": "client unavailable (creds/lib)"}
    try:
        resp = c.create_tweet(text=text)
        tid = (resp.data or {}).get("id")
        log.info("posted to X: %s", tid)
        return {"ok": True, "id": tid}
    except Exception as e:
        log.error("X post failed: %s", e)
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    # standalone connectivity test — posts a throwaway, prints result
    import sys
    logging.basicConfig(level=logging.INFO)
    msg = sys.argv[1] if len(sys.argv) > 1 else "QNTM publisher connectivity test — please ignore."
    print(post_to_x(msg))
