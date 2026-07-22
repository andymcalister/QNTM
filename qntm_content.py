"""QNTM content engine — two grounded posts a day, separate from outlook/wrap.

Every post is anchored to a real number pulled live from QNTM's own data at post
time. No generic quant aphorisms: if the query returns nothing, we skip rather
than invent. Rotates post types and avoids repeating a type or ticker recently.

Usage:
    python qntm_content.py --dry-run     # print, post nothing
    python qntm_content.py               # generate + post one item
    python qntm_content.py --slot am     # force a slot label (am|pm)

Kill switch: set CONTENT_ENGINE_ENABLED=0 to disable posting entirely.
Every generated post is logged to Supabase `content_posts` whether or not it is
published, so the record is auditable.
"""
import os
import sys
import json
import random
import logging
import datetime as dt
from zoneinfo import ZoneInfo

log = logging.getLogger("qntm_content")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [content] %(levelname)s %(message)s")

ET = ZoneInfo("America/New_York")
MODEL = os.getenv("CONTENT_MODEL", "claude-sonnet-5")
ENABLED = os.getenv("CONTENT_ENGINE_ENABLED", "1") != "0"
MAX_LEN = 280

# Types rotate; each MUST be backed by a live query or it is skipped.
TYPES = ["regime", "breadth", "anatomy", "method", "build"]

BANNED = [
    "in reality", "the key takeaway", "it's important to remember",
    "what this means is", "this highlights", "this demonstrates", "as always",
    "game changer", "deep dive", "unlock", "leverage the power",
    "buy", "sell now", "price target", "guaranteed", "will outperform",
]

VOICE = """You write for QNTM, a quantitative market research platform.

QNTM does not predict. It does not recommend. It interprets, probabilistically,
and looks for underlying drivers rather than reacting to headlines. Calm,
curious, analytical, humble, first-principles. Never promotional, never CNBC,
never a hype account.

You are given REAL numbers from QNTM's own system. Build the post around them.
Never invent a number, never round away precision, never imply a recommendation.

Write as someone thinking out loud about market structure, not lecturing.
Prefer "what I find interesting is", "worth separating", "the second-order
effect", "I'd want to know whether". Probabilistic language: likely, probably,
appears, suggests, worth watching. Never: proves, confirms, will, guaranteed.

NEVER use: "In reality", "The key takeaway", "It's important to remember",
"What this means is", "This highlights", "This demonstrates", "As always".
No hashtags. No links. No emojis. No ticker recommendations, price targets,
or performance claims.

HARD LIMIT: under 240 characters total, including spaces and line breaks. That
is 2-3 short lines, not 4. A longer post is discarded outright, so brevity is not
a style preference here.

You will usually be given more numbers than belong in one post. Pick the SINGLE
most interesting one and build around it. Using every number you were handed is
the most common way these come out too long and too flat.

Leave a little room for the reader to think — don't close the topic.

Do not speculate beyond the numbers you are given. Do not invent causes,
explanations, or context that is not in the data. If a number needs context to be
meaningful and you were not given that context, say less rather than reaching.

Return ONLY the post text. No preamble, no quotes, no markdown."""

PROMPTS = {
    "regime": "Write about the current macro regime and how the overlay is "
              "shifting adjusted conviction across the universe.",
    "breadth": "Write about market breadth — how much of the universe is "
               "screening high-conviction right now, and what that suggests.",
    "anatomy": "Write about what the model sees in one name's factor profile. "
               "Describe the factors, not a recommendation. No buy/sell language.",
    "method": "Write about how one piece of the QNTM method works, grounded in "
              "the live example given. Teach the thinking, not a conclusion.",
    "build": "Write a builder's note about making a quantitative research "
             "platform. You are given rough raw material from the founder and an "
             "angle to take on it. Do not restate the raw material - start from "
             "it and go somewhere it did not already go. First person, honest, "
             "specific, no motivational-poster register.",
}


# ── data ────────────────────────────────────────────────────────────────────
def _sb():
    from data_refresh import _get_supabase
    return _get_supabase()


def _today_et():
    return dt.datetime.now(ET).strftime("%Y-%m-%d")


def _latest_signal_date(sb):
    r = (sb.table("signal_log").select("signal_date")
         .order("signal_date", desc=True).limit(1).execute().data)
    return r[0]["signal_date"] if r else None


