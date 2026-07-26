"""Automatic market-data auto-valuation: the batch price refresh, the FX
reconversion pass, the daily net_worth_history write, the opt-in scheduler, and
the HTTP surface around all four.

Every test here drives its own throwaway database — `on_fresh_db` (from
`tests/conftest.py`) or its own `tmp_path` via the `fresh_client` fixture below
— and never the shared `data/demo.db` copy. This file collects before
`tests/test_net_worth.py` (pytest sorts alphabetically), and that file's
`test_history_matches_the_independently_seeded_totals` uses the shared copy's
`net_worth_history` table as an independent oracle; writing a row or a
snapshot into it here would corrupt that assertion.

Every test also stubs the network: `market_service.fetch_ticker_price` and
`currency_service.fetch_rates_from_nbu` are reached as module attributes
(`market_service.fetch_ticker_price(...)`, never a `from`-import), so
monkeypatching the module attribute is enough to intercept every call the
service layer makes.
"""

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from app import create_app, database, scheduler
from app.config import settings
from app.services import currency_service, market_service
from app.services import snapshot_service as ss


@pytest.fixture
def fresh_client(tmp_path, monkeypatch):
    """A TestClient against a brand-new, unseeded database — never the shared
    demo copy, and never another test's tmp_path."""
    monkeypatch.setattr(settings, "DATABASE_PATH", tmp_path / "auto-valuation.db")
    monkeypatch.setattr(settings, "SEED_SAMPLE_DATA", False)
    monkeypatch.setattr(database, "_db", None)
    with TestClient(create_app()) as c:
        yield c


# --- resolve_symbol: the crypto pair convention -------------------------


def test_crypto_tickers_resolve_to_a_yahoo_pair():
    assert market_service.resolve_symbol("BTC", "crypto") == "BTC-USD"
    assert market_service.resolve_symbol(" btc ", "crypto") == "BTC-USD"
    # Already a pair, or an exchange suffix filed under crypto by mistake:
    # left untouched either way.
    assert market_service.resolve_symbol("BTC-EUR", "crypto") == "BTC-EUR"
    assert market_service.resolve_symbol("0700.HK", "crypto") == "0700.HK"
    assert market_service.resolve_symbol("AAPL", "stock") == "AAPL"


# --- refresh_all_prices / revalue_asset_from_market ---------------------


def test_refresh_prices_updates_tickers_and_explains_every_skip(
    on_fresh_db, monkeypatch
):
    async def fake_fetch(symbol, price_date):
        return (250.0, "USD")

    monkeypatch.setattr(market_service, "fetch_ticker_price", fake_fetch)

    async def body(db):
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, currency, value_usd, ticker, quantity) "
            "VALUES ('Global Index Fund', 'asset', 'fund', 20000, 'USD', 20000, 'VTI', 80)"
        )
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, currency, value_usd) "
            "VALUES ('Checking', 'asset', 'cash', 5000, 'USD', 5000)"
        )
        await db.commit()
        report = await ss.refresh_all_prices()
        today = date.today().isoformat()  # noqa: DTZ011 - local calendar date
        cursor = await db.execute(
            "SELECT COUNT(*) AS n FROM snapshots WHERE snapshot_date = ?", (today,)
        )
        snap_count = (await cursor.fetchone())["n"]
        return report, snap_count

    report, snap_count = on_fresh_db(body)

    assert report["updated"] == 1
    assert report["skipped"] == 1
    assert report["failed"] == 0
    assert snap_count == 1  # only the priced row gets a today snapshot

    by_name = {o["name"]: o for o in report["outcomes"]}
    assert by_name["Global Index Fund"]["status"] == "updated"
    assert by_name["Global Index Fund"]["value_usd"] == pytest.approx(250.0 * 80)
    assert by_name["Checking"]["status"] == "skipped"
    assert by_name["Checking"]["detail"] == "no ticker"


