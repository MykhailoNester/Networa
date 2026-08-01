"""A value is recorded in the asset's own currency; USD is derived.

The VALUE tab used to post its number straight into ``snapshots.value_usd`` and
label the row ``'USD'``, so a EUR asset filed its EUR figure as dollars: the
history read back inflated by the EUR→USD rate, and ``_sync_asset_value_from_
latest_snapshot`` copied that same figure into ``assets.value``, corrupting the
native amount too. These tests pin the contract the whole tab now follows —
native in, USD derived, currency stated on screen.
"""

import re

import pytest
from fastapi.testclient import TestClient

from app import create_app, database
from app.config import settings

EUR_USD = 1.10


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A throwaway empty database, so this file owns every row it sees."""
    monkeypatch.setattr(settings, "DATABASE_PATH", tmp_path / "values.db")
    monkeypatch.setattr(settings, "SEED_SAMPLE_DATA", False)
    monkeypatch.setattr(database, "_db", None)
    with TestClient(create_app(), follow_redirects=True) as c:
        yield c


@pytest.fixture
def eur_asset(client):
    """A EUR-denominated asset, at a rate this file controls."""
    saved = client.post(
        "/api/v1/exchange-rates",
        json={
            "from_currency": "EUR",
            "to_currency": "USD",
            "rate": EUR_USD,
            "rate_date": "2026-01-01",
        },
    )
    assert saved.status_code == 200
    created = client.post(
        "/api/v1/assets",
        json={
            "name": "Berlin Flat",
            "asset_class": "real_estate",
            "value": 100_000,
            "currency": "EUR",
        },
    )
    assert created.status_code == 200
    return created.json()["id"]


def _snapshot_ids(html: str) -> list[int]:
    return [int(m) for m in re.findall(r'id="snap-row-(\d+)"', html)]


def test_a_value_is_entered_natively_and_converted_to_usd(client, eur_asset):
    client.post(
        f"/assets/{eur_asset}/snapshots/add",
        data={"snapshot_date": "2026-03-01", "value": "120000"},
    )

    asset = client.get(f"/api/v1/assets/{eur_asset}").json()

    # The native amount is exactly what was typed.
    assert asset["value"] == pytest.approx(120_000)
    assert asset["value_usd"] == pytest.approx(120_000 * EUR_USD)
    assert asset["current_value_usd"] == pytest.approx(120_000 * EUR_USD)


def test_the_recorded_row_keeps_the_currency_it_was_entered_in(client, eur_asset):
    body = client.post(
        f"/assets/{eur_asset}/snapshots/add",
        data={"snapshot_date": "2026-03-01", "value": "120000"},
    ).text

    # The history column is denominated in the display currency (USD here), with
    # the amount as entered underneath it — the confusion this fixes.
    assert "$132,000.00" in body
    assert "€120,000.00 EUR" in body


def test_the_add_form_says_which_currency_it_takes(client, eur_asset):
    page = client.get(f"/assets/{eur_asset}?tab=value").text

    assert 'name="value"' in page
    assert 'placeholder="Value in EUR"' in page
    # The live "≈ $x USD" preview, so the derived figure is never a surprise.
    assert 'id="new-snap-hint"' in page
    assert "var assetUsdRate = 1.1" in page


def test_editing_a_value_reconverts_rather_than_overwriting_usd(client, eur_asset):
    added = client.post(
        f"/assets/{eur_asset}/snapshots/add",
        data={"snapshot_date": "2026-03-01", "value": "120000"},
    ).text
    snap_id = _snapshot_ids(added)[0]

    edit_form = client.get(f"/assets/{eur_asset}/snapshots/{snap_id}/edit-row").text
    # The box is pre-filled with the native amount, not the USD one.
    assert 'value="120000.0"' in edit_form

    client.post(
        f"/assets/{eur_asset}/snapshots/{snap_id}/edit",
        data={"value": "130000"},
    )
    asset = client.get(f"/api/v1/assets/{eur_asset}").json()

    assert asset["value"] == pytest.approx(130_000)
    assert asset["value_usd"] == pytest.approx(130_000 * EUR_USD)


def test_a_usd_asset_is_unaffected(client):
    created = client.post(
        "/api/v1/assets",
        json={"name": "Brokerage", "asset_class": "stock", "value": 5_000},
    ).json()

    client.post(
        f"/assets/{created['id']}/snapshots/add",
        data={"snapshot_date": "2026-03-01", "value": "5500"},
    )
    asset = client.get(f"/api/v1/assets/{created['id']}").json()

    assert asset["value"] == pytest.approx(5_500)
    assert asset["value_usd"] == pytest.approx(5_500)


def test_an_add_with_no_amount_is_refused_not_recorded_as_zero(client, eur_asset):
    """A missing field must not wipe the day's value. The old handler defaulted
    to 0.0 and wrote it."""
    response = client.post(
        f"/assets/{eur_asset}/snapshots/add", data={"snapshot_date": "2026-03-01"}
    )

    assert response.status_code == 400
    assert client.get(f"/api/v1/assets/{eur_asset}").json()["value"] == pytest.approx(
        100_000
    )