def _universe(sb, d):
    rows, page = [], 0
    while page < 4:
        b = (sb.table("signal_log")
             .select("ticker,composite,adj_composite,macro_overlay,signal,"
                     "momentum,quality,value,sentiment,value_position")
             .eq("signal_date", d).range(page * 1000, (page + 1) * 1000 - 1)
             .execute().data or [])
        rows.extend(b)
        if len(b) < 1000:
            break
        page += 1
    return rows


def _facts_regime(sb, d, rows):
    o = (sb.table("daily_outlook").select("regime,regime_score")
         .eq("outlook_date", d).eq("kind", "outlook").limit(1).execute().data)
    ov = [float(r["macro_overlay"]) for r in rows
          if r.get("macro_overlay") is not None]
    if not ov or not o:
        return None
    gaps = [float(r["composite"]) - float(r["adj_composite"]) for r in rows
            if r.get("composite") is not None and r.get("adj_composite") is not None]
    distinct = {round(x, 3) for x in ov}
    return {
        "regime": o[0].get("regime"),
        "conviction": o[0].get("regime_score"),
        "universe": len(rows),
        "avg_overlay": round(sum(ov) / len(ov), 3),
        "overlay_min": round(min(ov), 3),
        "overlay_max": round(max(ov), 3),
        "overlay_distinct_values": len(distinct),
        "avg_points_removed": round(sum(gaps) / len(gaps), 2) if gaps else None,
        "max_points_removed": round(max(gaps), 2) if gaps else None,
        "note": "The overlay is applied per sector, so the count of distinct "
                "values shows how differentiated the macro tilt is. Points "
                "removed = composite minus adjusted score. A small overlay "
                "mechanically produces small point moves - never present that "
                "as surprising or as a finding; it is arithmetic, not signal. "
                "Only comment on dispersion using the min/max/distinct values "
                "given.",
    }


def _is_high(adj):
    """Canonical HIGH test - defers to conviction.py so the engine can never
    disagree with the screener. The bands key off the ROUNDED adjusted score,
    so a raw >= 65 test undercounts everything sitting at 64.5-64.99."""
    if adj is None:
        return False
    try:
        from conviction import conviction_label
        return conviction_label(float(adj)) == "HIGH"
    except Exception:
        return round(float(adj)) >= 65


def _day_bands(sb, d):
    """(high, total) for one session, using the canonical bands."""
    rows, page = [], 0
    while page < 4:
        b = (sb.table("signal_log").select("adj_composite")
             .eq("signal_date", d).range(page * 1000, (page + 1) * 1000 - 1)
             .execute().data or [])
        rows.extend(b)
        if len(b) < 1000:
            break
        page += 1
    scored = [r["adj_composite"] for r in rows if r.get("adj_composite") is not None]
    return sum(1 for a in scored if _is_high(a)), len(scored)


def _baseline(sb, d, days=10, lookback=18):
    """Trailing high-conviction share, so today's reading has context."""
    base = dt.date.fromisoformat(d)
    vals = []
    for i in range(1, lookback + 1):
        dd = (base - dt.timedelta(days=i)).isoformat()
        hi, total = _day_bands(sb, dd)
        if total < 100:
            continue
        vals.append(100.0 * hi / total)
        if len(vals) >= days:
            break
    if not vals:
        return None
    return round(sum(vals) / len(vals), 1)


def _facts_breadth(sb, d, rows):
    scored = [r for r in rows if r.get("adj_composite") is not None]
    if len(scored) < 100:
        return None
    hi = [r for r in scored if _is_high(r.get("adj_composite"))]
    high_pct = round(100 * len(hi) / len(scored), 1)
    avg = _baseline(sb, d)
    if avg is None:
        return None
    return {"universe": len(scored),
            "high_conviction": len(hi),
            "high_pct": high_pct,
            "trailing_10session_avg_high_pct": avg,
            "vs_trailing": round(high_pct - avg, 1),
            "note": "high-conviction means adjusted score >= 65. Compare today "
                    "to the trailing average; do NOT describe the universe "
                    "against the exit threshold, which applies only to holdings."}


