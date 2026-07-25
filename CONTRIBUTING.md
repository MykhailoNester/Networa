# Contributing to Networa

Thanks for your interest in contributing! This is a self-hosted personal
finance app built with FastAPI, HTMX, Jinja2, and SQLite. Please also read the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Development setup

Requires Python 3.12+ (`python3 -V` — macOS ships an older 3.9, which cannot
install the pinned dependencies).

```bash
python3 -m venv .venv                    # python3: most systems have no `python`
source .venv/bin/activate                # after this, `python`/`pip` are the venv's
pip install -r requirements.txt
pip install -r requirements-dev.txt      # pinned ruff, mypy, pytest — same as CI

python main.py                           # http://localhost:8000
```

By default the app creates and uses `data/networa.db`, seeded with a small
sample portfolio on first run. To work against the richer committed demo
dataset instead:

```bash
python scripts/seed_demo.py         # (re)build data/demo.db, if needed
DB_NAME=demo.db python main.py      # the DB_NAME is required — it is not the default
```

Never point tests or development at a real personal database — use the demo DB
or a throwaway copy (`DATABASE_PATH=/tmp/scratch.db`).

## The check gate

Before opening a PR, run the same gate CI runs:

```bash
make check-all
```

That is equivalent to:

```bash
ruff format --check .        # formatting
ruff check .                 # lint
mypy app/                    # type check (must report no issues)
pytest                       # tests
```

`make format` auto-formats; `ruff check --fix .` auto-fixes what it can.
The `main` branch is expected to be lint-clean, `mypy`-clean, and green.

## Architecture & conventions

- **Layering:** `routers/` (HTTP) → `services/` (business logic) → `database.py`
  (data access). Keep business logic in `services/`, not in routers.
- **Schema:** the entire database schema lives in a single **`app/schema.sql`**,
  applied idempotently on startup — there is **no** migrations directory. To
  change the schema, edit `app/schema.sql` (keep every statement
  `IF NOT EXISTS` / `INSERT OR IGNORE`-safe) and re-seed the demo DB.
- **Forms:** parse request forms with the typed helpers in `app/forms.py`
  (`get_str`, `get_float`, …) rather than coercing `request.form()` values
  inline.
- **Templates:** Jinja2 + HTMX; prefer server-rendered partials over
  client-side JavaScript. Vendored JS and fonts live in `app/static/vendor/`
  (served locally, no CDN — don't reintroduce one).
- **Escaping:** Jinja autoescapes, but a few routers build HTMX fragments as
  f-strings where it does not apply. In those, pass every interpolated value
  through `app.html.e()`, and any JSON embedded in a `<script>` through
  `app.html.json_for_script()`. New fragments are better as Jinja partials.
- **Money:** values are stored and aggregated in USD; use `currency_service`
  for conversions and `CURRENCY_SYMBOLS` for display symbols.
- **File naming:** snake_case for Python, kebab-case for templates/docs.

## Pull requests

- Keep PRs focused; one logical change per PR.
- Run the check gate and include a clear description of what and why.
- Do not add `Co-Authored-By` trailers to commits.
- Never commit real personal/financial data, secrets, or a real database — only
  `data/demo.db` (synthetic) is tracked; everything else under `data/` and the
  `cashflow/` and `reference/` paths is gitignored.

## Reporting bugs & requesting features

Open a GitHub issue with steps to reproduce (for bugs) or a clear use case (for
features). For security issues, follow [SECURITY.md](SECURITY.md) instead of
filing a public issue.
