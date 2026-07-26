"""First-run sample data.

A brand-new database is completely empty, which makes the dashboard look broken
rather than new: no assets, no allocation, and an empty net-worth chart. This
seeds a small illustrative portfolio the first time the app starts against an
empty database, so the UI has something to show.

It is deliberately *small* and clearly labelled — every row carries a
"Sample data" note so it is obvious what to delete once real holdings go in.
The rich dataset behind the README screenshots is a different thing entirely:
that lives in the committed ``data/demo.db``, built by ``scripts/seed_demo.py``.

Seeding is skipped whenever the database already holds any asset, so it never
touches an existing portfolio, and can be turned off outright with
``SEED_SAMPLE_DATA=0``.
"""

from datetime import date

from ..database import get_db

NOTE = "Sample data — safe to delete."

# (name, class, sheet, section, value_usd, investable, ticker, quantity, cash_in)
_ASSETS: tuple[tuple, ...] = (
    (
        "Global Index Fund (VTI)",
        "fund",
        "Investments",
        "Equities",
        24_000,
        "investable",
        "VTI",
        80,
        18_000,
    ),
    (
        "Bitcoin (BTC)",
        "crypto",
        "Investments",
        "Digital",
        4_500,
        "investable",
        "BTC",
        0.05,
        3_000,
    ),
    (
        "Everyday Checking",
        "cash",
        "Cash & Savings",
        "Checking",
        3_200,
        "investable",
        None,
        None,
        3_200,
    ),
    (
        "Savings Buffer",
        "cash",
        "Cash & Savings",
        "Savings",
        12_000,
        "investable",
        None,
        None,
        12_000,
    ),
    (
        "Apartment",
        "real_estate",
        "Property",
        "Properties",
        180_000,
        "non_investable",
        None,
        None,
        150_000,
    ),
)

# Liabilities are modelled the same way, with category='debt'.
_DEBTS: tuple[tuple, ...] = (
    ("Mortgage — Apartment", "real_estate", "Property", "Liabilities", 96_000),
)

_CASHFLOWS: tuple[tuple, ...] = (
    ("Global Index Fund (VTI)", "Monthly contribution", 5, 1_500),
    ("Bitcoin (BTC)", "Initial purchase", 4, 3_000),
    ("Savings Buffer", "Bonus set aside", 2, 2_000),
)

# Month-by-month multipliers, oldest first, so the trend chart has a real line
# instead of a single point. Ends at 1.0 = today's stated value.
_TREND = (0.90, 0.93, 0.95, 0.97, 0.99, 1.0)


def _months_back(months: int) -> str:
    """First-of-month date `months` before the current month, as YYYY-MM-DD."""
    today = date.today()  # noqa: DTZ011 - local calendar date
    month_index = today.year * 12 + (today.month - 1) - months
    return date(month_index // 12, month_index % 12 + 1, 1).isoformat()


async def maybe_seed_sample_data() -> int:
    """Seed the illustrative portfolio if this database has no assets yet.

    Returns the number of assets created (0 when seeding was skipped).
    """
    db = await get_db()

    cursor = await db.execute("SELECT 1 FROM assets LIMIT 1")
    if await cursor.fetchone() is not None:
        return 0

    sheet_ids: dict[str, int] = {}
    for order, name in enumerate(("Investments", "Cash & Savings", "Property")):
        await db.execute(
            "INSERT OR IGNORE INTO sheets (name, sort_order) VALUES (?, ?)",
            (name, order),
        )
        cursor = await db.execute("SELECT id FROM sheets WHERE name = ?", (name,))
        row = await cursor.fetchone()
        if row is not None:
            sheet_ids[name] = row["id"]

    asset_ids: dict[str, int] = {}

    for (
        name,
        asset_class,
        sheet,
        section,
        value,
        investable,
        ticker,
        quantity,
        cash_in,
    ) in _ASSETS:
        cursor = await db.execute(
            """INSERT INTO assets (
                   name, category, asset_class, sheet_id, section_name,
                   value, currency, value_usd, ticker, quantity,
                   cash_in, investable, notes
               ) VALUES (?, 'asset', ?, ?, ?, ?, 'USD', ?, ?, ?, ?, ?, ?)""",
            (
                name,
                asset_class,
                sheet_ids.get(sheet),
                section,
                value,
                value,
                ticker,
                quantity,
                cash_in,
                investable,
                NOTE,
            ),
        )
        if cursor.lastrowid is not None:
            asset_ids[name] = cursor.lastrowid

    for name, asset_class, sheet, section, value in _DEBTS:
        cursor = await db.execute(
            """INSERT INTO assets (
                   name, category, asset_class, sheet_id, section_name,
                   value, currency, value_usd, investable, notes
               ) VALUES (?, 'debt', ?, ?, ?, ?, 'USD', ?, 'non_investable', ?)""",
            (name, asset_class, sheet_ids.get(sheet), section, value, value, NOTE),
        )
        if cursor.lastrowid is not None:
            asset_ids[name] = cursor.lastrowid

    # A snapshot series per asset, so the net-worth trend and per-asset value
    # charts both have history to draw.
    current_values = {row[0]: row[4] for row in _ASSETS}
    current_values.update({row[0]: row[4] for row in _DEBTS})

    for name, asset_id in asset_ids.items():
        base = current_values[name]
        for months_ago, factor in enumerate(reversed(_TREND)):
            value = round(base * factor, 2)
            await db.execute(
                """INSERT OR IGNORE INTO snapshots
                       (snapshot_date, asset_id, value, currency, value_usd)
                   VALUES (?, ?, ?, 'USD', ?)""",
                (_months_back(months_ago), asset_id, value, value),
            )

    for asset_name, description, months_ago, amount in _CASHFLOWS:
        await db.execute(
            """INSERT INTO cashflows (
                   asset_id, asset_name, description, flow_date, notes,
                   cash_in, cash_in_currency, cash_in_usd, status
               ) VALUES (?, ?, ?, ?, ?, ?, 'USD', ?, 'Active')""",
            (
                asset_ids.get(asset_name),
                asset_name,
                description,
                _months_back(months_ago),
                NOTE,
                amount,
                amount,
            ),
        )

    await db.commit()
    return len(_ASSETS) + len(_DEBTS)