def test_a_debt_with_a_ticker_is_never_repriced(on_fresh_db, monkeypatch):
    calls = []

    async def fake_fetch(symbol, price_date):
        calls.append(symbol)
        return (999.0, "USD")

    monkeypatch.setattr(market_service, "fetch_ticker_price", fake_fetch)

    async def body(db):
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, currency, value_usd, ticker, quantity) "
            "VALUES ('Margin Loan', 'debt', 'miscellaneous', 5000, 'USD', 5000, 'MTGX', 100)"
        )
        await db.commit()
        report = await ss.refresh_all_prices()
        cursor = await db.execute(
            "SELECT value, value_usd FROM assets WHERE name = 'Margin Loan'"
        )
        asset_row = dict(await cursor.fetchone())
        cursor = await db.execute("SELECT COUNT(*) AS n FROM snapshots")
        snap_count = (await cursor.fetchone())["n"]
        return report, asset_row, snap_count

    report, asset_row, snap_count = on_fresh_db(body)

    assert report["updated"] == 0
    assert report["skipped"] == 1
    assert snap_count == 0
    assert asset_row["value"] == pytest.approx(5000)
    assert asset_row["value_usd"] == pytest.approx(5000)
    assert calls == []  # the debt's ticker was never handed to the fetch
    outcome = report["outcomes"][0]
    assert outcome["status"] == "skipped"
    assert "liability" in outcome["detail"]


def test_revalue_asset_from_market_refuses_a_debt_directly(on_fresh_db, monkeypatch):
    """The guard lives inside revalue_asset_from_market itself, not only in the
    batch's SQL filter (_PRICEABLE) in front of it — this is what protects the
    manual per-asset "Auto" button, which has no such filter."""
    calls = []

    async def fake_fetch(symbol, price_date):
        calls.append(symbol)
        return (999.0, "USD")

    monkeypatch.setattr(market_service, "fetch_ticker_price", fake_fetch)

    async def body(db):
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, currency, value_usd, ticker, quantity) "
            "VALUES ('Margin Loan', 'debt', 'miscellaneous', 5000, 'USD', 5000, 'MTGX', 100)"
        )
        await db.commit()
        cursor = await db.execute("SELECT * FROM assets WHERE name = 'Margin Loan'")
        asset = dict(await cursor.fetchone())
        return await ss.revalue_asset_from_market(db, asset, "2025-06-01")

    outcome = on_fresh_db(body)

    assert outcome["status"] == "skipped"
    assert "liability" in outcome["detail"]
    assert calls == []  # never even attempted the fetch


def test_the_manual_auto_button_refuses_a_debt_with_a_ticker(fresh_client, monkeypatch):
    """A debt can carry a ticker/quantity — CSV import, or the create form
    itself puts no category restriction on those fields — and the manual
    per-asset "Auto" button (snapshot_add_auto -> revalue_asset_from_market)
    reaches the priced row with no SQL filter in front of it, unlike the
    batch. It must fall through to the stored-value/exchange-rate path
    instead of repricing the liability as quantity x market price."""
    calls = []

    async def fake_fetch(symbol, price_date):
        calls.append(symbol)
        return (999.0, "USD")

    monkeypatch.setattr(market_service, "fetch_ticker_price", fake_fetch)

    created = fresh_client.post(
        "/api/v1/assets",
        json={
            "name": "Margin Loan",
            "category": "debt",
            "asset_class": "miscellaneous",
            "value": 5000,
            "currency": "USD",
            "ticker": "MTGX",
            "quantity": 100,
        },
    )
    assert created.status_code == 200
    asset_id = created.json()["id"]

    response = fresh_client.post(
        f"/assets/{asset_id}/snapshots/add-auto",
        data={"snapshot_date": "2025-06-01"},
    )

    assert response.status_code == 200
    assert calls == []  # the debt's ticker was never handed to the fetch

    asset = fresh_client.get(f"/api/v1/assets/{asset_id}").json()
    assert asset["value"] == pytest.approx(5000)  # unchanged, not 999 * 100
    assert asset["value_usd"] == pytest.approx(5000)


