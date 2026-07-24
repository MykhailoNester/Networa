# Third-Party Notices

Networa is licensed under the GNU Affero General Public License v3.0
(see [LICENSE](LICENSE)). It bundles and depends on the third-party components
below, each of which remains under its own license.

## Python runtime dependencies

Declared in [`requirements.txt`](requirements.txt):

| Package            | Version | License      |
|--------------------|---------|--------------|
| FastAPI            | 0.115.0 | MIT          |
| Uvicorn            | 0.30.6  | BSD-3-Clause |
| Jinja2             | 3.1.4   | BSD-3-Clause |
| aiosqlite          | 0.20.0  | MIT          |
| python-multipart   | 0.0.9   | Apache-2.0   |
| httpx              | 0.27.0  | BSD-3-Clause |

## Bundled front-end assets

Vendored under `app/static/vendor/` and served locally (no external CDN):

| Library  | Version | License                |
|----------|---------|------------------------|
| Chart.js | 4.4.4   | MIT                    |
| htmx     | vendored| Zero-Clause BSD (0BSD) |

## Development-only tools

Used for linting, type-checking, and tests; not distributed with the
application: **ruff**, **mypy**, **pytest**.
