"""QNTM educational poster — one durable investing concept a day.

Separate from qntm_content.py (which posts live signal-grounded content). This
teaches a concept in plain language, opens with the idea, one concrete example,
short. ~1 in 4 posts bridges to how QNTM applies the concept; the rest are pure
teaching. Runs every day including weekends (no market-data dependency).

HARD FENCE: this is EDUCATIONAL, never motivational-about-returns and never
advice. The validator rejects predictions, "you should", implied return
promises, "guaranteed/always/never" about markets, and ticker recommendations.

Usage:
    python qntm_educate.py --dry-run     # print, post nothing
    python qntm_educate.py               # generate + post one concept

Kill switch: EDUCATE_ENGINE_ENABLED=0 disables posting (still logs).
"""
import os
import sys
import json
import random
import logging
import datetime as dt
from zoneinfo import ZoneInfo

log = logging.getLogger("qntm_educate")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [educate] %(levelname)s %(message)s")

ET = ZoneInfo("America/New_York")
MODEL = os.getenv("EDUCATE_MODEL", "claude-sonnet-5")
ENABLED = os.getenv("EDUCATE_ENGINE_ENABLED", "1") != "0"
MAX_LEN = 280
QNTM_BRIDGE_RATE = 0.25   # fraction of posts that tie the concept to QNTM

# Durable investing CONCEPTS — evergreen, teachable, non-predictive. Rotated so
# none repeats within RECENT_AVOID posts. This is a topic SPACE, not copy: the
# model teaches the concept freshly each time.
CONCEPTS = [
    "what a factor is (momentum, quality, value) and why one number hides several bets",
    "equal-weighting as a statement about your own overconfidence in ranking",
    "base rates: why the outside view usually beats the vivid story",
    "the difference between price and value, and why cheap isn't the same as good",
    "diversification as the one thing that lowers risk without lowering expected return",
    "why most active managers trail the index over long horizons",
    "survivorship bias: the funds and stocks that quietly disappear from the average",
    "volatility is not the same as risk; permanent loss is the risk that matters",
    "position sizing: conviction can mean 'include it', not 'bet more on it'",
    "the cost of churn — how turnover and taxes quietly erode a good strategy",
    "why a screen (a filter) and a signal (a ranked view) are different tools",
    "mean reversion vs momentum: two regimes that punish the same rule differently",
    "the base-rate of stock-picking: a few names carry most of the index's return",
    "why backtests flatter — overfitting, look-ahead, and a single lucky period",
    "sample size: why a month of results tells you almost nothing about skill",
    "correlation vs causation in market narratives — the story arrives after the move",
    "the discipline of a rules-based exit vs. the pull of 'it'll come back'",
    "why forward-looking valuation ranges beat a single price target",
    "the difference between reducing uncertainty and predicting an outcome",
    "liquidity and market cap: why the same signal behaves differently by size",
]

BANNED = [
    # AI tells
    "in reality", "the key takeaway", "it's important to remember",
    "what this means is", "this highlights", "this demonstrates", "as always",
    "unlock", "game changer", "deep dive", "supercharge", "leverage the power",
    "let that sink in", "here's the thing", "the truth is",
    # advice / prediction / promise — the compliance fence
    "you should", "you need to", "buy ", "sell ", "price target",
    "guaranteed", "will outperform", "will rise", "will fall", "is going to",
    "pays off", "patience is rewarded", "conviction is rewarded",
    "get rich", "to the moon", "can't lose", "sure thing", "trust the process",
    "always wins", "never lose", "beat the market" ,
]

VOICE = """You write ONE short educational post for QNTM, a quantitative
investing-research platform. Your job is to teach a durable investing CONCEPT in
plain language — the kind of idea that's true across decades, not a take on
today's market.

Register: clear, curious, a little dry, respectful of the reader's intelligence.
A good finance teacher, not a motivational speaker and not a guru. You are making
the reader slightly smarter, not hyping them up.

STRUCTURE (this is what makes educational posts land):
- Open with the IDEA in the first line — no windup, no "let's talk about".
- Give ONE concrete example or intuition that makes it click.
- Stop. Leave a little room for the reader to think.

HARD RULES — this is a regulated context, a research product, not advice:
- NEVER give advice or a call to action. No "you should", no "buy/sell".
- NEVER predict or promise. No "will rise", no "pays off", no "beat the market".
- NEVER imply guaranteed returns or that patience/conviction is rewarded.
- No hype, no motivational-poster lines, no gurus, no "trust the process".
- No tickers as recommendations. No hashtags, no links, no emojis.
- Teach the concept honestly, including its limits. If a concept has a catch,
  say the catch — that's what earns trust.

Length: HARD LIMIT under 240 characters including spaces and line breaks. That's
2-3 short lines. A longer post is discarded.

Return ONLY the post text. No preamble, no quotes, no markdown."""

