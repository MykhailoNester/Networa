import csv
import io
import re

from ..database import get_db
from ..services.currency_service import convert_to_usd

# Accepted asset classes for the assets CSV (see docs/import-format.md).
VALID_ASSET_CLASSES = {
    "real_estate",
    "precious_metal",
    "cash",
    "stock",
    "fund",
    "crypto",
    "vehicle",
    "investment",
    "miscellaneous",
}


def _normalize_row(row: dict) -> dict:
    """Lower-case and strip CSV header keys so column matching is case-insensitive."""
    normalized = {}
    for key, value in row.items():
        if key is None:
            continue
        normalized[key.strip().lower()] = value
    return normalized


def _parse_optional_float(value) -> float | None:
    """Parse an optional numeric cell, returning None when blank."""
    if value is None or not str(value).strip():
        return None
    return _parse_float(str(value))


async def import_assets_csv(content: str) -> dict:
    """Import assets from the generic assets CSV format (see docs/import-format.md).

    Columns: name (required), asset_class (required), value (required),
    currency, category, sheet, section, ticker, quantity, price,
    cost_basis, cost_basis_currency, notes.
    """
    db = await get_db()
    stats = {"assets_created": 0, "sheets_created": 0, "skipped": 0}

    # Cache of sheet name -> id, populated lazily and auto-created when new.
    sheet_map: dict[str, int] = {}

    async def resolve_sheet_id(sheet_name: str) -> int | None:
        sheet_name = (sheet_name or "").strip()
        if not sheet_name:
            return None
        if sheet_name in sheet_map:
            return sheet_map[sheet_name]
        cursor = await db.execute("SELECT id FROM sheets WHERE name = ?", (sheet_name,))
        existing = await cursor.fetchone()
        if existing:
            sheet_map[sheet_name] = existing["id"]
            return existing["id"]
        cursor = await db.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM sheets"
        )
        order_row = await cursor.fetchone()
        next_order = order_row["next_order"] if order_row else 0
        cursor = await db.execute(
            "INSERT INTO sheets (name, sort_order) VALUES (?, ?)",
            (sheet_name, next_order),
        )
        new_id = cursor.lastrowid
        if new_id is None:
            raise RuntimeError("Sheet insert did not return a row id")
        sheet_map[sheet_name] = new_id
        stats["sheets_created"] += 1
        return new_id

    reader = csv.DictReader(io.StringIO(content))
    for raw_row in reader:
        row = _normalize_row(raw_row)

        name = (row.get("name") or "").strip()
        asset_class = (row.get("asset_class") or "").strip().lower().replace(" ", "_")
        value_raw = row.get("value")

        # Required fields
        if (
            not name
            or not asset_class
            or value_raw is None
            or not str(value_raw).strip()
        ):
            stats["skipped"] += 1
            continue

        if asset_class not in VALID_ASSET_CLASSES:
            asset_class = "miscellaneous"

        value_amount = _parse_float(str(value_raw))
        currency = (row.get("currency") or "USD").strip().upper() or "USD"

        category = (row.get("category") or "asset").strip().lower() or "asset"
        if category not in ("asset", "debt"):
            category = "asset"

        # Other tools export liabilities as negatives. Storing that sign would
        # negate it again on aggregation and *raise* net worth.
        if category == "debt":
            value_amount = abs(value_amount)

        value_usd = await convert_to_usd(value_amount, currency)

        sheet_id = await resolve_sheet_id(row.get("sheet") or "")
        section_name = (row.get("section") or "").strip() or None
        ticker = (row.get("ticker") or "").strip() or None
        quantity = _parse_optional_float(row.get("quantity"))
        price = _parse_optional_float(row.get("price"))
        price_currency = currency if price is not None else None
        cost_basis = _parse_optional_float(row.get("cost_basis"))
        cost_basis_currency = (
            row.get("cost_basis_currency") or "USD"
        ).strip().upper() or "USD"
        notes = (row.get("notes") or "").strip() or None

        await db.execute(
            """INSERT INTO assets (
                name, category, asset_class, sheet_id, section_name,
                value, currency, value_usd,
                ticker, quantity, price, price_currency,
                cost_basis, cost_basis_currency, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name,
                category,
                asset_class,
                sheet_id,
                section_name,
                value_amount,
                currency,
                value_usd,
                ticker,
                quantity,
                price,
                price_currency,
                cost_basis,
                cost_basis_currency,
                notes,
            ),
        )
        stats["assets_created"] += 1

    await db.commit()
    return stats


async def import_cashflow_csv(content: str) -> dict:
    """Import cash flow entries from the generic cashflows CSV format.

    Columns: date (required, YYYY-MM-DD), asset (matched to an existing active
    asset by name), cash_in / cash_out (bare number or "USD 65.25" form),
    currency, description, notes, status. See docs/import-format.md.
    """
    db = await get_db()
    stats = {"entries_created": 0, "skipped": 0}

    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        flow_date = row.get("Date", "")
        if not flow_date:
            stats["skipped"] += 1
            continue

        # Parse "USD 65.25" style amounts as well as bare numbers.
        cash_in, cash_in_cur = _parse_currency_amount(row.get("Cash In", ""))
        cash_out, cash_out_cur = _parse_currency_amount(row.get("Cash Out", ""))

        # USD columns
        cash_in_usd = _parse_float(row.get("Cash In (USD)", "0"))
        cash_out_usd = _parse_float(row.get("Cash Out (USD)", "0"))

        # Try to find matching asset
        asset_name = row.get("Asset", "")
        asset_id = None
        if asset_name:
            cursor = await db.execute(
                "SELECT id FROM assets WHERE name = ? AND is_active = 1 LIMIT 1",
                (asset_name,),
            )
            asset_row = await cursor.fetchone()
            if asset_row:
                asset_id = asset_row["id"]

        await db.execute(
            """INSERT INTO cashflows (
                asset_id, asset_name, symbol, location, description,
                flow_date, notes, cash_in, cash_in_currency, cash_in_usd,
                cash_out, cash_out_currency, cash_out_usd, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                asset_id,
                asset_name,
                row.get("Symbol", ""),
                row.get("Location", ""),
                row.get("Description", ""),
                flow_date,
                row.get("Notes", ""),
                cash_in,
                cash_in_cur,
                cash_in_usd,
                cash_out,
                cash_out_cur,
                cash_out_usd,
                row.get("Status", "Active"),
            ),
        )
        stats["entries_created"] += 1

    await db.commit()
    return stats


def _parse_currency_amount(value: str) -> tuple[float, str]:
    if not value or not value.strip():
        return 0.0, "USD"
    value = value.strip()
    match = re.match(r"^([A-Z]{3})\s+([\d,.-]+)$", value)
    if match:
        currency = match.group(1)
        amount = _parse_float(match.group(2))
        return amount, currency
    return _parse_float(value), "USD"


def _parse_float(value: str) -> float:
    if not value or not value.strip():
        return 0.0
    cleaned = value.strip().replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0