def test_net_worth_still_subtracts_debts_after_a_refresh(on_fresh_db, monkeypatch):
    async def fake_fetch(symbol, price_date):
        return (200.0, "USD")

    monkeypatch.setattr(market_service, "fetch_ticker_price", fake_fetch)

    async def body(db):
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, currency, value_usd, ticker, quantity) "
            "VALUES ('Fund', 'asset', 'fund', 10000, 'USD', 10000, 'FND', 100)"
        )
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, currency, value_usd) "
            "VALUES ('Mortgage', 'debt', 'real_estate', 30000, 'USD', 30000)"
        )
        await db.commit()
        await ss.refresh_all_prices()
        return await ss.get_current_net_worth()

    current = on_fresh_db(body)

    assert current["total_debts"] == pytest.approx(30000)
    assert current["total_assets"] == pytest.approx(200.0 * 100)
    assert current["net_worth"] == pytest.approx(
        current["total_assets"] - current["total_debts"]
    )


def test_a_failing_ticker_does_not_abort_the_run(on_fresh_db, monkeypatch):
    async def fake_fetch(symbol, price_date):
        return None if symbol == "BAD" else (42.0, "USD")

    monkeypatch.setattr(market_service, "fetch_ticker_price", fake_fetch)

    async def body(db):
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, currency, value_usd, ticker, quantity) "
            "VALUES ('Broken Fund', 'asset', 'fund', 100, 'USD', 100, 'BAD', 1)"
        )
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, currency, value_usd, ticker, quantity) "
            "VALUES ('Good Fund', 'asset', 'fund', 100, 'USD', 100, 'GOOD', 2)"
        )
        await db.commit()
        report = await ss.refresh_all_prices()
        cursor = await db.execute(
            "SELECT s.value_usd FROM snapshots s JOIN assets a ON a.id = s.asset_id "
            "WHERE a.name = 'Good Fund'"
        )
        row = await cursor.fetchone()
        return report, dict(row) if row else None

    report, row = on_fresh_db(body)

    assert report["updated"] == 1
    assert report["failed"] == 1
    assert row is not None
    assert row["value_usd"] == pytest.approx(84.0)


def test_a_raising_fetch_is_reported_as_failed(on_fresh_db, monkeypatch):
    async def fake_fetch(symbol, price_date):
        raise RuntimeError("network exploded")

    monkeypatch.setattr(market_service, "fetch_ticker_price", fake_fetch)

    async def body(db):
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, currency, value_usd, ticker, quantity) "
            "VALUES ('Fragile Fund', 'asset', 'fund', 100, 'USD', 100, 'FRAG', 5)"
        )
        await db.commit()
        return await ss.refresh_all_prices()

    report = on_fresh_db(body)

    assert report["failed"] == 1
    assert report["updated"] == 0
    assert "RuntimeError" in report["outcomes"][0]["detail"]


def test_a_non_positive_price_is_a_failure_not_a_zero_snapshot(
    on_fresh_db, monkeypatch
):
    async def fake_fetch(symbol, price_date):
        return (0.0, "USD")

    monkeypatch.setattr(market_service, "fetch_ticker_price", fake_fetch)

    async def body(db):
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, currency, value_usd, ticker, quantity) "
            "VALUES ('Delisted Co', 'asset', 'stock', 500, 'USD', 500, 'DELI', 10)"
        )
        await db.commit()
        report = await ss.refresh_all_prices()
        cursor = await db.execute(
            "SELECT value, value_usd FROM assets WHERE name = 'Delisted Co'"
        )
        asset_row = dict(await cursor.fetchone())
        cursor = await db.execute("SELECT COUNT(*) AS n FROM snapshots")
        snap_count = (await cursor.fetchone())["n"]
        return report, asset_row, snap_count

    report, asset_row, snap_count = on_fresh_db(body)

    assert report["failed"] == 1
    assert report["updated"] == 0
    assert asset_row["value_usd"] == pytest.approx(500)  # unchanged
    assert snap_count == 0  # no zero snapshot was written


