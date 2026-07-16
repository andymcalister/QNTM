"""QNTM social publisher: turn an outlook/wrap data dict into a validated X post
and publish it. Template-based (deterministic, no hallucination). Guardrails
reject bad data/text before posting. Auto-publish safe.

Call publish_social(data) after store() succeeds in market_outlook.main().
`data` needs: date, kind ('outlook'|'wrap'|'week'), regime, conviction (0-100),
pct_high (0-100), model_return, spy_return (percentages, for wraps).
"""
import logging

log = logging.getLogger("qntm_social")

BASE = "https://qntm.live"


def _utm(date: str, kind: str) -> str:
    seg = "outlook" if kind == "outlook" else "wrap"
    campaign = "outlook" if kind == "outlook" else "daywrap"
    return f"{BASE}/{seg}/{date}?utm_source=x&utm_medium=social&utm_campaign={campaign}"


def _fmt_pct(v) -> str:
    return f"{v:+.2f}%" if isinstance(v, (int, float)) else "—"


def _hook_outlook(regime: str, conv, pct_high) -> str:
    """One-line observation from the numbers (deterministic, honest)."""
    if isinstance(pct_high, (int, float)):
        if pct_high < 20:
            return f"Leadership is narrow — only {pct_high:.0f}% of the universe screens high-conviction."
        if pct_high > 35:
            return f"Breadth is wide — {pct_high:.0f}% of the universe screens high-conviction."
        return f"{pct_high:.0f}% of the universe screens high-conviction."
    return "The model's daily read across 1,400+ US stocks."


def _hook_wrap(model, spy) -> str:
    if isinstance(model, (int, float)) and isinstance(spy, (int, float)):
        diff = model - spy
        if diff >= 0:
            return f"The model beat SPY by {abs(diff):.2f}% today."
        return f"The model lagged SPY by {abs(diff):.2f}% today."
    return "Model vs SPY, marked at the close."


def generate_post(data: dict) -> str:
    kind = data.get("kind")
    date = data.get("date")
    regime = (data.get("regime") or "").upper()
    conv = data.get("conviction")
    pct_high = data.get("pct_high_conviction")
    link = _utm(date, kind)

    if kind == "outlook":
        lines = [
            "QNTM MARKET OUTLOOK",
            "",
            f"Regime: {regime}",
            f"Conviction: {conv:.1f}/100" if isinstance(conv, (int, float)) else None,
            "",
            _hook_outlook(regime, conv, pct_high),
            "",
            link,
        ]
    else:  # wrap / week
        model = data.get("model_return")
        spy = data.get("spy_return")
        lines = [
            "QNTM DAY WRAP",
            "",
            f"Model: {_fmt_pct(model)}",
            f"SPY: {_fmt_pct(spy)}",
            "",
            _hook_wrap(model, spy),
            "",
            link,
        ]
    return "\n".join(l for l in lines if l is not None).strip()


def generate_signals_reply(data: dict) -> str:
    """Build the 'flagged before today's moves' self-reply for wraps. Returns
    '' (skip the reply) for outlooks, on no signals, or on any error."""
    if data.get("kind") not in ("wrap", "week"):
        return ""
    try:
        import signal_validation as sv
        sigs = sv.get_validated_signals(as_of=data.get("date"))
        block = sv.format_wrap_block(sigs)
        if block and len(block) <= 280:
            return block
        return ""
    except Exception as e:
        log.warning("signals reply skipped: %s", e)
        return ""


# ── Guardrails ────────────────────────────────────────────────────────────────
_BAD_STRINGS = ("i'm sorry", "as an ai", "i cannot", "i don't have enough",
                "i have enough now", "none", "nan", "undefined", "null")

