"""
market_outlook.py — AI-narrated daily market briefs (Outlook + Day/Week Wrap).

Modes (argv[1]):
  outlook   pre-market, FORWARD  — regime, conviction, what's scheduled, what to watch
  wrap      post-close, BACKWARD — model portfolio vs SPY, what drove it, market recap
  week      weekend roll-up      — the week vs SPY, drivers, regime shifts

It gathers QNTM's own structured data (macro regime, market conviction, model
portfolio return vs SPY, sector attribution), then asks Claude — with web search
enabled — to fold in the day's REAL market news (Fed, jobs/CPI, earnings, notable
moves) and write a concise brief. One immutable row per (outlook_date, kind) is
written to daily_outlook.

Env:
  ANTHROPIC_API_KEY   required (narration)
  ANTHROPIC_MODEL     optional (default claude-sonnet-5)
  SUPABASE_URL / key  inherited from the existing crons (via data_refresh)

Render crons (mirror the other cron services):
  python market_outlook.py outlook   # ~8:00 AM ET, Mon-Fri
  python market_outlook.py wrap      # ~4:35 PM ET, Mon-Fri
  python market_outlook.py week      # Sat AM

Data notes / knobs:
  * "Conviction" = the mean composite (0-100) across today's scored universe in
    signal_log. To use % of names at HIGH instead, swap the field in gather().
  * Model return/attribution reuse the digest's battle-tested helpers.
"""
import json
import logging
import os
import sys
from datetime import date, datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("qntm.outlook")


def _sb():
    from data_refresh import _get_supabase
    return _get_supabase()


def _market_conviction(sb, as_of=None):
    """Mean composite (0-100) across the latest scored universe. Also returns the
    count and the % of names at HIGH (>=60). Fails soft -> (None, 0, None)."""
    try:
        rows = (sb.table("signal_log").select("composite,signal_date")
                .eq("signal_date", (as_of or date.today().isoformat())).execute().data or [])
        if not rows:
            latest = (sb.table("signal_log").select("signal_date")
                      .order("signal_date", desc=True).limit(1).execute().data or [])
            if latest:
                d = latest[0]["signal_date"]
                rows = (sb.table("signal_log").select("composite,signal_date")
                        .eq("signal_date", d).execute().data or [])
        vals = [float(r["composite"]) for r in rows if r.get("composite") is not None]
        if not vals:
            return None, 0, None
        avg = sum(vals) / len(vals)
        pct_high = sum(1 for v in vals if v >= 60) / len(vals) * 100.0
        return round(avg, 1), len(vals), round(pct_high, 1)
    except Exception as e:
        log.warning("conviction aggregate failed: %s", e)
        return None, 0, None


def _daily_startend(sb, tickers, as_of=None):
    """{ticker: {start: prev_close, end: close}} from the two most recent
    signal_log dates on or before as_of (defaults to latest)."""
    if not tickers:
        return {}
    try:
        # signal_log has ~1000 rows PER date, so we CANNOT find distinct dates by
        # row-limiting — query the two most recent dates directly.
        q1 = sb.table("signal_log").select("signal_date").order("signal_date", desc=True).limit(1)
        if as_of:
            q1 = q1.lte("signal_date", as_of)
        r1 = q1.execute().data or []
        if not r1:
            return {}
        last = r1[0]["signal_date"]
        r2 = (sb.table("signal_log").select("signal_date").lt("signal_date", last)
              .order("signal_date", desc=True).limit(1).execute().data or [])
        if not r2:
            return {}
        prev = r2[0]["signal_date"]
        rows = (sb.table("signal_log").select("ticker,price,signal_date")
                .in_("ticker", tickers).in_("signal_date", [last, prev]).execute().data or [])
        by = {}
        for r in rows:
            tk = (r.get("ticker") or "").upper()
            pr = r.get("price")
            if tk and pr is not None:
                by.setdefault(tk, {})[r["signal_date"]] = float(pr)
        out = {}
        for tk, m in by.items():
            if last in m and prev in m and m[prev]:
                out[tk] = {"start": m[prev], "end": m[last]}
        return out
    except Exception as e:
        log.warning("daily prices failed: %s", e)
        return {}