def test_a_foreign_currency_asset_keeps_native_and_usd_in_step(
    on_fresh_db, monkeypatch
):
    async def fake_fetch(symbol, price_date):
        return (100.0, "USD")

    monkeypatch.setattr(market_service, "fetch_ticker_price", fake_fetch)

    async def body(db):
        await currency_service.save_rate("EUR", "USD", 1.10, "2025-01-01")
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, currency, value_usd, ticker, quantity) "
            "VALUES ('Euro ETF', 'asset', 'fund', 1000, 'EUR', 1100, 'EUFD', 10)"
        )
        await db.commit()
        report = await ss.refresh_all_prices()
        cursor = await db.execute(
            "SELECT value, value_usd, currency FROM assets WHERE name = 'Euro ETF'"
        )
        asset_row = dict(await cursor.fetchone())
        cursor = await db.execute("SELECT value, value_usd, currency FROM snapshots")
        snap_row = dict(await cursor.fetchone())
        return report, asset_row, snap_row

    report, asset_row, snap_row = on_fresh_db(body)

    expected_value_usd = round(100.0 * 10, 2)
    expected_value_native = round(expected_value_usd / 1.10, 4)

    assert report["updated"] == 1
    assert asset_row["value_usd"] == pytest.approx(expected_value_usd)
    assert asset_row["value"] == pytest.approx(expected_value_native)
    assert asset_row["currency"] == "EUR"
    assert snap_row["value_usd"] == pytest.approx(expected_value_usd)
    assert snap_row["value"] == pytest.approx(expected_value_native)
    assert snap_row["currency"] == "EUR"


def test_refresh_on_an_empty_database_writes_nothing(on_fresh_db):
    report = on_fresh_db(lambda db: ss.refresh_all_prices())

    assert report["updated"] == 0
    assert report["skipped"] == 0
    assert report["failed"] == 0
    assert report["outcomes"] == []


def test_a_bare_crypto_ticker_prices_via_the_dash_usd_pair(on_fresh_db, monkeypatch):
    """End-to-end through refresh_all_prices, not just the resolve_symbol unit
    test: the report's `symbol` is what the fetch was actually asked for."""

    async def fake_fetch(symbol, price_date):
        return (60_000.0, "USD") if symbol == "BTC-USD" else None

    monkeypatch.setattr(market_service, "fetch_ticker_price", fake_fetch)

    async def body(db):
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, currency, value_usd, ticker, quantity) "
            "VALUES ('Bitcoin', 'asset', 'crypto', 3000, 'USD', 3000, 'BTC', 0.05)"
        )
        await db.commit()
        return await ss.refresh_all_prices()

    report = on_fresh_db(body)

    assert report["updated"] == 1
    assert report["failed"] == 0
    outcome = report["outcomes"][0]
    assert outcome["ticker"] == "BTC"
    assert outcome["symbol"] == "BTC-USD"
    assert outcome["value_usd"] == pytest.approx(60_000.0 * 0.05)


def test_a_crypto_pair_that_fails_falls_back_to_the_raw_ticker(
    on_fresh_db, monkeypatch
):
    async def fake_fetch(symbol, price_date):
        if symbol == "GBTC-USD":
            return None
        if symbol == "GBTC":
            return (35.0, "USD")
        return None

    monkeypatch.setattr(market_service, "fetch_ticker_price", fake_fetch)

    async def body(db):
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, currency, value_usd, ticker, quantity) "
            "VALUES ('Grayscale Bitcoin Trust', 'asset', 'crypto', 700, 'USD', 700, 'GBTC', 20)"
        )
        await db.commit()
        return await ss.refresh_all_prices()

    report = on_fresh_db(body)

    assert report["updated"] == 1
    assert report["failed"] == 0
    outcome = report["outcomes"][0]
    assert outcome["symbol"] == "GBTC"  # the raw ticker won, not the -USD pair
    assert outcome["value_usd"] == pytest.approx(35.0 * 20)


