from ..database import get_db


async def get_setting(key: str, default: str = "") -> str:
    db = await get_db()
    cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row["value"] if row else default


async def set_setting(key: str, value: str):
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        (key, value),
    )
    await db.commit()
