"""
QNTM — Backfill signal_log.mktcap
=================================
After adding the signal_log.mktcap column (migrations/add_signal_log_mktcap.sql),
existing rows have mktcap = NULL. The hidden-gem gate is FAIL-CLOSED (keeps only
explicit 'mid'/'small'), so until a row has a cap on file it is excluded from the
gem list — which would blank the Gems page until the next full nightly run
repopulates scores.

This fills mktcap on the most recent signal_date(s) immediately, so there is no
empty-Gems window between the migration and the next `data_refresh.py --force`.

Cap source, best → fallback:
  1. fundamentals_cache (today's live bucket, parsed from the JSON `fundamentals`)
  2. universe_data.FUNDAMENTALS (static bucket — covers ~528 names)
  3. None (left NULL — correctly excluded by the fail-closed gate)

Run once locally:
    python backfill_signal_log_mktcap.py            # latest signal_date only
    python backfill_signal_log_mktcap.py --days 5   # last 5 distinct dates
    python backfill_signal_log_mktcap.py --dry-run

Requires SUPABASE_URL + SUPABASE_SERVICE_KEY (the service_role key — writes hit
RLS otherwise) in env or .streamlit/secrets.toml.
"""
import os, sys, json, argparse, logging

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("qntm.backfill.mktcap")

SIGNAL_TABLE       = "signal_log"
FUNDAMENTALS_TABLE = "fundamentals_cache"


def get_supabase():
    from supabase import create_client
    # Service key only — this script writes, and the anon key can't (RLS blocks
    # it). Env ALWAYS wins; secrets.toml only fills genuine gaps and can never
    # downgrade an env-provided service key. (The earlier version clobbered the
    # exported key while reaching into secrets.toml for the URL — that's fixed.)
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    src = "env" if key else ""
    if not url or not key:
        try:
            import toml
            s = toml.load(".streamlit/secrets.toml")
            if "default" in s and isinstance(s["default"], dict):
                s = s["default"]
            url = url or s.get("SUPABASE_URL", "")
            if not key:
                key = s.get("SUPABASE_SERVICE_KEY", "")
                if key:
                    src = "secrets.toml"
        except Exception as e:
            log.warning(f"could not read .streamlit/secrets.toml: {e}")
    if not url:
        log.error("No SUPABASE_URL (checked env + .streamlit/secrets.toml). "
                  "Run from the repo root, where .streamlit/ lives.")
        sys.exit(1)
    if not key:
        log.error("No service_role key found. The anon key can't write (RLS). "
                  "Set it:  export SUPABASE_SERVICE_KEY='eyJ...'  then re-run.")
        sys.exit(1)
    log.info(f"auth: service_role key loaded from {src}")
    return create_client(url, key)


def load_static_caps() -> dict:
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from universe_data import FUNDAMENTALS
        return {tk: (f or {}).get("mktcap") for tk, f in FUNDAMENTALS.items() if (f or {}).get("mktcap")}
    except Exception as e:
        log.warning(f"Could not load static FUNDAMENTALS: {e}")
        return {}


def load_cache_caps(sb) -> dict:
    """Latest live bucket per ticker, parsed out of fundamentals_cache.fundamentals."""
    caps = {}
    try:
        rows = sb.table(FUNDAMENTALS_TABLE).select("ticker,fundamentals,refreshed_at") \
            .order("refreshed_at", desc=True).execute().data or []
        for r in rows:
            tk = r["ticker"]
            if tk in caps:           # keep the newest only (rows are desc-sorted)
                continue
            try:
                mk = (json.loads(r["fundamentals"]) or {}).get("mktcap")
                if mk:
                    caps[tk] = mk
            except Exception:
                pass
    except Exception as e:
        log.warning(f"Could not read fundamentals_cache: {e}")
    return caps


def recent_dates(sb, n: int) -> list:
    resp = sb.table(SIGNAL_TABLE).select("signal_date") \
        .order("signal_date", desc=True).limit(2000).execute()
    seen, out = set(), []
    for r in (resp.data or []):
        d = r["signal_date"]
        if d not in seen:
            seen.add(d); out.append(d)
        if len(out) >= n:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1, help="How many recent distinct signal_dates to backfill")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sb = get_supabase()

    static_caps = load_static_caps()
    cache_caps  = load_cache_caps(sb)
    log.info(f"Cap sources — fundamentals_cache: {len(cache_caps)} · static: {len(static_caps)}")

    dates = recent_dates(sb, args.days)
    if not dates:
        log.info("No signal_log rows found.")
        return
    log.info(f"Backfilling mktcap for date(s): {dates}")

    total_set = total_null = 0
    for d in dates:
        rows = sb.table(SIGNAL_TABLE).select("ticker,mktcap").eq("signal_date", d).execute().data or []
        missing = [r for r in rows if not r.get("mktcap")]
        log.info(f"\n── {d}: {len(rows)} rows · {len(missing)} missing mktcap ──")

        updates = []
        for r in missing:
            tk = r["ticker"]
            cap = cache_caps.get(tk) or static_caps.get(tk)
            if cap:
                updates.append({"ticker": tk, "signal_date": d, "mktcap": cap})
            else:
                total_null += 1

        if args.dry_run:
            from collections import Counter
            dist = Counter(u["mktcap"] for u in updates)
            log.info(f"  [DRY] would set {len(updates)} ({dict(dist)}); "
                     f"{len(missing) - len(updates)} stay NULL (no cap on file)")
            continue

        # Disjoint-column upsert on (ticker, signal_date) — writes mktcap only,
        # leaving every other column on the existing row untouched.
        for i in range(0, len(updates), 50):
            batch = updates[i:i + 50]
            sb.table(SIGNAL_TABLE).upsert(batch, on_conflict="ticker,signal_date").execute()
            total_set += len(batch)
        log.info(f"  set {len(updates)} · {len(missing) - len(updates)} left NULL")

    log.info(f"\nDone. mktcap set on {total_set} rows"
             + (f", {total_null} had no cap on file (left NULL → excluded from gems)" if total_null else "")
             + (" (dry run — nothing written)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