def gather(sb, kind, as_of=None):
    """Defensive data pull — each piece fails soft so the brief always generates."""
    data = {"kind": kind, "date": as_of or date.today().isoformat()}

    try:
        from data_refresh import _load_macro_state
        macro = _load_macro_state() or {}
        data["regime"] = macro.get("regime")
        data["macro_events"] = macro.get("events") or macro.get("active_events") or []
    except Exception as e:
        log.warning("macro state failed: %s", e)

    conv, n, pct_high = _market_conviction(sb, data['date'])
    data["conviction"] = conv
    data["universe_scored"] = n
    data["pct_high_conviction"] = pct_high

    if kind in ("wrap", "week"):
        try:
            from weekly_digest import (model_positions, model_dollar_weighted_return,
                                       spy_daily, _sector_perf)
            positions = model_positions(sb)
            tickers = [p["ticker"] for p in positions]
            prices = _daily_startend(sb, tickers, data['date']) if tickers else {}
            mret, used = model_dollar_weighted_return(positions, prices)
            data["model_return"] = round(mret, 2) if mret is not None else None
            data["model_holdings"] = len(positions)

            spy = [x for x in spy_daily(sb) if x[0] <= data['date']]
            if len(spy) >= 2 and spy[-2][1]:
                data["spy_return"] = round((spy[-1][1] / spy[-2][1] - 1.0) * 100.0, 2)

            perf = _sector_perf(tickers, prices, min_names=1)
            data["sector_attribution"] = [{"sector": s, "avg_pct": round(p, 2), "n": c} for s, p, c in perf][:8]

            movers = []
            for tk in tickers:
                pr = prices.get(tk)
                if pr and pr.get("start"):
                    try:
                        movers.append([tk, round((pr["end"] / pr["start"] - 1.0) * 100.0, 2)])
                    except (TypeError, ZeroDivisionError):
                        pass
            movers.sort(key=lambda x: x[1])
            data["worst_holdings"] = movers[:5]
            data["best_holdings"] = list(reversed(movers[-5:]))
        except Exception as e:
            log.warning("model attribution failed: %s", e)

    return data


def build_prompt(data):
    kind = data["kind"]
    facts = json.dumps({k: v for k, v in data.items() if k != "kind"}, indent=2, default=str)
    common = (
        "You are the market analyst for QNTM, a quantitative stock-research platform. QNTM scores "
        "~1,400 US stocks daily on a five-pillar model (momentum, quality, volume, value, sentiment) "
        "with a macro-regime overlay, and runs a rules-based model portfolio benchmarked to SPY. "
        "'Conviction' is the mean 0-100 composite across the scored universe.\n\n"
        "Write for retail investors: concise, specific, factual, plain language, no hype. This is "
        "research and education, NOT investment advice — never tell anyone to buy or sell.\n\n"
        "Use web search to ground the commentary in TODAY'S real market events: Fed decisions, economic "
        "data (jobs, CPI, PCE), major earnings, and notable index/sector/single-name moves.\n\n"
        f"QNTM's own data for the {data.get('date')} session:\n{facts}\n\n"        "IMPORTANT: write about THAT date's session specifically (it may be a past date); "
        "use web search for what actually happened that day.\n\n"
    )
    if kind == "outlook":
        task = (
            "Write a PRE-MARKET MARKET OUTLOOK with these labeled sections:\n"
            "- Market Regime: QNTM's regime plus your one-line read.\n"
            "- Conviction: the number /100 and one line on what it implies.\n"
            "- On the calendar today: Fed events, data releases, notable earnings (from web search; include times if known).\n"
            "- Overnight & premarket: futures, overseas markets, notable movers (from web search).\n"
            "- What to watch: 2-3 specific things that could move the tape today.\n"
            "Under 220 words. No preamble, start at the first section."
        )
    elif kind == "week":
        task = (
            "Write a WEEK WRAP:\n"
            "- The QNTM model portfolio vs SPY this week (use the numbers).\n"
            "- What drove it: sector attribution and best/worst holdings, with the real-world reasons (web search).\n"
            "- The macro backdrop and any regime shift.\n"
            "- One line on what next week sets up (scheduled events, from web search).\n"
            "Under 240 words. No preamble."
        )
    else:
        task = (
            "Write a POST-CLOSE DAY WRAP:\n"
            "- The QNTM model portfolio vs SPY today (use model_return vs spy_return explicitly).\n"
            "- WHAT DROVE IT: be specific using sector_attribution and worst/best_holdings. If the model "
            "diverged from SPY, explain why (concentration, a sector, specific names) and use web search to "
            "add the real-world reason those names/sectors moved today.\n"
            "- Brief general-market recap (indices, plus any Fed/data/news from web search).\n"
            "- One line on what's next.\n"
            "Under 240 words. No preamble."
        )
    return common + task


