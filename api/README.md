# QNTM API — Phase 1 (screener)

Thin FastAPI layer over the existing QNTM engine. It does **not** re-implement
scoring — it imports `model_engine`, `data_refresh`, and `universe_data` and
serves their precomputed results as JSON for the Next.js front-end.

```
Next.js (Vercel, app.qntm.live)  ──fetch──►  FastAPI (this)  ──►  Supabase
                                              api.qntm.live        (unchanged)
```

## Layout

```
api/
  main.py            # app, CORS, /health, router mount
  config.py          # env-driven settings (no extra deps)
  data.py            # the ONLY Supabase touchpoint; TTL-cached universe load
  schemas.py         # Pydantic response contract
  routers/
    screener.py      # GET /api/screener
  requirements.txt   # fastapi + uvicorn (on top of the repo's root deps)
```

The `api/` folder lives **inside the QNTM repo** (next to `model_engine.py`,
`data_refresh.py`, `universe_data.py`) so those imports resolve.

## Run locally (from the repo root)

```bash
pip install -r requirements.txt          # engine deps (pandas, supabase, ...)
pip install -r api/requirements.txt       # web layer
export SUPABASE_URL="https://zqrudkoqhsjsltpefgcl.supabase.co"
export SUPABASE_ANON_KEY="…anon key…"
uvicorn api.main:app --reload --port 8000
```

Then:

```bash
curl localhost:8000/health
curl "localhost:8000/api/screener?conviction=HIGH&limit=5"
```

## Deploy (separate Render web service)

This is its **own** service, distinct from the Streamlit app — they share the
repo but run different entrypoints.

- **Build command:** `pip install -r requirements.txt && pip install -r api/requirements.txt`
- **Start command:** `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
- **Env vars:**
  - `SUPABASE_URL`
  - `SUPABASE_ANON_KEY`  ← anon/read-only; never the service_role key here
  - `ALLOWED_ORIGINS` = `https://app.qntm.live,https://qntm.live,http://localhost:3000`
  - `API_CACHE_TTL` (optional, default 60)

Later, point a subdomain (`api.qntm.live`) at this service and have the Next.js
app call it.

## GET /api/screener

Query params (all optional):

| param        | default | notes                                            |
|--------------|---------|--------------------------------------------------|
| `conviction` | `all`   | `all` \| `HIGH` \| `MODERATE` \| `LOW`           |
| `sector`     | –       | exact sector name, e.g. `Technology`             |
| `search`     | –       | ticker contains (case-insensitive)              |
| `gems_only`  | `false` | restrict to hidden gems                          |
| `sort`       | `score` | score, composite, momentum, quality, volume, value, sentiment, price, ticker |
| `order`      | `desc`  | `asc` \| `desc`                                  |
| `limit`      | `50`    | 1–500                                            |
| `offset`     | `0`     | pagination                                       |

Response: `{ as_of, regime{label,vix,event,summary}, total, count, offset, limit, rows[] }`
where each row is `{ ticker, sector, conviction, score (=adj_composite),
composite, momentum, quality, volume, value, sentiment, macro_overlay, price,
value_position, is_hidden_gem }`.

## Notes / decisions

- **Read-only, public.** Screener data isn't user-specific, so no auth and the
  anon key suffices (RLS-protected, same as the marketing hero read).
- **Sector is attached in code,** not stored in `signal_log` — so the whole
  latest-dated universe (~1,400 rows) is loaded once, cached for `API_CACHE_TTL`,
  and filtered/sorted/paginated in Python. Tiny dataset; ~1 DB read per TTL.
- **Conviction tiers** come from `model_engine.ENTRY_THRESHOLD` / `EXIT_THRESHOLD`
  (60 / 45), so labels match the app exactly.
- **Regime** comes from `data_refresh._load_macro_state()` — the same canonical
  source the app banner and marketing hero use.
- **Durable `platform_stats` fix** lands here too: once this service is in place,
  author the `daily_summary` row from `data_refresh` on each scheduled pass
  instead of the screener render path.