def validate(data: dict, text: str) -> tuple[bool, str]:
    """Return (ok, reason). Auto-reject if anything's off — fail safe."""
    kind = data.get("kind")
    date = data.get("date")
    regime = data.get("regime")
    conv = data.get("conviction")

    if kind not in ("outlook", "wrap", "week"):
        return False, f"bad kind: {kind}"
    if not date or len(str(date)) != 10:
        return False, f"bad date: {date}"
    if not regime or not isinstance(regime, str):
        return False, f"missing regime"
    if conv is None or not isinstance(conv, (int, float)) or not (0 <= conv <= 100):
        return False, f"bad conviction: {conv}"
    if kind in ("wrap", "week"):
        m, s = data.get("model_return"), data.get("spy_return")
        if not isinstance(m, (int, float)) or not isinstance(s, (int, float)):
            return False, f"wrap missing returns: model={m} spy={s}"

    if not text or len(text) < 20:
        return False, "text too short"
    if len(text) > 280:
        return False, f"text too long ({len(text)})"
    if f"/{('outlook' if kind=='outlook' else 'wrap')}/{date}" not in text:
        return False, "text missing dated URL"
    low = text.lower()
    # only check for failure strings in the body, not legit uses
    for bad in ("i'm sorry", "as an ai", "i cannot", "i don't have enough",
                "i have enough now", "undefined", "nan/100", ": none", "—/100"):
        if bad in low:
            return False, f"text contains bad string: {bad!r}"
    return True, "ok"


def publish_social(data: dict, dedup_check=None, mark_posted=None) -> dict:
    """Full pipeline: generate -> validate -> post. Never raises.
    dedup_check(date,kind)->bool (True if already posted); mark_posted(date,kind,id)."""
    date, kind = data.get("date"), data.get("kind")
    try:
        if dedup_check and dedup_check(date, kind):
            log.info("social: already posted %s/%s, skipping", kind, date)
            return {"ok": False, "skipped": "already_posted"}

        text = generate_post(data)
        ok, reason = validate(data, text)
        if not ok:
            log.error("social: validation failed (%s/%s): %s", kind, date, reason)
            _alert(f"QNTM social post SKIPPED for {kind} {date}: {reason}")
            return {"ok": False, "error": reason}

        from x_publisher import post_to_x
        res = post_to_x(text)
        if res.get("ok"):
            log.info("social: posted %s/%s id=%s", kind, date, res.get("id"))
            if mark_posted:
                try: mark_posted(date, kind, res.get("id"))
                except Exception: pass
            try:
                reply_text = generate_signals_reply(data)
                if reply_text and res.get("id"):
                    from x_publisher import post_to_x as _reply
                    r2 = _reply(reply_text, in_reply_to=res.get("id"))
                    log.info("social: signals reply %s/%s ok=%s id=%s",
                             kind, date, r2.get("ok"), r2.get("id"))
            except Exception as e:
                log.warning("signals reply post skipped: %s", e)
        else:
            _alert(f"QNTM social post FAILED for {kind} {date}: {res.get('error')}")
        return res
    except Exception as e:
        log.error("social publish crashed: %s", e)
        _alert(f"QNTM social publish crashed for {kind} {date}: {e}")
        return {"ok": False, "error": str(e)}


def _alert(msg: str):
    """Email admin on skip/failure so silent auto-publish still surfaces problems."""
    try:
        import db as _db
        admin = None
        import os
        admin = os.getenv("ADMIN_EMAIL") or os.getenv("ADMIN_EMAILS", "").split(",")[0] or "admin@qntm.live"
        _db.send_email(admin, "QNTM auto-post alert", msg)
    except Exception as e:
        log.warning("alert failed: %s", e)


if __name__ == "__main__":
    # dry-run: print generated posts for sample data (no posting)
    for d in [
        {"kind":"outlook","date":"2026-07-10","regime":"Mildly Bullish","conviction":54.6,"pct_high":16.7},
        {"kind":"wrap","date":"2026-07-10","regime":"Neutral","conviction":54.4,"pct_high":16.0,"model_return":-0.35,"spy_return":-0.24},
    ]:
        txt = generate_post(d)
        ok, reason = validate(d, txt)
        print(f"--- {d['kind']} (valid={ok}, {reason}, {len(txt)} chars) ---")
        print(txt); print()
