from datetime import date

from ..database import get_db
from ..models import AssetCreate, AssetUpdate

# Subquery to get latest snapshot value per asset
_LATEST_SNAP_JOIN = """
LEFT JOIN (
    SELECT asset_id, value_usd as snap_value_usd
    FROM snapshots
    WHERE (asset_id, snapshot_date) IN (
        SELECT asset_id, MAX(snapshot_date) FROM snapshots GROUP BY asset_id
    )
) latest_snap ON a.id = latest_snap.asset_id
"""


def _row_to_dict(row) -> dict | None:
    return dict(row) if row else None


def _enrich(d: dict) -> dict:
    d["gain_loss"] = _calc_gain_loss(d)
    d["gain_loss_pct"] = _calc_gain_loss_pct(d)
    d["holding_period_days"] = _calc_holding_period(d)
    d["estimated_tax"] = _calc_estimated_tax(d)
    return d


async def list_assets(
    category: str | None = None,
    sheet_id: int | None = None,
    asset_class: str | None = None,
    active_only: bool = True,
) -> list[dict]:
    db = await get_db()
    query = f"""
        SELECT a.*, s.name as sheet_name,
               COALESCE(latest_snap.snap_value_usd, a.value_usd) as current_value_usd
        FROM assets a
        LEFT JOIN sheets s ON a.sheet_id = s.id
        {_LATEST_SNAP_JOIN}
        WHERE 1=1
    """
    params: list[str | int] = []
    if active_only:
        query += " AND a.is_active = 1"
    if category:
        query += " AND a.category = ?"
        params.append(category)
    if sheet_id:
        query += " AND a.sheet_id = ?"
        params.append(sheet_id)
    if asset_class:
        query += " AND a.asset_class = ?"
        params.append(asset_class)
    query += " ORDER BY s.sort_order, a.sort_order, a.name"
    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [_enrich(dict(row)) for row in rows]


async def get_asset(asset_id: int) -> dict | None:
    db = await get_db()
    cursor = await db.execute(
        f"""SELECT a.*, s.name as sheet_name,
                   COALESCE(latest_snap.snap_value_usd, a.value_usd) as current_value_usd
            FROM assets a
            LEFT JOIN sheets s ON a.sheet_id = s.id
            {_LATEST_SNAP_JOIN}
            WHERE a.id = ?""",
        (asset_id,),
    )
    row = await cursor.fetchone()
    if row:
        return _enrich(dict(row))
    return None


async def create_asset(data: AssetCreate) -> dict:
    db = await get_db()
    d = data.model_dump()
    from ..services import currency_service

    if d["currency"] != "USD":
        d["value_usd"] = await currency_service.convert_to_usd(
            d["value"], d["currency"]
        )
    elif d["value_usd"] == 0:
        d["value_usd"] = d["value"]
    columns = ", ".join(d.keys())
    placeholders = ", ".join(["?"] * len(d))
    cursor = await db.execute(
        f"INSERT INTO assets ({columns}) VALUES ({placeholders})",
        list(d.values()),
    )
    await db.commit()
    if cursor.lastrowid is None:
        raise RuntimeError("Asset insert did not return a row id")
    asset = await get_asset(cursor.lastrowid)
    if asset is None:
        raise RuntimeError("Asset not found immediately after insert")
    return asset


async def update_asset(asset_id: int, data: AssetUpdate) -> dict | None:
    db = await get_db()
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        return await get_asset(asset_id)

    # Recompute value_usd whenever value or currency changes
    if "value" in updates or "currency" in updates:
        current = await get_asset(asset_id)
        if current:
            new_value = updates.get("value", current["value"])
            new_currency = updates.get("currency", current["currency"])
            from ..services import currency_service

            updates["value_usd"] = await currency_service.convert_to_usd(
                new_value, new_currency
            )

    updates["updated_at"] = "CURRENT_TIMESTAMP"
    set_clause = ", ".join(
        f"{k} = CURRENT_TIMESTAMP" if k == "updated_at" else f"{k} = ?" for k in updates
    )
    values = [v for k, v in updates.items() if k != "updated_at"]
    values.append(asset_id)
    await db.execute(f"UPDATE assets SET {set_clause} WHERE id = ?", values)
    await db.commit()
    return await get_asset(asset_id)


async def delete_asset(asset_id: int) -> bool:
    db = await get_db()
    await db.execute(
        "UPDATE assets SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (asset_id,),
    )
    await db.commit()
    return True


async def get_asset_classes() -> list[dict]:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM asset_classes ORDER BY display_name")
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


def _calc_gain_loss(asset: dict) -> float | None:
    # Use latest snapshot value (current_value_usd) for accurate gain/loss
    value = asset.get("current_value_usd") or asset.get("value_usd") or 0
    cost = asset.get("cost_basis") or asset.get("cash_in") or 0
    if cost != 0:
        # Only compare when cost is denominated in USD
        if asset.get("cost_basis_currency") not in (None, "USD"):
            return None
        return value - cost
    # Fall back to stored unrealized_gain when no cost basis is set
    if asset.get("unrealized_gain") is not None:
        return asset["unrealized_gain"]
    return None


def _calc_gain_loss_pct(asset: dict) -> float | None:
    gain = _calc_gain_loss(asset)
    if gain is None:
        return None
    cost = asset.get("cost_basis") or asset.get("cash_in") or 0
    if cost == 0:
        return None
    return (gain / abs(cost)) * 100


def _calc_holding_period(asset: dict) -> int | None:
    purchase_date = asset.get("purchase_date")
    if not purchase_date:
        return None
    try:
        pd = date.fromisoformat(str(purchase_date)[:10])
        return (date.today() - pd).days  # noqa: DTZ011 - local calendar date
    except (ValueError, TypeError):
        return None


def _calc_estimated_tax(asset: dict) -> float | None:
    gain = _calc_gain_loss(asset)
    tax_rate = asset.get("tax_rate")
    if gain is None or tax_rate is None:
        return None
    return gain * tax_rate / 100