def narrate(data):
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        log.error("ANTHROPIC_API_KEY not set — cannot narrate")
        return None
    try:
        import anthropic
    except ImportError:
        log.error("anthropic SDK not installed (add 'anthropic' to requirements.txt)")
        return None
    client = anthropic.Anthropic(api_key=key)
    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=1400,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}],
            messages=[{"role": "user", "content": build_prompt(data)}],
        )
        text = "\n".join(
            b.text for b in resp.content
            if getattr(b, "type", "") == "text" and getattr(b, "text", "")
        ).strip()
        return text or None
    except Exception as e:
        log.error("narration failed: %s", e)
        return None


def store(sb, data, narrative):
    conv = data.get("conviction")
    row = {
        "outlook_date": data["date"],
        "kind": data["kind"],
        "regime": data.get("regime"),
        "conviction": int(round(conv)) if conv is not None else None,
        "regime_score": conv,
        "model_return": data.get("model_return"),
        "spy_return": data.get("spy_return"),
        "attribution": json.dumps(data.get("sector_attribution") or []),
        "themes": json.dumps(data.get("macro_events") or []),
        "narrative": narrative,
    }
    try:
        # immutable: never overwrite an existing (date, kind) row
        sb.table("daily_outlook").upsert(
            row, on_conflict="outlook_date,kind", ignore_duplicates=True
        ).execute()
        log.info("stored %s / %s", data["kind"], data["date"])
        return True
    except Exception as e:
        log.error("store failed: %s", e)
        return False


def email_subscribers(sb, kind, data, narrative):
    """Email verified subscribers who opted into this brief kind. Fails soft."""
    try:
        from db import send_email
    except Exception:
        return
    try:
        rows = (sb.table("outlook_subscribers").select("email,unsub_token")
                .eq("verified", True).contains("kinds", [kind]).execute().data or [])
    except Exception as e:
        log.warning("subscriber query failed: %s", e)
        return
    if not rows:
        log.info("no verified subscribers for %s", kind)
        return
    api = os.getenv("PUBLIC_API_URL", "https://qntm-api.onrender.com")
    label = {"outlook": "Market Outlook", "wrap": "Day Wrap", "week": "Week Wrap"}.get(kind, "Market Brief")
    subj = f"QNTM {label} \u2014 {data.get('date')}"
    # naive markdown -> html for the email body
    body = narrative.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    import re as _re
    body = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body)
    import re as _re2
    _paras = []
    for para in body.split("\n\n"):
        t = _re2.sub(r"\s+([.,;:!?])", r"\1", _re2.sub(r"\s+", " ", para.replace("\n", " "))).strip()
        if t:
            _paras.append(f'<p style="margin:0 0 12px">{t}</p>')
    body = "".join(_paras)
    sent = 0
    for r in rows:
        unsub = f"{api}/api/outlook/unsubscribe?token={r.get('unsub_token')}"
        html = (
            '<div style="font-family:sans-serif;max-width:560px;margin:0 auto;color:#111;line-height:1.6;">'
            f'<h2 style="color:#111;">QNTM {label}</h2>{body}'
            '<hr style="border:none;border-top:1px solid #eee;margin:20px 0;">'
            f'<p style="font-size:12px;color:#888;">You subscribed to QNTM briefs. '
            f'<a href="{unsub}">Unsubscribe</a>. QNTM LLC \u00b7 35 Laguna Woods Drive, Laguna Niguel, CA 92677. '
            'Research/education, not investment advice.</p></div>'
        )
        try:
            send_email(r["email"], subj, html, text=narrative + f"\n\nUnsubscribe: {unsub}")
            sent += 1
        except Exception:
            pass
    log.info("emailed %d subscribers for %s", sent, kind)


def main():
    kind = (sys.argv[1] if len(sys.argv) > 1 else "outlook").lower()
    if kind not in ("outlook", "wrap", "week"):
        log.error("usage: python market_outlook.py [outlook|wrap|week] [YYYY-MM-DD]")
        sys.exit(2)
    as_of = sys.argv[2] if len(sys.argv) > 2 else None
    sb = _sb()
    if not sb:
        log.error("no supabase client")
        sys.exit(1)
    data = gather(sb, kind, as_of)
    log.info("gathered: %s", json.dumps({k: v for k, v in data.items()
             if k not in ("sector_attribution", "worst_holdings", "best_holdings")}, default=str))
    narrative = narrate(data)
    if not narrative:
        log.error("no narrative produced — not storing")
        sys.exit(1)
    print("\n===== " + kind.upper() + " =====\n" + narrative + "\n")
    store(sb, data, narrative)
    email_subscribers(sb, kind, data, narrative)


if __name__ == "__main__":
    main()
