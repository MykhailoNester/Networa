"""Net worth is assets MINUS debts.

The product is named after this number, so these tests pin the arithmetic
rather than the presentation: the headline total, the trend series, and the
per-line contributions all have to agree with each other and with the
liabilities recorded in the database.

``_run`` drives a body against the seeded demo copy; the ``on_fresh_db`` fixture
in conftest.py drives one against an empty database, for the cases that need
balances chosen to hit a specific boundary.
"""

import asyncio
from collections.abc import Callable, Coroutine
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import create_app, database
from app.config import settings
from app.services import currency_service
from app.services import snapshot_service as ss
from app.services.import_service import import_assets_csv

# The committed demo dataset: 11 active assets, 2 active debts.
DEMO_ASSETS = 955_000.0
DEMO_DEBTS = 303_500.0
DEMO_NET = DEMO_ASSETS - DEMO_DEBTS  # 651,500


def _run(body: Callable[[], Coroutine]):
    """Drive an async service against the configured test database."""

    async def main():
        await database.init_db()
        try:
            return await body()
        finally:
            await database.close_db()

    return asyncio.run(main())


# --- The headline number ------------------------------------------------


def test_net_worth_subtracts_debts():
    data = _run(ss.get_current_net_worth)

    assert data["total_assets"] == pytest.approx(DEMO_ASSETS)
    assert data["total_debts"] == pytest.approx(DEMO_DEBTS)
    assert data["net_worth"] == pytest.approx(DEMO_NET)
    # The bug this guards: net_worth silently equal to gross assets.
    assert data["net_worth"] != pytest.approx(data["total_assets"])
    assert data["assets_count"] == 11
    assert data["debts_count"] == 2


def test_debts_are_reported_individually():
    data = _run(ss.get_current_net_worth)

    assert sum(data["debts_by_name"].values()) == pytest.approx(DEMO_DEBTS)
    assert any("Mortgage" in name for name in data["debts_by_name"])


def test_allocation_stays_asset_side():
    """Composition views describe assets; a liability is not an asset class."""
    data = _run(ss.get_current_net_worth)

    allocated = sum(info["total"] for info in data["allocation_by_class"].values())
    assert allocated == pytest.approx(DEMO_ASSETS)
    assert sum(data["allocation_by_sheet"].values()) == pytest.approx(DEMO_ASSETS)


# --- The trend series --------------------------------------------------


def test_history_is_net_of_debts_and_ends_where_the_headline_does():
    async def body():
        history = await ss.get_net_worth_history()
        current = await ss.get_current_net_worth()
        return history, current

    history, current = _run(body)

    assert history, "demo database should have a trend series"
    for point in history:
        assert point["net_worth_usd"] == pytest.approx(
            point["total_assets_usd"] - point["total_debts_usd"]
        )
        assert point["total_debts_usd"] > 0, "demo debts span the whole series"

    # The last point of the chart and the dashboard total are the same figure.
    assert history[-1]["net_worth_usd"] == pytest.approx(current["net_worth"])


def test_history_keeps_dates_that_only_a_debt_moved(on_fresh_db):
    """A date carrying only a debt snapshot is still a point on the curve."""

    async def body(db):
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, value_usd) "
            "VALUES ('House', 'asset', 'real_estate', 300000, 300000)"
        )
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, value_usd) "
            "VALUES ('Mortgage', 'debt', 'real_estate', 200000, 200000)"
        )
        await db.execute(
            "INSERT INTO snapshots (snapshot_date, asset_id, value, currency, value_usd) "
            "VALUES ('2025-01-01', 1, 300000, 'USD', 300000)"
        )
        await db.execute(
            "INSERT INTO snapshots (snapshot_date, asset_id, value, currency, value_usd) "
            "VALUES ('2025-01-01', 2, 200000, 'USD', 200000)"
        )
        # Only the mortgage moves on this date — a payment, no asset revaluation.
        await db.execute(
            "INSERT INTO snapshots (snapshot_date, asset_id, value, currency, value_usd) "
            "VALUES ('2025-02-01', 2, 195000, 'USD', 195000)"
        )
        await db.commit()
        return await ss.get_net_worth_history()

    history = on_fresh_db(body)
    dates = [point["snapshot_date"] for point in history]

    assert dates == ["2025-01-01", "2025-02-01"]
    assert history[0]["net_worth_usd"] == pytest.approx(100_000)
    # The house's value carries forward; only the debt changed.
    assert history[1]["total_assets_usd"] == pytest.approx(300_000)
    assert history[1]["net_worth_usd"] == pytest.approx(105_000)


