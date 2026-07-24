from ..database import get_db
from .currency_service import convert_to_usd


async def list_cashflows(asset_id=None, from_date=None, to_date=None):
    db = await get_db()
    query = """
        SELECT cf.*, a.name AS asset_name
        FROM cashflows cf
        LEFT JOIN assets a ON cf.asset_id = a.id
        WHERE 1=1
    """
    params = []
    if asset_id:
        query += " AND cf.asset_id = ?"
        params.append(asset_id)
    if from_date:
        query += " AND cf.flow_date >= ?"
        params.append(from_date)
    if to_date:
        query += " AND cf.flow_date <= ?"
        params.append(to_date)
    query += " ORDER BY cf.flow_date DESC"
    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_cashflow(cashflow_id):
    db = await get_db()
    cursor = await db.execute(
        """SELECT cf.*, a.name AS asset_name
           FROM cashflows cf
           LEFT JOIN assets a ON cf.asset_id = a.id
           WHERE cf.id = ?""",
        (cashflow_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def create_cashflow(data: dict):
    db = await get_db()
    data["cash_in_usd"] = await convert_to_usd(
        data.get("cash_in", 0) or 0, data.get("cash_in_currency", "USD") or "USD"
    )
    data["cash_out_usd"] = await convert_to_usd(
        data.get("cash_out", 0) or 0, data.get("cash_out_currency", "USD") or "USD"
    )
    columns = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cursor = await db.execute(
        f"INSERT INTO cashflows ({columns}) VALUES ({placeholders})",
        list(data.values()),
    )
    await db.commit()
    row_id = cursor.lastrowid
    cursor = await db.execute(
        """SELECT cf.*, a.name AS asset_name
           FROM cashflows cf
           LEFT JOIN assets a ON cf.asset_id = a.id
           WHERE cf.id = ?""",
        (row_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("Cashflow not found immediately after insert")
    return dict(row)


async def update_cashflow(cashflow_id, data: dict):
    db = await get_db()
    existing = await get_cashflow(cashflow_id)
    if not existing:
        return None
    cash_in = data.get("cash_in", existing["cash_in"])
    cash_in_currency = data.get("cash_in_currency", existing["cash_in_currency"])
    cash_out = data.get("cash_out", existing["cash_out"])
    cash_out_currency = data.get("cash_out_currency", existing["cash_out_currency"])
    data["cash_in_usd"] = await convert_to_usd(cash_in or 0, cash_in_currency or "USD")
    data["cash_out_usd"] = await convert_to_usd(
        cash_out or 0, cash_out_currency or "USD"
    )
    set_clause = ", ".join(f"{k} = ?" for k in data)
    values = [*data.values(), cashflow_id]
    await db.execute(f"UPDATE cashflows SET {set_clause} WHERE id = ?", values)
    await db.commit()
    return await get_cashflow(cashflow_id)


async def delete_cashflow(cashflow_id):
    db = await get_db()
    await db.execute("DELETE FROM cashflows WHERE id = ?", (cashflow_id,))
    await db.commit()
    return {"status": "deleted"}


async def get_asset_cashflows(asset_id):
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM cashflows WHERE asset_id = ? ORDER BY flow_date ASC",
        (asset_id,),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_cashflow_summary(asset_id=None):
    db = await get_db()
    query = "SELECT SUM(cash_in_usd) AS total_in, SUM(cash_out_usd) AS total_out FROM cashflows WHERE 1=1"
    params = []
    if asset_id:
        query += " AND asset_id = ?"
        params.append(asset_id)
    cursor = await db.execute(query, params)
    row = await cursor.fetchone()
    total_in = row["total_in"] or 0
    total_out = row["total_out"] or 0
    return {"total_in": total_in, "total_out": total_out, "net": total_in - total_out}


async def get_sold_positions_summary():
    db = await get_db()
    cursor = await db.execute(
        """SELECT id, name, cash_in, cash_out
           FROM assets
           WHERE value = 0 AND cash_out > 0
           ORDER BY name"""
    )
    rows = await cursor.fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["realized_pnl"] = (d["cash_out"] or 0) - (d["cash_in"] or 0)
        result.append(d)
    return result