# --- reconvert_foreign_currency_rows -------------------------------------


def test_fx_reconversion_rewrites_non_usd_rows_including_debts(on_fresh_db):
    async def body(db):
        await currency_service.save_rate("EUR", "USD", 1.20, "2025-01-01")
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, currency, value_usd) "
            "VALUES ('Euro Savings', 'asset', 'cash', 1000, 'EUR', 1200)"
        )
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, currency, value_usd) "
            "VALUES ('Euro Mortgage', 'debt', 'real_estate', 2000, 'EUR', 2400)"
        )
        await db.commit()
        # The rate moves after the cache above was written.
        await currency_service.save_rate("EUR", "USD", 1.30, "2025-06-01")

        fx = await ss.reconvert_foreign_currency_rows()
        today = date.today().isoformat()  # noqa: DTZ011 - local calendar date
        cursor = await db.execute(
            "SELECT a.name, a.value AS asset_value, a.value_usd AS asset_value_usd, "
            "s.value AS snap_value, s.value_usd AS snap_value_usd "
            "FROM assets a JOIN snapshots s ON s.asset_id = a.id "
            "WHERE s.snapshot_date = ? ORDER BY a.name",
            (today,),
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        current = await ss.get_current_net_worth()
        return fx, rows, current

    fx, rows, current = on_fresh_db(body)

    assert fx["reconverted"] == 2
    by_name = {r["name"]: r for r in rows}
    assert by_name["Euro Savings"]["asset_value"] == pytest.approx(1000)
    assert by_name["Euro Savings"]["asset_value_usd"] == pytest.approx(1300)
    assert by_name["Euro Savings"]["snap_value_usd"] == pytest.approx(1300)
    # A debt's stored value stays positive — signing is the aggregates' job.
    assert by_name["Euro Mortgage"]["asset_value"] == pytest.approx(2000)
    assert by_name["Euro Mortgage"]["asset_value_usd"] == pytest.approx(2600)
    assert current["net_worth"] == pytest.approx(1300 - 2600)


# --- run_daily_valuation: the skip_asset_ids interaction -------------------


def test_the_daily_job_does_not_double_convert_a_priced_foreign_currency_asset(
    on_fresh_db, monkeypatch
):
    """The one piece of logic run_daily_valuation adds on top of its three
    building blocks: priced_ids from the price pass is threaded into the FX
    pass's skip_asset_ids, so a non-USD ticker asset's fresh, price-pass USD
    figure is not immediately reconverted a second time. Both the ticker price
    and the NBU rate are stubbed, the stubbed rate is *different* from the one
    already on file, and every assertion is a concrete number rather than
    "changed" — an unguarded reconversion would show up here as a second entry
    for this asset in the combined outcome list, not necessarily as a
    different number (a same-rate round-trip nets out to the same cents)."""

    async def fake_fetch(symbol, price_date):
        return (90.0, "EUR")  # priced in the asset's own currency

    async def fake_nbu(rate_date=None):
        # Mirrors the real fetch_rates_from_nbu's side effect: it persists the
        # rate it fetched, which is exactly what makes it "fresh" for the
        # price pass that runs right after it.
        await currency_service.save_rate("EUR", "USD", 1.30, rate_date or "2025-06-01")
        return {"EUR": 1.30}

    monkeypatch.setattr(market_service, "fetch_ticker_price", fake_fetch)
    monkeypatch.setattr(currency_service, "fetch_rates_from_nbu", fake_nbu)

    async def body(db):
        await currency_service.save_rate("EUR", "USD", 1.10, "2025-01-01")
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, currency, value_usd, ticker, quantity) "
            "VALUES ('Euro Fund', 'asset', 'fund', 1000, 'EUR', 1100, 'EUFD', 10)"
        )
        await db.commit()
        cursor = await db.execute("SELECT id FROM assets WHERE name = 'Euro Fund'")
        asset_id = (await cursor.fetchone())["id"]

        report = await ss.run_daily_valuation("2025-06-01")

        cursor = await db.execute(
            "SELECT value, value_usd, currency FROM assets WHERE id = ?", (asset_id,)
        )
        asset_row = dict(await cursor.fetchone())
        cursor = await db.execute(
            "SELECT value, value_usd, currency FROM snapshots "
            "WHERE asset_id = ? AND snapshot_date = ?",
            (asset_id, "2025-06-01"),
        )
        snap_row = dict(await cursor.fetchone())
        return report, asset_id, asset_row, snap_row

    report, asset_id, asset_row, snap_row = on_fresh_db(body)

    # price_in_usd = 90.0 EUR * the fresh 1.30 rate (not the stale 1.10 on file
    # before the run), value_usd = price_in_usd * quantity.
    expected_value_usd = round(90.0 * 1.30 * 10, 2)
    expected_value_native = round(expected_value_usd / 1.30, 4)

    assert report["updated"] == 1
    assert asset_row["value_usd"] == pytest.approx(expected_value_usd)
    assert asset_row["value"] == pytest.approx(expected_value_native)
    assert asset_row["currency"] == "EUR"
    assert snap_row["value_usd"] == pytest.approx(expected_value_usd)
    assert snap_row["value"] == pytest.approx(expected_value_native)

    # Not reconverted a second time: it appears exactly once in the combined
    # outcome list, and the FX pass reports zero rows (it is the only non-USD
    # asset in this database).
    matching = [o for o in report["outcomes"] if o["asset_id"] == asset_id]
    assert len(matching) == 1
    assert matching[0]["source"] == "market"
    assert report["reconverted"] == 0


