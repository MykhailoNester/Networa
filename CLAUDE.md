# Networa

Self-hosted personal net-worth and asset tracker for monitoring assets, debts, cash flows, and net worth over time. A local SQLite-backed FastAPI app.

## Tech Stack

- **Backend:** Python 3.12+, FastAPI, aiosqlite (async SQLite)
- **Frontend:** Jinja2 templates, HTMX, Chart.js, custom dark-theme CSS
- **Database:** SQLite with WAL mode (`data/demo.db` default, shipped / user DB via `DB_NAME` | `DATABASE_PATH`)
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
  __init__.py           # app factory, Jinja2 setup, router registration
  config.py             # settings (db path, host, port)
  database.py           # async SQLite connection, schema init
  models.py             # Pydantic request/response schemas
  routers/              # route handlers (dashboard, assets, cashflows, snapshots, exchange_rates, sheets, import_data)
                        # CSV import format documented in docs/import-format.md
  services/             # business logic (asset_service, snapshot_service, currency_service, import_service)
templates/              # Jinja2 HTML templates
migrations/
  001_initial_schema.sql  # table definitions, indexes, seeded asset classes
scripts/
  backup.sh             # WAL-safe SQLite backup with retention
data/                   # SQLite database: data/demo.db (default, shipped) / user DB via DB_NAME|DATABASE_PATH
```

## Architecture Notes

- **Routers → Services → Database** pattern; keep business logic in `services/`, not routers.
- **No authentication** — single-user, self-hosted deployment.
- Schema is initialized automatically from `migrations/001_initial_schema.sql` on first run.
- SQLite pragmas applied at startup: `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`.
- 9 asset classes are pre-seeded (stocks, real estate, crypto, etc.).

## Database Backup

```bash
./scripts/backup.sh                    # default: ./backups, 30-day retention
./scripts/backup.sh /path/to/backups 60
```

Safe to run while the app is running (WAL mode).
