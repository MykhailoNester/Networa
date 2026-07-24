from pathlib import Path

import aiosqlite

from .config import settings

# Canonical schema (tables, indexes, and seed rows). Single source of truth —
# applied idempotently on startup; there is no migrations directory.
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        settings.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _db = await aiosqlite.connect(str(settings.DATABASE_PATH))
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def init_db() -> None:
    """Create the schema and seed reference data if missing (idempotent)."""
    db = await get_db()
    await db.executescript(SCHEMA_PATH.read_text())
    await db.commit()


async def close_db() -> None:
    """Close the shared connection (used on app shutdown and by scripts)."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None
