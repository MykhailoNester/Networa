"""Schema-application tests.

``init_db()`` re-applies app/schema.sql on every startup, so it has to be
genuinely idempotent — not merely non-destructive. It previously bumped
sqlite_sequence each run, which left the database file modified just from
launching the app; for the committed data/demo.db that showed up as a dirty
working tree, one `git add` away from republishing it.
"""

import asyncio
import hashlib
import sqlite3

from app import database
from app.config import settings


def _open_close(path):
    """Apply the schema once and close cleanly, checkpointing the WAL."""

    async def main():
        await database.init_db()
        await database.close_db()

    asyncio.run(main())
    for sidecar in ("-wal", "-shm"):
        sibling = path.with_name(path.name + sidecar)
        if sibling.exists():
            sibling.unlink()


def _digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_reapplying_the_schema_does_not_modify_the_file(tmp_path, monkeypatch):
    db_path = tmp_path / "stable.db"
    monkeypatch.setattr(settings, "DATABASE_PATH", db_path)
    monkeypatch.setattr(database, "_db", None)

    _open_close(db_path)
    first = _digest(db_path)

    for _ in range(3):
        monkeypatch.setattr(database, "_db", None)
        _open_close(db_path)

    assert _digest(db_path) == first, (
        "init_db() changed the database file on a no-op run"
    )


def test_seed_rows_are_not_duplicated_or_renumbered(tmp_path, monkeypatch):
    db_path = tmp_path / "classes.db"
    monkeypatch.setattr(settings, "DATABASE_PATH", db_path)
    monkeypatch.setattr(database, "_db", None)

    for _ in range(3):
        monkeypatch.setattr(database, "_db", None)
        _open_close(db_path)

    con = sqlite3.connect(db_path)
    assert con.execute("SELECT COUNT(*) FROM asset_classes").fetchone()[0] == 9
    assert [
        r[0] for r in con.execute("SELECT id FROM asset_classes ORDER BY id")
    ] == list(range(1, 10))
    # The AUTOINCREMENT counter must not creep upward on repeat application.
    seq = dict(con.execute("SELECT name, seq FROM sqlite_sequence").fetchall())
    assert seq.get("asset_classes") == 9
    con.close()
