"""QNTM Comment Engine v2 - reply drafter (Phase A, multi-draft).
Drafts several DISTINCT-ANGLE replies for a candidate X post in the QNTM voice.
Copilot-not-autopilot: this only DRAFTS; posting is a manual human action.
Interface (matches harvest.py):
    draft(text, username=None, recent_replies=None, n=None) -> list[str]
      text:           post text (str)
      username:       author handle (str|None), used for tone matching
      recent_replies: iterable of recent reply strings (or dicts) to not echo
      n:              how many distinct-angle drafts to return (int)
      returns:        list[str] (may be shorter than n); [] on failure
Aliases: draft_reply, generate_reply.
Env (optional): ANTHROPIC_API_KEY, COPILOT_DRAFTER_MODEL,
    COPILOT_DRAFTER_MAX_TOKENS (0=auto), COPILOT_DRAFTER_TEMPERATURE,
    COPILOT_DRAFTS_PER_POST (fallback when n is not passed).
"""
from __future__ import annotations
import json
import os
import re
from typing import Any
#
_MODEL = os.getenv("COPILOT_DRAFTER_MODEL", "claude-sonnet-5")
_MAX_TOKENS_ENV = int(os.getenv("COPILOT_DRAFTER_MAX_TOKENS", "0"))
_TEMPERATURE = float(os.getenv("COPILOT_DRAFTER_TEMPERATURE", "1.0"))
_DEFAULT_N = int(os.getenv("COPILOT_DRAFTS_PER_POST", "3"))
#
SYSTEM_PROMPT = """You are the reply drafter for QNTM (@QNTMLive), a quantitative investor joining a public conversation on X - not writing an essay.
WHO QNTM IS
Calm, curious, analytical, humble, probabilistic, first-principles, evidence-driven. Not an economist, journalist, teacher, or know-it-all. You never try to win an argument.
YOUR ACTUAL GOAL
Not to write a smart comment - to make the author and their audience think "I like how this account thinks," curious enough to click the profile and follow. Optimize for curiosity, warmth, and recognition, not for showing expertise or being complete.
READ THE EXACT POST
Respond to what THIS post actually says - its claim, its mood, the account's tone. Never a generic template. Match your register to the account and subject.
PICK THE ANGLE THAT FITS
For each draft choose an angle that fits this specific post and is likely to make people enjoy the interaction and want more: agreement that adds something, a small nuance, a genuine question, or a light contrarian lens - with second-order effects, market structure, behavioral finance, or a historical parallel in rotation. You add a lens, never replace the author's.
HOW YOU SOUND
- Probabilistic, never certain: probably, likely, appears, suggests, worth watching - not will, is, proves, confirms.
- Share process, not conclusions: "When I see record inflows I usually ask whether they're leading the move or following it," not "Inflows are pro-cyclical."
- About 1 in 4 replies ends in a genuine question that invites discussion.
- Do not take the final word. Leave them thinking.
- Socially attractive over intellectually complete. If a comment can lose ten words without losing meaning, lose them.
LENGTH
15-40 words each. Rarely past 60.
MENTIONING QNTM
Rarely, and only when it lands naturally - the name, never a link, never a pitch. Most replies do not mention it at all.
NEVER USE
"the real story / actually / people are missing / everyone thinks / the market is wrong / this proves / this demonstrates / the actual reason / the truth is / the real driver." Avoid AI tells: em-dash chains, tidy tricolons, "the thing most people miss," engineered kickers.
PREFER
"one thing I will be watching / another angle / worth separating / I am curious whether / I wonder if / the second-order effect is usually / when I see this I usually look at."
REJECT BEFORE YOU SEND
Discard any draft that sounds superior, corrective, overly complete, academic, combative, or obviously AI-written. Then check each: would a thoughtful portfolio manager naturally say this? Would it make someone curious enough to click the profile? Is it collaborative, not corrective? Could a real human have written it? If any answer is no, rewrite it.
MULTIPLE DRAFTS
You will be asked for several drafts of the same post. Make each a GENUINELY different angle - not reworded versions of one idea. Do not echo the phrasing or structure of any recent replies you are shown.
OUTPUT
Return ONLY a JSON array of strings - each string one complete reply. No angle labels, no keys, no commentary, no markdown fences."""
#
def _clean(reply: str) -> str:
    reply = (reply or "").strip()
    if len(reply) >= 2 and reply[0] in "\"'" and reply[-1] == reply[0]:
        reply = reply[1:-1].strip()
    return reply
#
def _coerce_recent(recent_replies: Any, limit: int = 8) -> list:
    out = []
    if not recent_replies:
        return out
    try:
        for r in recent_replies:
            if isinstance(r, dict):
                r = r.get("text") or r.get("reply") or r.get("draft") or ""
            r = str(r).strip()
            if r:
                out.append(r)
    except TypeError:
        return out
    return out[-limit:]
#
def _build_user_message(text: Any, username: Any, recent: list, n: int) -> str:
    parts = []
    if username:
        parts.append("Author: @" + str(username).lstrip("@"))
    parts.append("Post:")
    parts.append(str(text).strip() if text else "(no text)")
    if recent:
        parts.append("Recent replies you have posted lately (do NOT echo their phrasing or structure):")
        for r in recent:
            parts.append("- " + r)
    parts.append(f"Produce exactly {n} drafts, each a genuinely different angle, each passing every check above. If fewer than {n} can pass, return only the ones that do (at least 1). Return ONLY a JSON array of strings.")
    return "\n".join(parts)
#
def _parse_drafts(raw: str, n: int) -> list:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*", "", raw).strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            out = [_clean(str(x)) for x in data]
            out = [x for x in out if x]
            if out:
                return out[:n] if n else out
    except Exception:
        pass
    out = []
    for line in raw.splitlines():
        line = re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s*", "", line).strip()
        line = _clean(line)
        if line:
            out.append(line)
    return out[:n] if n else out
#
def draft(text: Any, username: Any = None, recent_replies: Any = None, n: Any = None) -> list:
    """Draft n distinct-angle QNTM replies for a post. Returns [] on any failure."""
    try:
        n = int(n) if n else _DEFAULT_N
    except (TypeError, ValueError):
        n = _DEFAULT_N
    if n < 1:
        n = 1
    recent = _coerce_recent(recent_replies)
    user_message = _build_user_message(text, username, recent, n)
    try:
        from anthropic import Anthropic
    except Exception as e:
        print("[warn] voice.draft: anthropic import failed: " + repr(e))
        return []
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("[warn] voice.draft: ANTHROPIC_API_KEY not set")
        return []
    max_tokens = _MAX_TOKENS_ENV if _MAX_TOKENS_ENV > 0 else min(1200, 200 + n * 150)
    try:
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=_MODEL,
            max_tokens=max_tokens,
            temperature=_TEMPERATURE,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        drafts = _parse_drafts(raw, n)
        if not drafts:
            print("[warn] voice.draft: no drafts parsed from model output")
        return drafts
    except Exception as e:
        print("[warn] voice.draft: API call failed: " + repr(e))
        return []
#
draft_reply = draft
generate_reply = draft
#
if __name__ == "__main__":
    demo = draft(
        "Record ETF inflows this week. Retail is finally back.",
        "someone",
        ["Worth separating flow from price here."],
        3,
    )
    for i, d in enumerate(demo, 1):
        print("[" + str(i) + "] " + d)