# --- Derived figures ---------------------------------------------------


def test_paying_down_a_debt_counts_as_a_gain():
    """A shrinking liability lifts net worth, so its contribution is positive."""
    contributors = _run(lambda: ss.get_period_contributors("all_time"))

    debts = [c for c in contributors if c["category"] == "debt"]
    assert debts, "demo debts amortise over the series"
    for debt in debts:
        # Balances fall across the demo history, so every debt is a gain.
        assert debt["current_val"] < debt["ref_val"]
        assert debt["change"] > 0


def test_contributors_reconcile_with_the_period_change():
    async def body():
        return (
            await ss.get_period_contributors("all_time"),
            await ss.get_period_returns(),
        )

    contributors, returns = _run(body)

    assert returns["all_time_change"] is not None
    assert sum(c["change"] for c in contributors) == pytest.approx(
        returns["all_time_change"], abs=0.02
    )


def test_history_matches_the_independently_seeded_totals():
    """The live carry-forward query against an independent computation.

    scripts/seed_demo.py fills the net_worth_history TABLE by summing its own
    per-month lists in Python — a completely separate code path the application
    never reads. It is therefore a free oracle for the hardest query here.
    """

    async def body():
        db = await database.get_db()
        cursor = await db.execute(
            "SELECT snapshot_date, total_assets_usd, total_debts_usd, net_worth_usd "
            "FROM net_worth_history ORDER BY snapshot_date"
        )
        seeded = {row["snapshot_date"]: dict(row) for row in await cursor.fetchall()}
        return await ss.get_net_worth_history(), seeded

    history, seeded = _run(body)

    assert seeded, "demo database ships a seeded net_worth_history table"
    assert [p["snapshot_date"] for p in history] == sorted(seeded)
    for point in history:
        expected = seeded[point["snapshot_date"]]
        for column in ("total_assets_usd", "total_debts_usd", "net_worth_usd"):
            assert point[column] == pytest.approx(expected[column], abs=0.01), (
                f"{column} diverged on {point['snapshot_date']}"
            )


def test_top_movers_signs_debts_by_net_worth_effect(on_fresh_db):
    """Built on explicit dates: `days` is relative to today, so asserting
    against the demo dataset would start failing as its snapshots age out."""

    async def body(db):
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, value_usd) "
            "VALUES ('Fund', 'asset', 'fund', 60000, 60000)"
        )
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, value_usd) "
            "VALUES ('Mortgage', 'debt', 'real_estate', 90000, 90000)"
        )
        today = date.today()  # noqa: DTZ011 - matches the service's local-date basis
        # Must predate the 30-day window, or it is not a *reference* point:
        # get_top_movers resolves the baseline from snapshots at or before the
        # cutoff, and inner-joins it, so a too-recent baseline yields no rows.
        earlier = (today - timedelta(days=60)).isoformat()
        for asset_id, value in ((1, 50000), (2, 100000)):
            await db.execute(
                "INSERT INTO snapshots (snapshot_date, asset_id, value, currency, value_usd) "
                "VALUES (?, ?, ?, 'USD', ?)",
                (earlier, asset_id, value, value),
            )
        # The fund gains 10k; the mortgage is paid down by 10k. Both lift net
        # worth by 10k, so both must surface as positive movers.
        for asset_id, value in ((1, 60000), (2, 90000)):
            await db.execute(
                "INSERT INTO snapshots (snapshot_date, asset_id, value, currency, value_usd) "
                "VALUES (?, ?, ?, 'USD', ?)",
                (today.isoformat(), asset_id, value, value),
            )
        await db.commit()
        return await ss.get_top_movers(days=30, limit=10)

    movers = {m["name"]: m for m in on_fresh_db(body)}

    assert set(movers) == {"Fund", "Mortgage"}
    assert movers["Fund"]["change_val"] == pytest.approx(10_000)
    assert movers["Mortgage"]["change_val"] == pytest.approx(10_000)
    # Percentages are denominated by magnitude, so their signs agree too.
    assert movers["Mortgage"]["change_pct"] == pytest.approx(10.0)
    assert movers["Fund"]["change_pct"] == pytest.approx(20.0)


