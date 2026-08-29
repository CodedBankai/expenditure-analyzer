# Expenditure Analyzer

Upload a bank / UPI statement (CSV or Excel) and get a spending dashboard —
category breakdown, trends over time, top vendors, recurring-charge
detection, and plain-language recommendations. No login, no database,
nothing written to disk.

## Why zero-persistence

Every uploaded file is parsed straight into memory, processed, and held only
in a per-session in-memory store keyed by a random session ID in an
httpOnly cookie. There is no database and no file ever touches the disk.
Data is dropped when:
- the user clicks **Clear my data now**,
- the session goes 30 minutes idle (background TTL sweep), or
- the process restarts.

This trades multi-instance scalability for a much smaller trust surface:
swap `app/core/session_store.py` for Redis and nothing else in the app
needs to change if horizontal scaling is ever needed.

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv\Scripts\activate on cmd/PowerShell
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000.

Run tests:

```bash
pytest tests/ -q
```

## UI

The dashboard is a single page with four tabs (Spend, Top Vendors, Week
Pattern, Recommendations) — switching tabs never navigates away, it just
toggles which section is visible. The Week Pattern tab lets you drill into
a specific month and, within it, a specific week (only offered when the
data spans more than one month), then compares that against a total
spend-by-month view. This was designed from a hand-drawn sketch:

![UI sketch](docs/ui-sketch.png)

The light theme (white / cream / light green / light blue) was built from
a separate reference image, not copied 1:1.

## How it works (pipeline)

```
Upload (CSV/Excel)
  -> Format detection & parsing      (app/core/parsing.py)
  -> Schema normalization            (app/core/parsing.py)
  -> Cleaning                        (app/core/cleaning.py)
  -> Categorization                  (app/core/categorize.py)
  -> Analysis / aggregation          (app/core/analysis.py)
  -> Recommendation engine           (app/core/analysis.py)
  -> Dashboard (Chart.js, client-side render only)
  -> Session-end purge               (app/core/session_store.py)
```

Two known column-layout profiles are auto-detected (a debit/credit bank
export and a signed-amount UPI export — see `sample_data/`), with a generic
heuristic sniffer as fallback and a manual column-mapping screen if that
sniffer isn't confident.

## Deployment

**Render — supported, via `render.yaml` (auto-detected as a Blueprint):**
connect the repo at [render.com](https://render.com), and it picks up
`render.yaml` automatically — one persistent Python web service, health
check on `/health`, no manual config needed. This works because Render
runs the app as a single long-running process, which is exactly what the
in-memory session store in `app/core/session_store.py` requires (see
"Why zero-persistence" above). Do not enable autoscaling / multiple
instances for this service — a second instance would not share the first
instance's session dict, and requests would randomly 404 (same failure
mode as running uvicorn with `--workers > 1`).

**Vercel — not supported as-is.** Vercel runs Python apps as stateless
serverless functions: there's no guarantee that two requests from the
same browser session hit the same function instance, or that the process
even stays alive between requests. Since sessions live only in an
in-memory dict, `/upload` and a later `/session/{id}/analysis` call could
land on different instances with no shared memory, producing intermittent
404s. Making this app work on Vercel would require swapping
`session_store.py` for an external store (e.g. Vercel KV / Upstash Redis)
first — the same swap already called out as the fix for horizontal
scaling in general. No `vercel.json` is included, so as not to give
Vercel something to auto-detect and deploy in a broken configuration.

## Known limits (v1, by design)

- **Single process only.** The session store is an in-memory dict; do not
  run with `--workers > 1` or it'll produce intermittent 404s (see
  design.md §6.1). Swap in Redis behind `session_store.py` for horizontal
  scaling.
- **Upload cap:** 5MB total / 10,000 rows per session.
- **Concurrent session cap:** 50 (returns 503 past that, to bound memory).
- Cross-file duplicate-row detection is not implemented (v1.1 idea).
- PDF statements, login/accounts, and real bank integrations are out of
  scope for v1 (see requirements.md §4).

## Project layout

See `app/` for the FastAPI app (`routes/` = HTTP layer, `core/` = pure,
independently unit-testable logic), `tests/` for unit tests, and
`sample_data/` for synthetic statements used in both tests and manual
demoing.