# --- write_net_worth_history ----------------------------------------------


def test_the_daily_history_row_is_assets_minus_debts(on_fresh_db):
    async def body(db):
        today = date.today().isoformat()  # noqa: DTZ011 - local calendar date
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, currency, value_usd, investable) "
            "VALUES ('Brokerage', 'asset', 'fund', 50000, 'USD', 50000, 'investable')"
        )
        # Marked investable too, on purpose: investable totals are asset-side
        # only, and this proves a debt cannot leak into them.
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, currency, value_usd, investable) "
            "VALUES ('Mortgage', 'debt', 'real_estate', 20000, 'USD', 20000, 'investable')"
        )
        await db.commit()
        cursor = await db.execute("SELECT id FROM assets ORDER BY id")
        ids = [r["id"] for r in await cursor.fetchall()]
        for asset_id, value in zip(ids, (50000, 20000), strict=True):
            await db.execute(
                "INSERT INTO snapshots (snapshot_date, asset_id, value, currency, value_usd) "
                "VALUES (?, ?, ?, 'USD', ?)",
                (today, asset_id, value, value),
            )
        await db.commit()

        history = await ss.write_net_worth_history(today)
        cursor = await db.execute(
            "SELECT total_assets_usd, total_debts_usd, net_worth_usd, investable_total_usd "
            "FROM net_worth_history WHERE snapshot_date = ?",
            (today,),
        )
        row = dict(await cursor.fetchone())
        current = await ss.get_current_net_worth()
        return history, row, current

    history, row, current = on_fresh_db(body)

    assert history["written"] is True
    assert row["net_worth_usd"] == pytest.approx(
        row["total_assets_usd"] - row["total_debts_usd"]
    )
    assert row["net_worth_usd"] == pytest.approx(current["net_worth"])
    assert row["investable_total_usd"] == pytest.approx(50000)  # Brokerage only