def test_percentages_are_withheld_when_the_reference_is_not_positive(on_fresh_db):
    """Debts exceeding assets makes a ratio meaningless, not merely negative."""

    async def body(db):
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, value_usd) "
            "VALUES ('Car', 'asset', 'vehicle', 10000, 10000)"
        )
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, value_usd) "
            "VALUES ('Car Loan', 'debt', 'vehicle', 25000, 25000)"
        )
        for asset_id, value in ((1, 10000), (2, 25000)):
            await db.execute(
                "INSERT INTO snapshots (snapshot_date, asset_id, value, currency, value_usd) "
                "VALUES ('2025-01-01', ?, ?, 'USD', ?)",
                (asset_id, value, value),
            )
        # A later payment: net worth improves but is still negative.
        await db.execute(
            "INSERT INTO snapshots (snapshot_date, asset_id, value, currency, value_usd) "
            "VALUES ('2025-06-01', 2, 20000, 'USD', 20000)"
        )
        await db.commit()
        return await ss.get_current_net_worth(), await ss.get_period_returns()

    current, returns = on_fresh_db(body)

    assert current["net_worth"] == pytest.approx(-10_000)
    # Absolute change is still reported; the percentage is not invented.
    assert returns["all_time_change"] == pytest.approx(5_000)
    assert returns["all_time"] is None


def test_returns_are_empty_for_an_empty_portfolio(on_fresh_db):
    assert on_fresh_db(lambda db: ss.get_period_returns()) == {}


def test_a_debt_in_another_currency_is_subtracted_in_usd(on_fresh_db):
    """Aggregation happens in USD, so a foreign-currency balance has to be
    converted before it is subtracted — not subtracted at face value."""
    csv = (
        "name,asset_class,category,value,currency\n"
        "Flat,real_estate,asset,300000,USD\n"
        "Euro Mortgage,real_estate,debt,100000,EUR\n"
    )

    async def body(db):
        await currency_service.save_rate("EUR", "USD", 1.10, "2025-01-01")
        await import_assets_csv(csv)
        cursor = await db.execute(
            "SELECT value, currency, value_usd FROM assets WHERE category = 'debt'"
        )
        return dict(await cursor.fetchone()), await ss.get_current_net_worth()

    debt, current = on_fresh_db(body)

    assert debt["value"] == pytest.approx(100_000)  # native amount preserved
    assert debt["currency"] == "EUR"
    assert debt["value_usd"] == pytest.approx(110_000)
    assert current["total_debts"] == pytest.approx(110_000)
    assert current["net_worth"] == pytest.approx(190_000)


