"""Regression tests for the escaping and same-origin defences.

Each test here corresponds to a hole that was once open, so they are written as
"the attack no longer works" rather than "the helper returns X".
"""

import pytest
from fastapi.testclient import TestClient

from app import create_app
from app.html import e, json_for_script

TICKER_PAYLOAD = "<img src=x onerror=alert(1)>"
SCRIPT_PAYLOAD = "</script><script>alert(1)</script>"


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def hostile_asset(client):
    """An asset whose ticker and currency both carry HTML payloads."""
    response = client.post(
        "/api/v1/assets",
        json={
            "name": "XSS probe",
            "asset_class": "stock",
            "value": 100,
            "currency": SCRIPT_PAYLOAD,
            "ticker": TICKER_PAYLOAD,
            "quantity": 5,
        },
    )
    assert response.status_code == 200
    return response.json()["id"]


# --- Escaping helpers ---


def test_e_escapes_html_and_quotes():
    assert e("<b>") == "&lt;b&gt;"
    assert e('a"b') == "a&quot;b"


def test_e_preserves_zero_and_blanks_none():
    # `str(val or "")` would turn 0 into "" — numbers must survive intact.
    assert e(0) == "0"
    assert e(None) == ""


def test_json_for_script_neutralises_closing_tag():
    payload = json_for_script({"currency": SCRIPT_PAYLOAD})
    assert "</script>" not in payload
    assert "\\u003c" in payload


# --- Stored XSS in hand-built HTMX fragments ---


def test_ticker_is_escaped_in_value_cell(client, hostile_asset):
    body = client.get(f"/assets/{hostile_asset}/inline-display").text
    assert TICKER_PAYLOAD not in body
    assert "&lt;img" in body


def test_currency_is_escaped_in_value_cell(client, hostile_asset):
    body = client.get(f"/assets/{hostile_asset}/inline-display").text
    assert "</script>" not in body


def test_snapshot_json_cannot_escape_its_script_block(client, hostile_asset):
    """The chart-data fragment embeds snapshots, which carry the asset currency."""
    client.post(f"/assets/{hostile_asset}/inline-save", data={"value": "100"})
    client.post(
        f"/assets/{hostile_asset}/snapshots/add",
        data={"snapshot_date": "2026-01-02", "value": "120"},
    )
    body = client.post(
        f"/assets/{hostile_asset}/snapshots/add",
        data={"snapshot_date": "2026-01-03", "value": "130"},
    ).text
    assert "snapData=" in body
    assert SCRIPT_PAYLOAD not in body


def test_the_detail_pages_script_block_cannot_be_broken_out_of(client, hostile_asset):
    """The VALUE tab hands the asset's currency to JavaScript for the conversion
    preview, so that currency is interpolated into a <script> block."""
    body = client.get(f"/assets/{hostile_asset}?tab=value").text

    assert "var assetCurrency" in body
    assert SCRIPT_PAYLOAD not in body
    assert "\\u003c" in body


def test_snapshot_date_is_escaped(client, hostile_asset):
    """snapshot_date is free-form text, not a validated date."""
    body = client.post(
        f"/assets/{hostile_asset}/snapshots/add",
        data={"snapshot_date": "<b>pwn</b>", "value": "5"},
    ).text
    assert "<b>pwn</b>" not in body
    assert "&lt;b&gt;pwn" in body


# --- Same-origin enforcement ---