def test_the_history_row_is_written_on_a_day_when_nothing_repriced(on_fresh_db):
    async def body(db):
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, currency, value_usd) "
            "VALUES ('Cash', 'asset', 'cash', 8000, 'USD', 8000)"
        )
        await db.commit()
        cursor = await db.execute("SELECT id FROM assets")
        asset_id = (await cursor.fetchone())["id"]
        await db.execute(
            "INSERT INTO snapshots (snapshot_date, asset_id, value, currency, value_usd) "
            "VALUES ('2025-01-01', ?, 8000, 'USD', 8000)",
            (asset_id,),
        )
        await db.commit()

        today = date.today().isoformat()  # noqa: DTZ011 - local calendar date
        # Zero priceable rows: no ticker anywhere, nothing was repriced today.
        history = await ss.write_net_worth_history(today)
        current = await ss.get_current_net_worth()
        return history, current

    history, current = on_fresh_db(body)

    assert history["written"] is True
    assert history["net_worth_usd"] == pytest.approx(8000)
    assert history["net_worth_usd"] == pytest.approx(current["net_worth"])


def test_no_history_row_when_nothing_was_ever_snapshotted(on_fresh_db):
    async def body(db):
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, currency, value_usd) "
            "VALUES ('Cash', 'asset', 'cash', 8000, 'USD', 8000)"
        )
        await db.commit()
        today = date.today().isoformat()  # noqa: DTZ011 - local calendar date
        history = await ss.write_net_worth_history(today)
        cursor = await db.execute("SELECT COUNT(*) AS n FROM net_worth_history")
        count = (await cursor.fetchone())["n"]
        return history, count

    history, count = on_fresh_db(body)

    # A row of zeros would assert "net worth is zero" — the real answer is
    # "unknown", so nothing is written.
    assert history["written"] is False
    assert "reason" in history
    assert count == 0


# --- scheduler: pure functions --------------------------------------------


def test_should_run_waits_for_the_hour_and_fires_once_a_day():
    same_day_morning = datetime(2026, 7, 26, 9, 0, tzinfo=UTC)
    day_advanced_early = datetime(2026, 7, 26, 1, 0, tzinfo=UTC)
    day_advanced_at_hour = datetime(2026, 7, 26, 3, 0, tzinfo=UTC)

    # Already ran today: no, regardless of the hour.
    assert scheduler.should_run("2026-07-26", same_day_morning, 3) is False
    # A new day, but the hour has not arrived yet.
    assert scheduler.should_run("2026-07-25", day_advanced_early, 3) is False
    # A new day, and the hour has arrived.
    assert scheduler.should_run("2026-07-25", day_advanced_at_hour, 3) is True
    # Never run before: fires as soon as the hour is reached.
    assert scheduler.should_run("", day_advanced_at_hour, 3) is True


def test_parse_run_hour_falls_back_to_the_default_when_unparseable():
    assert scheduler.parse_run_hour("25") == scheduler.DEFAULT_RUN_HOUR
    assert scheduler.parse_run_hour("abc") == scheduler.DEFAULT_RUN_HOUR
    assert scheduler.parse_run_hour("") == scheduler.DEFAULT_RUN_HOUR
    assert scheduler.parse_run_hour("0") == 0


# --- scheduler: lifecycle wired through the app ---------------------------


def test_the_scheduler_is_off_after_a_default_boot(fresh_client):
    assert scheduler.is_running() is False


def test_toggling_the_setting_starts_and_stops_the_loop(fresh_client, monkeypatch):
    # No work, no network, no sleep assertion: only start()/stop() are under
    # test here, not what a run does.
    async def fake_run_once(price_date=None):
        return {}

    monkeypatch.setattr(scheduler, "run_once", fake_run_once)

    on_response = fresh_client.post(
        "/settings/auto-valuation", data={"enabled": "1", "run_hour": "3"}
    )
    assert on_response.status_code == 200  # followed the redirect to "/"
    assert scheduler.is_running() is True

    off_response = fresh_client.post(
        "/settings/auto-valuation", data={"enabled": "0", "run_hour": "3"}
    )
    assert off_response.status_code == 200
    assert scheduler.is_running() is False