def test_a_net_worth_of_exactly_zero_is_a_figure_not_a_blank(on_fresh_db):
    """Assets equal to debts is the boundary that a truthiness check gets wrong."""

    async def body(db):
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, value_usd) "
            "VALUES ('Flat', 'asset', 'real_estate', 50000, 50000)"
        )
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, value_usd) "
            "VALUES ('Mortgage', 'debt', 'real_estate', 50000, 50000)"
        )
        for asset_id in (1, 2):
            await db.execute(
                "INSERT INTO snapshots (snapshot_date, asset_id, value, currency, value_usd) "
                "VALUES ('2025-01-01', ?, 50000, 'USD', 50000)",
                (asset_id,),
            )
        await db.commit()
        return (
            await ss.get_current_net_worth(),
            await ss.get_net_worth_history(),
            await ss._get_net_worth_at_date(db, "2025-01-01"),
        )

    current, history, at_date = on_fresh_db(body)

    assert current["net_worth"] == 0.0
    assert history[-1]["net_worth_usd"] == 0.0
    # None would mean "no data", which would blank the period cards instead.
    assert at_date == 0.0


def test_deactivating_a_debt_removes_it_from_net_worth(on_fresh_db):
    """Deletion is a soft delete, so the aggregates must respect is_active."""

    async def body(db):
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, value_usd) "
            "VALUES ('Flat', 'asset', 'real_estate', 100000, 100000)"
        )
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, value_usd) "
            "VALUES ('Loan', 'debt', 'miscellaneous', 40000, 40000)"
        )
        await db.commit()
        before = await ss.get_current_net_worth()
        await db.execute("UPDATE assets SET is_active = 0 WHERE category = 'debt'")
        await db.commit()
        return before, await ss.get_current_net_worth()

    before, after = on_fresh_db(body)

    assert before["net_worth"] == pytest.approx(60_000)
    assert after["net_worth"] == pytest.approx(100_000)
    assert after["total_debts"] == 0
    assert after["debts_count"] == 0


def test_a_credit_balance_on_a_debt_raises_net_worth(on_fresh_db):
    """A negative debt is a real thing — an escrow over-payment is money owed
    back to you. Aggregation must not abs() it away."""

    async def body(db):
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, value_usd) "
            "VALUES ('Flat', 'asset', 'real_estate', 100000, 100000)"
        )
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, value_usd) "
            "VALUES ('Escrow', 'debt', 'miscellaneous', -400, -400)"
        )
        await db.commit()
        return await ss.get_current_net_worth()

    current = on_fresh_db(body)

    assert current["total_debts"] == pytest.approx(-400)
    assert current["net_worth"] == pytest.approx(100_400)


def test_take_snapshot_records_debts_and_returns_net_worth(on_fresh_db):
    """The endpoint used to freeze liability balances while assets advanced."""

    async def body(db):
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, value_usd) "
            "VALUES ('Flat', 'asset', 'real_estate', 300000, 300000)"
        )
        await db.execute(
            "INSERT INTO assets (name, category, asset_class, value, value_usd) "
            "VALUES ('Mortgage', 'debt', 'real_estate', 120000, 120000)"
        )
        await db.commit()
        result = await ss.take_snapshot("2025-03-01")
        cursor = await db.execute(
            "SELECT a.category FROM snapshots s JOIN assets a ON a.id = s.asset_id "
            "WHERE s.snapshot_date = '2025-03-01'"
        )
        return result, sorted(row["category"] for row in await cursor.fetchall())

    result, snapshotted = on_fresh_db(body)

    assert snapshotted == ["asset", "debt"], "both categories must be snapshotted"
    assert result["total_assets"] == pytest.approx(300_000)
    assert result["total_debts"] == pytest.approx(120_000)
    assert result["net_worth"] == pytest.approx(180_000)


