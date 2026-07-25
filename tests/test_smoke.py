"""Smoke tests: the app boots and its core pages render (against a demo-db copy)."""

import pytest
from fastapi.testclient import TestClient

from app import create_app


@pytest.fixture
def client():
    with TestClient(create_app(), follow_redirects=True) as c:
        yield c


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/assets",
        "/assets/1",
        "/debts",
        "/cashflows",
        "/import",
        "/exchange-rates",
        "/sheets",
        "/breakdown/networth",
    ],
)
def test_core_pages_render(client, path):
    response = client.get(path)
    assert response.status_code == 200, f"{path} returned {response.status_code}"