def _facts_anatomy(sb, d, rows, avoid):
    held = [r["ticker"] for r in
            (sb.table("model_portfolio_positions").select("ticker")
             .is_("exit_date", "null").execute().data or [])]
    pool = [r for r in rows if r["ticker"] in held
            and r["ticker"] not in avoid
            and r.get("adj_composite") is not None]
    if not pool:
        return None
    r = max(pool, key=lambda x: float(x["adj_composite"]))
    return {"ticker": r["ticker"], "adj_composite": r.get("adj_composite"),
            "composite": r.get("composite"), "momentum": r.get("momentum"),
            "quality": r.get("quality"), "value": r.get("value"),
            "sentiment": r.get("sentiment"),
            "value_position": r.get("value_position")}


def _held_rows(sb, rows):
    held = {r["ticker"] for r in
            (sb.table("model_portfolio_positions").select("ticker")
             .is_("exit_date", "null").execute().data or [])}
    return [r for r in rows if r["ticker"] in held
            and r.get("adj_composite") is not None]


def _facts_method(sb, d, rows):
    """Each topic carries its OWN matching numbers. A random topic paired with an
    unrelated stat forces a bogus connection in the copy."""
    hrows = _held_rows(sb, rows)
    if len(hrows) < 5:
        return None
    topic = random.choice(["exit_discipline", "equal_weighting", "valuation_band"])

    if topic == "exit_discipline":
        near = [r for r in hrows if 55 < round(float(r["adj_composite"])) <= 58]
        return {"topic": "exit discipline - a holding is sold when its adjusted "
                         "score drops to 55 or under",
                "holdings": len(hrows),
                "holdings_within_3pts_of_exit": len(near),
                "lowest_held_score": round(
                    min(float(r["adj_composite"]) for r in hrows), 1),
                "note": "The exit line applies ONLY to current holdings, never to "
                        "the wider universe - most names sit below it as a matter "
                        "of course. Never describe the universe against it. "
                        "lowest_held_score is the minimum across ALL holdings, "
                        "not the minimum of that cluster - never present the two "
                        "as one figure."}

    if topic == "equal_weighting":
        return {"topic": "equal weighting - every position enters at the same size",
                "holdings": len(hrows),
                "target_book": 50,
                "highest_held_score": round(
                    max(float(r["adj_composite"]) for r in hrows), 1),
                "lowest_held_score": round(
                    min(float(r["adj_composite"]) for r in hrows), 1),
                "note": "Conviction shows up as presence in the book, not as a "
                        "bigger position. Do not imply position sizing by score."}

    vp = [float(r["value_position"]) for r in hrows
          if r.get("value_position") is not None]
    if not vp:
        return None
    return {"topic": "the QNTM valuation band - where price sits inside a stock's "
                     "own valuation range",
            "holdings": len(hrows),
            "held_with_band": len(vp),
            "at_or_below_floor": sum(1 for x in vp if x <= 0),
            "avg_value_position": round(sum(vp) / len(vp), 1),
            "note": "value_position runs 0-100; 0 means at or below the band "
                    "floor. This is descriptive context, never a price target or "
                    "a recommendation."}


BUILD_ANGLES = [
    "the tradeoff you accepted, and what it actually cost",
    "what you believed at the start that turned out to be wrong",
    "the specific decision point, and why you went the way you did",
    "what you would tell someone about to make the same call",
    "the second-order consequence nobody warns you about",
    "why the obvious answer was the wrong one here",
    "the part that was boring but mattered more than the interesting part",
]


def _facts_build(sb, d, rows):
    """Seeds are raw material, not copy. Pair two and rotate the angle so the
    same handful of notes produce genuinely different posts over time."""
    seeds = json.loads(os.getenv("CONTENT_BUILD_SEEDS", "[]") or "[]")
    if not seeds:
        return None
    pool = list(seeds)
    random.shuffle(pool)
    prev = (sb.table("content_posts").select("text")
            .eq("post_type", "build").order("created_at", desc=True)
            .limit(6).execute().data or [])
    hrows = _held_rows(sb, rows)
    return {
        "raw_material": pool[0],
        "second_thread": pool[1] if len(pool) > 1 else None,
        "angle": random.choice(BUILD_ANGLES),
        "live_context": {"universe_size": len(rows), "holdings": len(hrows)},
        "avoid_echoing_these_recent_build_posts": [x.get("text") for x in prev],
        "note": "raw_material and second_thread are rough private notes from the "
                "founder. They are NOT copy to restate or paraphrase back. Find "
                "one specific idea inside them and write something new from the "
                "given angle - a thought the notes imply but do not say. If the "
                "two threads connect, use the connection; if not, ignore the "
                "second. live_context numbers are optional - include one only if "
                "it genuinely earns its place, never force it in.",
    }


