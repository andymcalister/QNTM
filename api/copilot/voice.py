"""Draft reply options in the QNTM founder voice using the Anthropic API."""
import json
import anthropic
from . import config

_SYS = """You draft reply comments for @QNTMLive on X, in the founder's own voice.

The throughline of every reply (never stated as slogans, just felt):
- Process over prediction.
- Better decisions over bigger wins.
- Patience is a position.
- Conviction matters, but as probability, not certainty.
- Discipline compounds.

Voice for REPLIES: loose, conversational, human. Someone who actually read the post
and is adding ONE genuine thought. Not a brand account. Not a motivational poster.

Hard rules (compliance + authenticity):
- No ticker symbols. No buy/sell calls. No performance or return claims. No price targets, no forecasts.
- Don't pitch QNTM. No links. No hashtags.
- At most one emoji, and only if the post itself is casual and one fits naturally. Usually zero.
- Short: one or two sentences. Sound like a person typing on their phone.
- React to the SPECIFIC point in the post, not the topic in general.
- Do NOT reuse phrasing from the 'recent replies to avoid echoing' list. Vary sentence shape.
- The three options should differ in angle, not just wording. If a post has nothing worth
  adding, one option may be a short, honest agreement rather than a manufactured insight.

Return ONLY a JSON array of exactly {n} strings. No preamble, no markdown, no keys."""


def draft(post_text, author, recent_replies, n=3):
    client = anthropic.Anthropic()
    avoid = "\n".join(f"- {r}" for r in (recent_replies or [])[-20:]) or "(none yet)"
    user = (f'Post by @{author or "unknown"}:\n"""\n{post_text}\n"""\n\n'
            f"Recent replies to avoid echoing:\n{avoid}\n\n"
            f"Draft {n} distinct reply options.")
    msg = client.messages.create(
        model=config.MODEL, max_tokens=700,
        system=_SYS.format(n=n),
        messages=[{"role": "user", "content": user}])
    txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    txt = txt.replace("```json", "").replace("```", "").strip()
    try:
        arr = json.loads(txt)
        out = [str(x).strip() for x in arr if str(x).strip()]
    except Exception:
        out = [l.strip("-*• ").strip().strip('"') for l in txt.splitlines() if l.strip()]
    return out[:n]
