"""PostHog server-side capture. Fails soft — never raises, so analytics can't
break a request path. Reads the project key from env (the same phc_ key the
client uses). Configure POSTHOG_API_KEY (or NEXT_PUBLIC_POSTHOG_KEY) and an
optional POSTHOG_HOST on qntm-api."""
import logging
import os

_log = logging.getLogger("qntm.api.analytics")
_client = None
_tried = False


def _get():
    global _client, _tried
    if _tried:
        return _client
    _tried = True
    key = (os.getenv("POSTHOG_API_KEY") or os.getenv("POSTHOG_KEY")
           or os.getenv("NEXT_PUBLIC_POSTHOG_KEY"))
    if not key:
        _log.info("PostHog not configured — server events disabled")
        return None
    try:
        from posthog import Posthog
        _client = Posthog(project_api_key=key,
                          host=os.getenv("POSTHOG_HOST", "https://us.i.posthog.com"))
    except Exception as e:
        _log.warning("PostHog init failed: %s", e)
        _client = None
    return _client


def capture(distinct_id, event, properties=None):
    c = _get()
    if not c or not distinct_id:
        return
    try:
        c.capture(distinct_id=str(distinct_id), event=event, properties=properties or {})
    except Exception as e:
        _log.warning("PostHog capture failed (%s): %s", event, e)