# --- HTTP surface ----------------------------------------------------------


def test_the_refresh_endpoint_reports_the_outcome_summary(fresh_client, monkeypatch):
    async def fake_fetch(symbol, price_date):
        return (123.45, "USD")

    monkeypatch.setattr(market_service, "fetch_ticker_price", fake_fetch)

    created = fresh_client.post(
        "/api/v1/assets",
        json={
            "name": "Index Fund",
            "asset_class": "fund",
            "value": 100,
            "currency": "USD",
            "ticker": "VTI",
            "quantity": 10,
        },
    )
    assert created.status_code == 200

    response = fresh_client.post("/prices/refresh")

    assert response.status_code == 200
    assert "Index Fund" in response.text
    assert "<strong>1</strong> updated" in response.text


def test_the_refresh_partial_escapes_a_hostile_ticker(fresh_client, monkeypatch):
    payload = "<img src=x onerror=alert(1)>"

    async def fake_fetch(symbol, price_date):
        return (10.0, "USD")

    monkeypatch.setattr(market_service, "fetch_ticker_price", fake_fetch)

    created = fresh_client.post(
        "/api/v1/assets",
        json={
            "name": "XSS probe",
            "asset_class": "stock",
            "value": 100,
            "currency": "USD",
            "ticker": payload,
            "quantity": 5,
        },
    )
    assert created.status_code == 200

    response = fresh_client.post("/prices/refresh")

    assert response.status_code == 200
    assert payload not in response.text
    assert "&lt;img" in response.text


def test_the_json_refresh_returns_the_report(fresh_client, monkeypatch):
    async def fake_fetch(symbol, price_date):
        return (50.0, "USD")

    monkeypatch.setattr(market_service, "fetch_ticker_price", fake_fetch)

    fresh_client.post(
        "/api/v1/assets",
        json={
            "name": "Index Fund",
            "asset_class": "fund",
            "value": 100,
            "currency": "USD",
            "ticker": "VTI",
            "quantity": 10,
        },
    )

    response = fresh_client.post("/api/v1/prices/refresh")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"price_date", "updated", "skipped", "failed", "outcomes"}
    assert body["updated"] == 1
    assert body["failed"] == 0
    assert body["skipped"] == 0


def test_the_daily_run_endpoint_writes_the_history_row(fresh_client, monkeypatch):
    async def fake_fetch(symbol, price_date):
        return (100.0, "USD")

    async def fake_nbu(rate_date=None):
        return {}

    monkeypatch.setattr(market_service, "fetch_ticker_price", fake_fetch)
    monkeypatch.setattr(currency_service, "fetch_rates_from_nbu", fake_nbu)

    # The HTML form path (not the JSON API) so both rows get an initial
    # snapshot, which the as-of history query needs to see either of them.
    fresh_client.post(
        "/assets/create",
        data={
            "name": "Fund",
            "category": "asset",
            "asset_class": "fund",
            "value": "1000",
            "currency": "USD",
            "ticker": "FND",
            "quantity": "10",
        },
    )
    fresh_client.post(
        "/assets/create",
        data={
            "name": "Loan",
            "category": "debt",
            "asset_class": "miscellaneous",
            "value": "300",
            "currency": "USD",
        },
    )

    response = fresh_client.post("/api/v1/valuation/daily-run")

    assert response.status_code == 200
    body = response.json()
    assert body["updated"] == 1  # the Fund, repriced via its ticker
    assert body["history"]["written"] is True
    assert body["history"]["net_worth_usd"] == pytest.approx(
        body["history"]["total_assets_usd"] - body["history"]["total_debts_usd"]
    )
    assert body["history"]["total_debts_usd"] == pytest.approx(300)
