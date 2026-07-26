# Automatic Market-Data Valuation

Networa can reprice every ticker-bearing asset from live market data instead of
requiring a manual value entry each time. There are three ways to trigger it —
a manual button, a JSON endpoint, and an opt-in daily schedule — and they all
funnel through the same service code (`app/services/snapshot_service.py`), so
the numbers agree no matter which one you use.

## What makes an asset priceable

A row is repriced only when **all** of these hold:

- `is_active = 1` (a soft-deleted row is never touched).
- `category = 'asset'`. A debt's balance is an amortisation schedule, not
  `quantity × market price`, so **debts are never priced by this path** — not
  even a debt that happens to carry a ticker (possible via CSV import, or the
  create form itself, since neither restricts `ticker`/`quantity` by
  category). The guard lives in `revalue_asset_from_market` itself, not only
  in the batch's SQL filter in front of it, so it holds for both callers: the
  batch reports it `skipped` with an explicit reason before ever calling that
  function, and the manual **Auto** button on an individual debt reaches the
  same guard and falls through to the exchange-rate/stored-value path
  instead.
- It carries a non-empty `ticker`.
- It carries a non-zero `quantity`.

Everything else is reported `skipped` with the reason (`no ticker`,
`no quantity`, or the liability note above), so a refresh's summary always
accounts for every active row — not just the ones that moved.

## The crypto pair convention

Yahoo Finance quotes spot crypto as a pair, e.g. `BTC-USD` or `ETH-USD`, but a
person (and the built-in sample portfolio) types the bare coin symbol. For the
`crypto` asset class only, a bare ticker gets a `-USD` suffix appended before
the fetch:

```
BTC      (crypto)  →  BTC-USD
 btc     (crypto)  →  BTC-USD
BTC-EUR  (crypto)  →  BTC-EUR   (already a pair — left alone)
0700.HK  (crypto)  →  0700.HK   (exchange suffix — left alone)
AAPL     (stock)   →  AAPL      (untouched — not the crypto class)
```

If the resolved pair returns no price, the raw ticker is retried once — a
crypto-flavoured equity such as `GBTC` (a trust that trades as a stock, not a
coin pair) has no `-USD` quote, so the fallback is what makes it price at all.
The refresh report's `symbol` field shows whichever one actually won, so you
can see `GBTC-USD` failed and `GBTC` succeeded.

`data/demo.db` and the first-run sample portfolio (`app/services/sample_data.py`)
both ship a bare `BTC`, on purpose, so this path is exercised out of the box.

## A non-positive or missing price never zeroes a holding

If Yahoo returns nothing, a 404, or times out, that one row is reported
`failed` and its previous value is left untouched. If Yahoo returns `0`, a
negative number, or something non-finite (a delisted ticker sometimes does),
that is also `failed` rather than being written — a real position must never
silently drop to zero on the trend chart because an upstream had a bad day.

## The three ways to trigger it

| Trigger | Endpoint | What it does |
|---|---|---|
| Manual button | `POST /prices/refresh` (HTMX, on the Dashboard and Assets pages) | Reprices every eligible asset and shows the outcome summary. Prices only — no FX pass, no history row. Works identically whether or not the daily schedule is on. |
| Cron-friendly JSON | `POST /api/v1/prices/refresh` | The same prices-only pass, as JSON. |
| Full daily job, on demand | `POST /api/v1/valuation/daily-run` | Fresh FX rates, ticker prices, FX reconversion for every other non-USD row, and a `net_worth_history` row for the day — the same job the in-app scheduler runs. Meant for a system cron that would rather drive this than the in-app scheduler: |

```bash
curl -X POST http://127.0.0.1:8000/api/v1/valuation/daily-run
```

| In-app schedule | Toggled from Settings, or `POST /settings/auto-valuation` | Runs the same full daily job automatically. **Off by default.** |

## The opt-in daily schedule

The scheduler (`app/scheduler.py`) is a plain `asyncio` background task — no
new dependency, no cron parser — started from the app's lifespan only when
`settings.auto_valuation_enabled` is `"1"`. On a default boot it starts no
task at all. Three settings keys, all stored in the existing `settings`
key/value table (no schema change):

| Setting | Values | Default |
|---|---|---|
| `auto_valuation_enabled` | `"1"` / `"0"` | `"0"` (off) |
| `auto_valuation_run_hour` | `"0"`–`"23"` | `"3"` (3 AM local time) |
| `auto_valuation_last_run` | `"YYYY-MM-DD"` | `""` (never) |

Turning it on and setting the hour is done from the **Settings** page (which
also shows whether the loop is currently running and when it is next expected
to fire), or:

```bash
curl -X POST http://127.0.0.1:8000/settings/auto-valuation \
     -d "enabled=1" -d "run_hour=3"
```

The loop wakes up every 15 minutes and asks `should_run` (`app/scheduler.py`)
whether to fire, given `auto_valuation_last_run` and `run_hour`:

- never run before (`auto_valuation_last_run` empty or unparseable) -> run
  now;
- already ran today -> wait;
- the last run is strictly earlier than yesterday, i.e. at least one whole
  calendar day was missed while the app was off -> run **immediately**,
  whatever the current hour;
- the last run was yesterday -> the normal cadence: wait until the clock
  reaches `run_hour`.

Either way the marker advances whether the run succeeded or failed, so a
broken upstream (Yahoo or NBU down) is retried once a day, not every 15
minutes. Turning the setting off stops the loop immediately, without a
restart.

The catch-up case is what makes a container that was off for several days —
or one that only happens to be up outside its `run_hour` window — notice and
run on its next boot rather than never running at all, or waiting until
`run_hour` comes around again. It is not a backfill, though: a caught-up run
still prices everything as of *today*. `market_service.fetch_ticker_price`
returns a current quote, not a historical one, so the prices for the actual
missed days are gone; the schedule only guarantees the numbers are never more
than one calendar day stale, and the normal daily cadence resumes right after.

## Weekends and outside market hours

Networa does not special-case non-trading days. Yahoo's chart API already
returns the nearest prior trading day's close (or the last known
`regularMarketPrice`) for a date when the market was closed, so a Saturday
refresh carries Friday's close forward — which is the correct answer for a
weekly-glance net-worth tracker.

## Local-first

The only outbound requests this feature makes are to Yahoo Finance (prices)
and the National Bank of Ukraine (`bank.gov.ua`, exchange rates) — the same
two hosts `market_service` and `currency_service` already talk to for the
manual **Auto** button and the **Exchange Rates** page. Nothing else leaves
the machine, and a failed request degrades to "that row/rate is unchanged"
rather than raising.