# ── history / storage ───────────────────────────────────────────────────────
def _recent(sb, n=8):
    return (sb.table("content_posts")
            .select("post_type,ticker,text,created_at")
            .order("created_at", desc=True).limit(n).execute().data or [])


def _record(sb, row):
    try:
        sb.table("content_posts").insert(row).execute()
    except Exception as e:
        log.warning("content_posts insert failed: %s", e)


# ── generation ──────────────────────────────────────────────────────────────
def _draft(post_type, facts, recent_texts, extra=""):
    import anthropic
    client = anthropic.Anthropic()
    avoid = "\n".join(f"- {t}" for t in recent_texts) or "(none)"
    user = (f"{PROMPTS[post_type]}\n\nREAL DATA (use these exact numbers):\n"
            f"{json.dumps(facts, indent=2)}\n\n"
            f"Recent posts to avoid echoing:\n{avoid}")
    if extra:
        user += f"\n\n{extra}"
    m = client.messages.create(model=MODEL, max_tokens=400, system=VOICE,
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
            return False, f"banned phrase: {b}"
    if "http" in low or "#" in text:
        return False, "contains link or hashtag"
    return True, "ok"


def run(dry_run=False, slot=None):
    sb = _sb()
    if not sb:
        log.error("no supabase client"); return {"ok": False}

    d = _latest_signal_date(sb)
    if not d:
        log.error("no signal_log data"); return {"ok": False}
    rows = _universe(sb, d)
    log.info("universe %d rows @ %s", len(rows), d)

    hist = _recent(sb)
    used_types = [h.get("post_type") for h in hist[:3]]
    used_tk = {h.get("ticker") for h in hist[:6] if h.get("ticker")}
    recent_texts = [h.get("text", "") for h in hist[:6]]

    order = [t for t in TYPES if t not in used_types] or TYPES[:]
    random.shuffle(order)

    for post_type in order:
        if post_type == "regime":
            facts = _facts_regime(sb, d, rows)
        elif post_type == "breadth":
            facts = _facts_breadth(sb, d, rows)
        elif post_type == "anatomy":
            facts = _facts_anatomy(sb, d, rows, used_tk)
        elif post_type == "method":
            facts = _facts_method(sb, d, rows)
        else:
            facts = _facts_build(sb, d, rows)
        if not facts:
            log.info("no facts for %s — skipping", post_type)
            continue

        try:
            text = _draft(post_type, facts, recent_texts)
        except Exception as e:
            log.warning("draft failed for %s: %s", post_type, e)
            continue

        ok, why = _validate(text)
        if not ok and why.startswith("too long"):
            # shorten_retry: one tightened attempt before abandoning this type,
            # otherwise a long draft can leave a scheduled slot with no post.
            log.info("retrying %s shorter (%s)", post_type, why)
            try:
                text = _draft(post_type, facts, recent_texts,
                              extra="Your previous attempt was too long. Rewrite it "
                                    "in UNDER 220 characters total. Drop the least "
                                    "essential line entirely rather than trimming "
                                    "words from every line.")
                ok, why = _validate(text)
            except Exception as e:
                log.warning("shorten retry failed: %s", e)

        row = {"post_type": post_type, "slot": slot,
               "ticker": facts.get("ticker"), "facts": json.dumps(facts),
               "text": text, "valid": ok, "reason": why,
               "posted": False, "signal_date": d}

        if not ok:
            log.warning("validation failed (%s): %s", why, text[:80])
            _record(sb, row)
            continue

        if dry_run or not ENABLED:
            log.info("[dry-run] %s\n%s", post_type, text)
            _record(sb, row)
            return {"ok": True, "posted": False, "type": post_type, "text": text}

        try:
            from x_publisher import post_to_x
            post_to_x(text)
            row["posted"] = True
            log.info("posted %s: %s", post_type, text[:80])
        except Exception as e:
            row["reason"] = f"post failed: {e}"
            log.error("post failed: %s", e)
        _record(sb, row)
        return {"ok": row["posted"], "type": post_type, "text": text}

    log.warning("no post produced this run")
    return {"ok": False, "reason": "no viable post type"}


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv,
        slot=(sys.argv[sys.argv.index("--slot") + 1]
              if "--slot" in sys.argv else None))