BRIDGE = """
This post may end with ONE short line connecting the concept to how QNTM
approaches it — observational, not promotional (e.g. "It's why the model
equal-weights every position" / "It's why we publish a complete signal record,
not just the wins"). Name QNTM or "the model" at most once, no link, no pitch,
no claim of performance. If it doesn't fit naturally, leave it off."""


def _sb():
    from data_refresh import _get_supabase
    return _get_supabase()


def _recent(sb, n=8):
    try:
        return (sb.table("educate_posts").select("concept,text,created_at")
                .order("created_at", desc=True).limit(n).execute().data or [])
    except Exception:
        return []


def _record(sb, row):
    try:
        sb.table("educate_posts").insert(row).execute()
    except Exception as e:
        log.warning("educate_posts insert failed: %s", e)


def _draft(concept, bridge, recent_texts):
    import anthropic
    client = anthropic.Anthropic()
    system = VOICE + (BRIDGE if bridge else "")
    avoid = "\n".join(f"- {t}" for t in recent_texts) or "(none)"
    user = (f"Teach this concept:\n{concept}\n\n"
            f"Recent posts to avoid echoing in wording or angle:\n{avoid}")
    m = client.messages.create(model=MODEL, max_tokens=400, system=system,
                               messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in m.content
                   if getattr(b, "type", "") == "text").strip().strip('"')


def _validate(text):
    if not text:
        return False, "empty"
    if len(text) > MAX_LEN:
        return False, f"too long ({len(text)})"
    low = text.lower()
    for b in BANNED:
        if b in low:
            return False, f"banned/advice phrase: {b.strip()}"
    if "http" in low or "#" in text:
        return False, "contains link or hashtag"
    return True, "ok"


def run(dry_run=False):
    sb = _sb()
    if not sb:
        log.error("no supabase client"); return {"ok": False}

    hist = _recent(sb)
    used = {h.get("concept") for h in hist[:8]}
    recent_texts = [h.get("text", "") for h in hist[:6]]

    pool = [c for c in CONCEPTS if c not in used] or CONCEPTS[:]
    random.shuffle(pool)

    for concept in pool:
        bridge = random.random() < QNTM_BRIDGE_RATE
        try:
            text = _draft(concept, bridge, recent_texts)
        except Exception as e:
            log.warning("draft failed: %s", e); continue

        ok, why = _validate(text)
        if not ok and why.startswith("too long"):
            try:
                text = _draft(concept + " (in UNDER 200 characters; cut to the "
                              "single clearest sentence plus one example)",
                              bridge, recent_texts)
                ok, why = _validate(text)
            except Exception as e:
                log.warning("shorten retry failed: %s", e)

        row = {"concept": concept, "bridge": bridge, "text": text,
               "valid": ok, "reason": why, "posted": False,
               "created_at": dt.datetime.now(ET).isoformat()}

        if not ok:
            log.warning("validation failed (%s): %s", why, text[:80])
            _record(sb, row)
            continue

        if dry_run or not ENABLED:
            log.info("[dry-run] concept=%s bridge=%s\n%s", concept, bridge, text)
            _record(sb, row)
            return {"ok": True, "posted": False, "text": text}

        try:
            from x_publisher import post_to_x
            post_to_x(text)
            row["posted"] = True
            log.info("posted: %s", text[:80])
        except Exception as e:
            row["reason"] = f"post failed: {e}"
            log.error("post failed: %s", e)
        _record(sb, row)
        return {"ok": row["posted"], "text": text}

    log.warning("no educational post produced this run")
    return {"ok": False, "reason": "no viable concept"}


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
