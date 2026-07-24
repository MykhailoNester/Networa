# Security Policy

## Trust model — read this before deploying

Networa is designed for **local, single-user, self-hosted** use, and
its threat model reflects that:

- **No authentication.** The app has no login, users, sessions, or access
  control. Anyone who can reach the HTTP port has full read/write access to all
  data.
- **Binds to `127.0.0.1` by default.** It is only reachable from the local
  machine unless you deliberately change `HOST`.
- **No telemetry, no external calls for your data.** Your financial data lives
  only in a local SQLite database (`data/…`) on your machine. (Optional
  features such as exchange-rate/price lookups may call public data APIs, but
  never transmit your holdings.)

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
