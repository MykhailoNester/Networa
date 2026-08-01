# Networa

Self-hosted personal net-worth and asset tracker for monitoring assets, debts, cash flows, and net worth over time. A local SQLite-backed FastAPI app.

## Tech Stack

- **Backend:** Python 3.12+, FastAPI, aiosqlite (async SQLite)
- **Frontend:** Jinja2 templates, HTMX, Chart.js, custom dark-theme CSS
- **Database:** SQLite with WAL mode. Default `data/networa.db` (gitignored, created and sample-seeded on first run). `data/demo.db` is the committed screenshot dataset — never put real data in it. Override with `DB_NAME` | `DATABASE_PATH`.
- **Deployment:** Docker / Docker Compose

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py          # runs on http://localhost:8000 with hot reload
```

## Docker

```bash
docker compose up -d    # build and start
docker compose down     # stop
```

Database is persisted to `./data` volume.

## Project Structure

```
app/
  __init__.py           # app factory (lifespan), Jinja2 setup, router registration
  config.py             # settings (db path, host, port, allowed hosts, sample seeding)
  database.py           # async SQLite connection + schema init
  schema.sql            # canonical database schema — single source of truth (no migrations dir)
  models.py             # Pydantic request/response schemas
  forms.py              # typed form-field helpers
  html.py               # escaping helpers for router-built HTML fragments
  security.py           # same-origin + Host enforcement middleware
  routers/              # route handlers (dashboard, assets, debts, cashflows, snapshots, exchange_rates,
                        #   sheets, import_data, settings)
                        # CSV import format documented in docs/import-format.md
  services/             # business logic (asset_service, snapshot_service, currency_service, import_service,
                        #   cashflow_service, market_service, settings_service,
                        #   sample_data — first-run seeding of an empty DB)
templates/              # Jinja2 HTML templates
scripts/
  seed_demo.py          # (re)build the synthetic data/demo.db
  backup.sh             # WAL-safe SQLite backup with retention
data/                   # SQLite databases: networa.db (default, gitignored) + demo.db (committed sample)
```

## Architecture Notes

- **Routers → Services → Database** pattern; keep business logic in `services/`, not routers.
- **Assets and debts share one table.** `assets.category` is `'asset'` or `'debt'`, and a debt's value is
  stored as a **positive** number. Net worth is therefore `assets − debts`, and every aggregate in
  `snapshot_service` that means *net worth* signs debt rows with −1 (see the `_SIGNED` constant). A debt's
  contribution to a period is the **negation** of its value change, so paying a mortgage down reads as a
  gain and the contributor list still sums to the period's net-worth change. Aggregates that describe asset
  *composition* — allocation by class/sheet, investable tiers, top holdings — stay `category = 'asset'` on
  purpose and are denominated by **gross assets**, never by net worth. The `/debts` page is a thin view over
  `asset_service`; creating and editing a debt reuses the assets router's handlers.
- **No authentication** — single-user, self-hosted deployment. Because of that, `app/security.py` rejects state-changing requests a browser reports as cross-origin, and restricts the `Host` header to block DNS rebinding. The host rule turns on *names*, not addresses: every IP literal and `localhost` are always allowed (they cannot be repointed), while other hostnames need `ALLOWED_HOSTS`. Non-browser clients are unaffected.
- **Escaping is manual in router-built HTML.** Some HTMX fragments are assembled as f-strings, where Jinja's autoescaping does not apply. Every interpolated DB value must go through `app.html.e()`, and any JSON embedded in a `<script>` block through `app.html.json_for_script()`. Prefer adding new fragments as Jinja partials under `templates/` instead.
- No third-party requests to render the UI: fonts, HTMX and Chart.js are all vendored under `app/static/vendor/`. Don't reintroduce a CDN link.
- **Every chart goes through `app/static/js/charts.js` (`window.NetworaCharts`).** It owns the
  hover behaviour (whole-x-position tooltips), the per-record point markers, the dark tooltip
  theme and money formatting, so charts stay consistent instead of each one re-deciding. Chart
  data is always converted to the display currency before it reaches Chart.js — the server
  sends USD.
- Schema is initialized automatically from the single `app/schema.sql` on first run (idempotent; there is no migrations directory). Note this cannot add a column to an existing table — adding one needs a real migration step.
- SQLite pragmas applied at startup: `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`.
- 9 asset classes are pre-seeded (stocks, real estate, crypto, etc.).

## Database Backup

```bash
./scripts/backup.sh                    # default: ./backups, 30-day retention
./scripts/backup.sh /path/to/backups 60
```

Safe to run while the app is running (WAL mode).