def test_cross_site_post_is_rejected(client, hostile_asset):
    response = client.post(
        f"/assets/{hostile_asset}/delete", headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert response.status_code == 403


def test_foreign_origin_is_rejected(client, hostile_asset):
    """Fallback path for browsers that do not send Sec-Fetch-Site."""
    response = client.request(
        "DELETE",
        f"/api/v1/assets/{hostile_asset}",
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_same_origin_post_is_allowed(client, hostile_asset):
    response = client.post(
        f"/assets/{hostile_asset}/snapshots/add",
        data={"snapshot_date": "2026-02-02", "value": "9"},
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert response.status_code == 200


def test_non_browser_client_is_allowed(client):
    """No Origin and no Sec-Fetch-Site: curl, the REST API, an MCP client."""
    assert (
        client.post("/api/v1/sheets", json={"name": "From a script"}).status_code == 200
    )


def test_safe_methods_are_never_blocked(client):
    assert client.get(
        "/assets", headers={"Sec-Fetch-Site": "cross-site"}
    ).status_code in (
        200,
        302,
    )


# --- Host checking ---
#
# The rule turns on names, not addresses: rebinding needs a hostname whose DNS
# the attacker controls, so every IP literal is safe to accept.


def test_unknown_hostname_is_rejected(client):
    """A name the attacker could point at loopback must not be answered."""
    response = client.get("/", headers={"Host": "evil.example"})
    assert response.status_code == 400
    # The error has to say how to fix it, or it reads as the app being broken.
    assert "ALLOWED_HOSTS" in response.text


@pytest.mark.parametrize(
    "host",
    [
        "0.0.0.0:8001",  # what uvicorn prints when bound to all interfaces
        "0.0.0.0",
        "127.0.0.1:8000",
        "192.168.1.5:8000",  # reached over the LAN
        "10.0.0.7",
        "[::1]:8000",  # IPv6 loopback, bracketed with a port
        "[::1]",
        "localhost:8000",
        "localhost",
        "networa.localhost",
    ],
)
def test_addresses_and_localhost_are_always_allowed(client, host):
    assert client.get("/", headers={"Host": host}).status_code in (200, 302)


def test_configured_hostname_is_allowed(monkeypatch, client):
    from app.config import settings

    monkeypatch.setattr(settings, "ALLOWED_HOSTS", ["networa.example.com"])
    assert client.get("/", headers={"Host": "networa.example.com"}).status_code in (
        200,
        302,
    )
    assert client.get("/", headers={"Host": "other.example.com"}).status_code == 400


def test_wildcard_subdomain_is_allowed(monkeypatch, client):
    from app.config import settings

    monkeypatch.setattr(settings, "ALLOWED_HOSTS", ["*.example.com"])
    for host in ("app.example.com", "example.com"):
        assert client.get("/", headers={"Host": host}).status_code in (200, 302)
    assert client.get("/", headers={"Host": "example.org"}).status_code == 400


def test_star_disables_the_check(monkeypatch, client):
    from app.config import settings

    monkeypatch.setattr(settings, "ALLOWED_HOSTS", ["*"])
    assert client.get("/", headers={"Host": "anything.example"}).status_code in (
        200,
        302,
    )


def test_hostname_parsing():
    from app.security import hostname_of

    assert hostname_of("0.0.0.0:8001") == "0.0.0.0"
    assert hostname_of("[::1]:8000") == "::1"
    assert hostname_of("::1") == "::1"
    assert hostname_of("Example.COM:443") == "example.com"
    assert hostname_of("  localhost  ") == "localhost"


# --- Upload limits ---


def test_oversized_csv_is_rejected(client):
    from app.routers.import_data import MAX_CSV_BYTES

    oversized = b"name,asset_class,value\n" + b"x,stock,1\n" * (
        MAX_CSV_BYTES // 10 + 1000
    )
    response = client.post(
        "/api/v1/import/assets-csv",
        files={"file": ("big.csv", oversized, "text/csv")},
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert response.status_code == 413


def test_non_utf8_csv_is_rejected(client):
    response = client.post(
        "/api/v1/import/assets-csv",
        files={"file": ("bad.csv", b"name\n\xff\xfe\x00binary", "text/csv")},
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert response.status_code == 400


# --- Open redirect ---


def test_display_currency_redirect_stays_on_this_app(client):
    response = client.post(
        "/settings/display-currency",
        data={"currency": "EUR"},
        headers={
            "Referer": "https://evil.example/phish",
            "Sec-Fetch-Site": "same-origin",
        },
        follow_redirects=False,
    )
    assert response.headers["location"] == "/phish"


def test_display_currency_redirect_rejects_protocol_relative(client):
    response = client.post(
        "/settings/display-currency",
        data={"currency": "USD"},
        headers={"Referer": "//evil.example", "Sec-Fetch-Site": "same-origin"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/"
