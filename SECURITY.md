# Security Policy

## Trust model — read this before deploying

Networa is designed for **local, single-user, self-hosted** use, and
its threat model reflects that:

- **No authentication.** The app has no login, users, sessions, or access
  control. Anyone who can reach the HTTP port has full read/write access to all
  data.
- **Binds to `127.0.0.1` by default.** It is only reachable from the local
  machine unless you deliberately change `HOST`. The Docker Compose port
  mapping is likewise pinned to `127.0.0.1`.
- **No telemetry and no third-party requests to render the UI.** Fonts, HTMX
  and Chart.js are all vendored under `app/static/vendor/`, so loading a page
  contacts nothing but your own machine, and the UI works fully offline.
- **Your data stays local.** It lives only in a SQLite database (`data/…`) on
  your machine.

### Outbound network calls, in full

The app makes network requests only on actions you trigger, never in the
background, and never with your balances:

| Trigger | Endpoint | What is sent |
|---|---|---|
| Per-asset "auto" value refresh on a ticker asset | `query1.finance.yahoo.com` | The ticker symbol and a date. Yahoo therefore learns *which* symbols you hold — not quantities or values. |
| Fetching FX rates, and switching display currency | `bank.gov.ua` (NBU) | Nothing but a date. |

Nothing else leaves the machine. If even the ticker lookup is more than you
want to share, leave the ticker field empty and enter values manually.

### Cross-origin protection

Because there is no authentication, any page in your browser could otherwise
drive the app by submitting a form at it — a plain HTML form POST is sent
cross-origin with no preflight. Two middlewares in `app/security.py` close
that off:

- State-changing requests (`POST`/`PUT`/`PATCH`/`DELETE`) are rejected unless
  the browser reports them as same-origin. Non-browser clients (curl, the REST
  API) send no origin headers and are unaffected.
- The `Host` header is restricted, which is what prevents DNS rebinding — an
  attack where a hostile page points a hostname it controls at your loopback
  address, so that `Origin` and `Host` agree and the browser treats the app as
  same-origin. Because that requires a *name*, the rule applies to names only:
  every IP address and `localhost` are always accepted, and any other hostname
  must be listed in `ALLOWED_HOSTS`. Behind a reverse proxy, add your hostname
  there and forward the original `Host`.

These reduce the blast radius of a browser-based attack. They are **not** a
substitute for authentication: anyone who can reach the port directly still
has full access.

If you want to reach the app from other devices, **do not** bind it to
`0.0.0.0` directly. Put it behind a trusted reverse proxy (e.g. Caddy, nginx,
or a Tailscale/VPN network) that provides TLS and authentication. Exposing an
unauthenticated instance to a network or the public internet gives anyone who
finds it complete access to your financial data.

## Supported versions

This is an early-stage project; security fixes are applied to the latest
`main`. There are no long-term support branches yet.

## Reporting a vulnerability

Please report security issues **privately** — do not open a public GitHub issue.

- Email the maintainer at **nsmisha.dev@gmail.com**, or
- open a private report via
  [GitHub Security Advisories](https://github.com/MykhailoNester/Networa/security/advisories/new).

Include reproduction steps and impact. You'll get an acknowledgement as soon as
possible, and a fix or mitigation will be coordinated before any public
disclosure.
