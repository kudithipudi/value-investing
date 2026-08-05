# Graham & Doddsville newsletter dashboard

Dashboard for the [Graham & Doddsville](https://business.columbia.edu/heilbrunn/resources/graham-and-doddsville-newsletter)
newsletter from Columbia Business School. Downloads the issues' PDFs, extracts every
investment idea (formal student stock pitches + investor-mentioned positions), tracks
whether each idea worked, and surfaces the freshest high-scoring ideas.

## What it is

- Ingests the ~50-issue historical archive (Winter 2006 → Spring 2026) plus any newly
  published issue.
- Extracts ideas with an LLM (OpenRouter), split into **pitches** (formal, named challenges
  like the Pershing Square Challenge) and **positions** (investor mentions).
- Computes a **price-based return** (price at pitch vs current, via Yahoo Finance) and an
  **LLM verdict** ("worked / partial / failed / inconclusive") per idea.
- Ranks the most recent issue's ideas for **"best ideas to watch"** with an LLM score.

## Stack

Python 3.12 · FastAPI · aiosqlite/SQLite · Jinja2 · Tailwind CSS · Alpine.js ·
gunicorn + uvicorn worker · systemd · nginx (`/value-investing/` sub-path)

## Layout

```
app/
  main.py            # app factory + routers
  config.py          # pydantic-settings (.env)
  db.py              # aiosqlite access, idempotent schema
  routers/           # dashboard.py (pages), admin.py (ingest/analyze/score)
  services/          # catalog, discovery, downloader, extractor, llm, prices, analyst, ingest
  templates/         # base.html, index.html, issue.html, idea.html, admin.html
  static/            # app.css (built), js/alpine.min.js
data/                # SQLite db + downloaded PDFs (gitignored, www-data writable)
db/schema.sql        # canonical schema
scripts/backfill.py  # bulk ingest + analyze + score (resumable)
tests/               # pytest
gunicorn.conf.py
requirements.txt     # pinned
.env                 # secrets (gitignored)
```

## Run locally

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env   # set OPENROUTER_API_KEY, ROOT_PATH
./venv/bin/uvicorn app.main:app --port 8000
open http://localhost:8000/
```

## Rebuilding Tailwind CSS

Tailwind is built from the lab standalone CLI into a committed CSS file. After editing
templates or `tailwind.config.js`, rebuild:

```bash
/var/www/tailwindcss \
  -i app/static/css/input.css \
  -o app/static/css/app.css --minify
```

## Ingesting data

```bash
# Ingest + analyze everything in the catalog (resumable; skips already-done issues)
./venv/bin/python scripts/backfill.py --analyze --picks
```

Or via the UI: `/admin` → paste a direct PDF URL for a newly published issue (Columbia's
listing page blocks bots, but PDFs are downloadable), or use the backfill button.

## Deploy

- systemd unit: `value-investing.service` (runs gunicorn as `www-data`, reads `.env`).
- nginx: `location /value-investing/` strips the prefix and proxies to the unix socket.
- After changes: `sudo systemctl restart value-investing` then
  `curl -s -o /dev/null -w '%{http_code}' https://lab.kudithipudi.org/value-investing/`.

## Env vars

| Var | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | LLM extraction / verdicts / scoring |
| `ROOT_PATH` | public sub-path, used for template URLs |
| `DB_PATH` | override default `data/value-investing.db` |
| `LLM_MODEL` | OpenRouter model id (default `openai/gpt-4o-mini`) |
| `ADMIN_PASSWORD` | Login password for `/admin` (form at `/admin/login`), gating the management routes (ingest, backfill, score-latest, discover). Unset = admin locked out entirely. |
| `SESSION_SECRET` | Signs the admin login session cookie. Falls back to `ADMIN_PASSWORD` if unset, but set a dedicated random value in production — without a stable secret, every restart logs everyone out. |

## Notes

- Prices come from Yahoo Finance (`query1.finance.yahoo.com`) because stooq.com blocks
  this server. No API key needed. Yahoo already covers most non-US exchanges (LSE, HKEX,
  Tokyo, etc.) via a suffix on the symbol — the gap was resolving *which* suffix a bare
  extracted ticker needs, not exchange coverage. When a bare ticker returns no data,
  `app/services/prices.py` falls back to Yahoo's own symbol search keyed on the company
  name, preferring a real primary/US-OTC listing over thin same-day German mirror
  exchanges (which quote in EUR and aren't comparable to a USD reference price).
  It also cross-checks the returned instrument's name against the idea's company —
  a bare ticker can return real, valid-looking data for a completely unrelated company
  (e.g. "AMS" is a real NYSE American penny stock, American Shared Hospital Services,
  not Amadeus IT Group's Madrid listing), which a plain success/failure check on the
  request can't catch. If the name search can't confirm a better symbol either (e.g.
  the stored company field is an informal name Yahoo's search doesn't index), the
  original price is kept rather than discarded — there's no evidence it's wrong, and
  silently returning "no data" for a real number would be worse.
- Returns are approximate: reference price is the price stated in the pitch when given,
  else the price on the stated pitch date.
- The "worked / partial / failed / inconclusive" verdict is time-aware: it weighs the
  interim return against the thesis's *own* stated horizon (e.g. "3-year target"), not
  against how much time has passed in absolute terms. A pitch judged shortly after
  publication with a multi-year target correctly comes back "inconclusive" rather than a
  premature "failed" off a few months of normal price noise. Re-running analysis (the
  issue page's "Analyze ideas", or `scripts/backfill.py --analyze`) recomputes verdicts
  with whatever the current verdict logic is, so periodically re-running the most
  recently published issue keeps its "inconclusive" verdicts current as time passes.
- Not investment advice.
