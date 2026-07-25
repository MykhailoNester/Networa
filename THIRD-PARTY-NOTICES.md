# Third-Party Notices

Networa is licensed under the GNU Affero General Public License v3.0
(see [LICENSE](LICENSE)). It bundles and depends on the third-party components
below, each of which remains under its own license.

## Python runtime dependencies

Declared in [`requirements.txt`](requirements.txt):

| Package            | Version | License      |
|--------------------|---------|--------------|
| FastAPI            | 0.139.2 | MIT          |
| Uvicorn            | 0.51.0  | BSD-3-Clause |
| Jinja2             | 3.1.6   | BSD-3-Clause |
| aiosqlite          | 0.22.1  | MIT          |
| python-multipart   | 0.0.32  | Apache-2.0   |
| httpx              | 0.28.1  | BSD-3-Clause |

## Bundled front-end assets

Vendored under `app/static/vendor/` and served locally. Nothing is loaded from
a CDN, so rendering a page makes no third-party requests and the UI works
offline.

| Asset                     | Version  | License                |
|---------------------------|----------|------------------------|
| Chart.js                  | 4.4.4    | MIT                    |
| htmx                      | vendored | Zero-Clause BSD (0BSD) |
| Inter (variable woff2)     | v20      | SIL Open Font License 1.1 |
| Roboto Mono (variable woff2) | v31    | Apache License 2.0     |

The font files live in `app/static/vendor/fonts/` with `fonts.css` declaring
the `@font-face` rules. Subsets included: latin, latin-ext, cyrillic,
cyrillic-ext. Inter is © The Inter Project Authors under the SIL OFL 1.1;
Roboto Mono is © Google under the Apache License 2.0. Both licenses permit
redistribution of the unmodified font files as bundled here.

## Development-only tools

Used for linting, type-checking, and tests; not distributed with the
application: **ruff**, **mypy**, **pytest**.
