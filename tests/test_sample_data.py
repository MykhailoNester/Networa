"""Tests for first-run sample seeding.

The load-bearing property is the negative one: seeding must never touch a
database that already holds assets, because the default database is the user's
real one.

These drive the async services directly via ``asyncio.run`` rather than pulling
in pytest-asyncio. Each body must close the shared connection before its event
loop goes away, or a later test would inherit an aiosqlite handle bound to a
dead loop.
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from app import database
from app.config import settings
from app.services.sample_data import NOTE, maybe_seed_sample_data


def _on_fresh_db(tmp_path, monkeypatch, body: Callable[[Any], Coroutine]):
    """Run ``body(db)`` against a newly created, schema-only database."""
    monkeypatch.setattr(settings, "DATABASE_PATH", tmp_path / "fresh.db")
    monkeypatch.setattr(database, "_db", None)

    async def main():
        await database.init_db()
        try:
            return await body(await database.get_db())
        finally:
            await database.close_db()

    return asyncio.run(main())


async def _count(db, sql: str, params: tuple = ()) -> int:
    cursor = await db.execute(sql, params)
    row = await cursor.fetchone()
    return row[0]


def test_seeds_an_illustrative_portfolio(tmp_path, monkeypatch):
    async def body(db):
        assert await maybe_seed_sample_data() > 0
        # Assets, and a debt too, so assets-minus-liabilities is representable.
        assert (
            await _count(db, "SELECT COUNT(*) FROM assets WHERE category='asset'") > 0
        )
        assert await _count(db, "SELECT COUNT(*) FROM assets WHERE category='debt'") > 0
        # Several dates, so the trend chart draws a line rather than a dot.
        assert (
            await _count(db, "SELECT COUNT(DISTINCT snapshot_date) FROM snapshots") >= 2
        )
        assert await _count(db, "SELECT COUNT(*) FROM cashflows") > 0
        # Sheets give the assets somewhere to live.
        assert await _count(db, "SELECT COUNT(*) FROM sheets") > 0

    _on_fresh_db(tmp_path, monkeypatch, body)


def test_every_seeded_row_is_labelled(tmp_path, monkeypatch):
    """The user must be able to tell which rows are safe to delete."""

    async def body(db):
        await maybe_seed_sample_data()
        unlabelled = await _count(
            db,
            "SELECT COUNT(*) FROM assets WHERE notes IS NULL OR notes != ?",
            (NOTE,),
        )
        assert unlabelled == 0

    _on_fresh_db(tmp_path, monkeypatch, body)


def test_does_not_touch_a_database_that_already_has_assets(tmp_path, monkeypatch):
    async def body(db):
        await db.execute(
            """INSERT INTO assets (name, category, asset_class, value, value_usd)
               VALUES ('My real holding', 'asset', 'cash', 1234, 1234)"""
        )
        await db.commit()

        assert await maybe_seed_sample_data() == 0

        cursor = await db.execute("SELECT name FROM assets")
        assert [row["name"] for row in await cursor.fetchall()] == ["My real holding"]

    _on_fresh_db(tmp_path, monkeypatch, body)


def test_is_idempotent(tmp_path, monkeypatch):
    async def body(db):
        first = await maybe_seed_sample_data()
        assert first > 0
        # The second call sees a populated database and declines.
        assert await maybe_seed_sample_data() == 0
        assert await _count(db, "SELECT COUNT(*) FROM assets") == first

    _on_fresh_db(tmp_path, monkeypatch, body)


def test_seeded_values_are_positive_and_usd(tmp_path, monkeypatch):
    async def body(db):
        await maybe_seed_sample_data()
        assert await _count(db, "SELECT COUNT(*) FROM assets WHERE value_usd <= 0") == 0
        assert (
            await _count(db, "SELECT COUNT(*) FROM assets WHERE currency != 'USD'") == 0
        )

    _on_fresh_db(tmp_path, monkeypatch, body)