def test_imported_debts_are_stored_as_magnitudes(on_fresh_db):
    """Other tools export liabilities as negatives; storing that sign would
    negate it a second time on aggregation and *raise* net worth."""
    csv = (
        "name,asset_class,category,value\n"
        "House,real_estate,asset,300000\n"
        "Mortgage,real_estate,debt,-200000\n"
    )

    async def body(db):
        await import_assets_csv(csv)
        cursor = await db.execute(
            "SELECT value, value_usd FROM assets WHERE category = 'debt'"
        )
        row = await cursor.fetchone()
        return dict(row), await ss.get_current_net_worth()

    debt, current = on_fresh_db(body)

    assert debt["value"] == pytest.approx(200_000)
    assert debt["value_usd"] == pytest.approx(200_000)
    assert current["net_worth"] == pytest.approx(100_000)


# --- The debts page ----------------------------------------------------


@pytest.fixture
def client():
    with TestClient(create_app(), follow_redirects=True) as c:
        yield c


def test_debts_page_lists_the_liabilities(client):
    response = client.get("/debts")

    assert response.status_code == 200
    assert "Mortgage" in response.text
    # The add-debt affordance is what made the orphaned template unusable.
    assert "/assets/create" in response.text
    assert 'name="category" value="debt"' in response.text


def test_dashboard_api_reports_debts(client):
    payload = client.get("/api/v1/dashboard").json()

    assert payload["net_worth"] == pytest.approx(DEMO_NET)
    assert payload["total_debts"] == pytest.approx(DEMO_DEBTS)
    assert payload["debts_count"] == 2


def test_debt_detail_page_hides_the_asset_only_controls(client):
    """A liability has no cost basis, return, investable tier or tax on gain,
    so those controls must not be offered — a no-op input invites bad data."""
    debt = client.get("/assets/12")  # the demo Mortgage
    asset = client.get("/assets/1")

    assert debt.status_code == 200
    assert "Debt Info" in debt.text
    assert "Back to Debts" in debt.text
    for absent in (
        'data-tab="returns"',  # the whole RETURNS tab
        "Investable Asset?",
        "Taxable Asset?",
        "Tax Estimate",
        "Ticker Symbol",
    ):
        assert absent not in debt.text, f"{absent!r} should not render for a debt"
    # Balance-flavoured labels replace the asset-flavoured ones.
    assert "Current Balance" in debt.text
    assert "Balance Over Time" in debt.text

    # None of which is removed for a real asset.
    assert asset.status_code == 200
    assert 'data-tab="returns"' in asset.text
    assert "Investable Asset?" in asset.text
    assert "Current Value" in asset.text


def test_history_card_appears_before_any_value_is_recorded(tmp_path, monkeypatch):
    """A row with no snapshots still needs the history card and its add control,
    or there is no way to record a first value. Uses its own empty database so
    the shared demo copy's asset count stays intact for the other tests."""
    monkeypatch.setattr(settings, "DATABASE_PATH", tmp_path / "empty.db")
    monkeypatch.setattr(settings, "SEED_SAMPLE_DATA", False)
    monkeypatch.setattr(database, "_db", None)

    with TestClient(create_app(), follow_redirects=True) as fresh:
        # value=0 creates the row without an initial snapshot.
        page = fresh.post(
            "/assets/create",
            data={
                "name": "Unvalued Flat",
                "category": "asset",
                "asset_class": "real_estate",
                "value": "0",
                "currency": "USD",
            },
        )

    assert page.status_code == 200
    assert 'id="value-history-table"' in page.text
    assert "/snapshots/add" in page.text
    # Exactly one, because HTMX swaps into #snap-tbody by id.
    assert page.text.count('id="snap-tbody"') == 1
    # No data yet, so no chart.
    assert 'id="assetValueChart"' not in page.text


def test_debt_detail_survives_a_stale_returns_tab_link(client):
    """?tab=returns is reachable from old links and from the edit redirect."""
    response = client.get("/assets/12?tab=returns")

    assert response.status_code == 200
    assert "Debt Info" in response.text


def test_debts_api_returns_only_debts(client):
    rows = client.get("/api/v1/debts").json()

    assert len(rows) == 2
    assert {row["category"] for row in rows} == {"debt"}
