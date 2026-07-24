"""
Seed demo.db with realistic portfolio data.

Usage:
    python scripts/seed_demo.py

Creates data/demo.db — never touches data/networth.db.
Run the app in demo mode with: DB_NAME=demo.db python main.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Must be set BEFORE any app module is imported so settings.DATABASE_PATH
# evaluates to data/demo.db the first time app.config is loaded.
os.environ["DB_NAME"] = "demo.db"

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import close_db, get_db, init_db

# ── Constants ─────────────────────────────────────────────────────────────────

# 20 monthly snapshot dates: Jun 2023 → Jan 2025 (inclusive)
MONTHS = [
    "2023-06-01",
    "2023-07-01",
    "2023-08-01",
    "2023-09-01",
    "2023-10-01",
    "2023-11-01",
    "2023-12-01",
    "2024-01-01",
    "2024-02-01",
    "2024-03-01",
    "2024-04-01",
    "2024-05-01",
    "2024-06-01",
    "2024-07-01",
    "2024-08-01",
    "2024-09-01",
    "2024-10-01",
    "2024-11-01",
    "2024-12-01",
    "2025-01-01",
]

SHEETS = [
    ("Investments", 0),
    ("Real Estate", 1),
    ("Cash & Savings", 2),
    ("Crypto", 3),
]

# Each asset: dict with name, category, asset_class, sheet, section,
# currency, ticker, investable, cash_in, and a list of 20 USD values
# aligned to MONTHS. Value of 0 means the asset didn't exist yet that month.
ASSETS = [
    {
        "name": "S&P 500 Index Fund (VFIAX)",
        "category": "asset",
        "asset_class": "fund",
        "sheet": "Investments",
        "section": "US Equities",
        "currency": "USD",
        "ticker": "VFIAX",
        "investable": "investable",
        "cash_in": 92000,
        "values": [
            82000,
            84500,
            86000,
            87200,
            88500,
            91000,
            95000,
            97000,
            99500,
            102000,
            105000,
            108000,
            111000,
            115000,
            119000,
            122000,
            126000,
            130000,
            138000,
            145000,
        ],
    },
    {
        "name": "Apple Inc (AAPL)",
        "category": "asset",
        "asset_class": "stock",
        "sheet": "Investments",
        "section": "US Equities",
        "currency": "USD",
        "ticker": "AAPL",
        "investable": "investable",
        "cash_in": 28000,
        "values": [
            24000,
            25500,
            27000,
            27800,
            26500,
            28000,
            30000,
            30500,
            31000,
            32500,
            34000,
            33500,
            35000,
            36000,
            37000,
            36500,
            37500,
            38500,
            38000,
            38000,
        ],
    },
    {
        "name": "Microsoft Corp (MSFT)",
        "category": "asset",
        "asset_class": "stock",
        "sheet": "Investments",
        "section": "US Equities",
        "currency": "USD",
        "ticker": "MSFT",
        "investable": "investable",
        "cash_in": 38000,
        # Purchased Jan 2024 — first 7 months are 0
        "values": [
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            38000,
            39000,
            40500,
            41000,
            41500,
            42000,
            42500,
            41000,
            41500,
            42000,
            43000,
            43500,
            42000,
        ],
    },
    {
        "name": "Emerging Markets ETF (VWO)",
        "category": "asset",
        "asset_class": "fund",
        "sheet": "Investments",
        "section": "International",
        "currency": "USD",
        "ticker": "VWO",
        "investable": "investable",
        "cash_in": 10000,
        # Initial purchase Dec 2023, large addition Dec 2024
        "values": [
            0,
            0,
            0,
            0,
            0,
            0,
            10000,
            10200,
            10500,
            10800,
            11000,
            11200,
            11500,
            11800,
            12000,
            12200,
            12500,
            13000,
            14000,
            22000,
        ],
    },
    {
        "name": "Primary Residence",
        "category": "asset",
        "asset_class": "real_estate",
        "sheet": "Real Estate",
        "section": "Properties",
        "currency": "USD",
        "ticker": None,
        "investable": "non_investable",
        "cash_in": 350000,
        "values": [
            395000,
            396000,
            397000,
            398000,
            399000,
            400000,
            402000,
            403000,
            404000,
            406000,
            407000,
            408000,
            410000,
            412000,
            413000,
            415000,
            416000,
            417000,
            419000,
            420000,
        ],
    },
    {
        "name": "Vacation Rental Property",
        "category": "asset",
        "asset_class": "real_estate",
        "sheet": "Real Estate",
        "section": "Properties",
        "currency": "USD",
        "ticker": None,
        "investable": "investable_illiquid",
        "cash_in": 160000,
        "values": [
            168000,
            169000,
            170000,
            171000,
            172000,
            173000,
            174000,
            175000,
            176000,
            177000,
            178000,
            179000,
            180000,
            181000,
            182000,
            183000,
            183500,
            184000,
            184500,
            185000,
        ],
    },
    {
        "name": "Chase Checking",
        "category": "asset",
        "asset_class": "cash",
        "sheet": "Cash & Savings",
        "section": "Checking",
        "currency": "USD",
        "ticker": None,
        "investable": "investable",
        "cash_in": 18500,
        "values": [
            12000,
            13500,
            14200,
            15000,
            16500,
            17000,
            18500,
            19000,
            17500,
            16000,
            18000,
            19500,
            18000,
            17500,
            19000,
            18500,
            19000,
            18000,
            19500,
            18500,
        ],
    },
    {
        "name": "Ally High-Yield Savings",
        "category": "asset",
        "asset_class": "cash",
        "sheet": "Cash & Savings",
        "section": "Savings",
        "currency": "USD",
        "ticker": None,
        "investable": "investable",
        "cash_in": 32000,
        "values": [
            15000,
            16000,
            17500,
            18000,
            20000,
            21000,
            22500,
            24000,
            25500,
            26000,
            27000,
            28000,
            29000,
            30000,
            30500,
            31000,
            31500,
            32000,
            32000,
            32000,
        ],
    },
    {
        "name": "Emergency Fund CD",
        "category": "asset",
        "asset_class": "cash",
        "sheet": "Cash & Savings",
        "section": "Savings",
        "currency": "USD",
        "ticker": None,
        "investable": "investable",
        "cash_in": 15000,
        "values": [
            15000,
            15050,
            15100,
            15150,
            15200,
            15250,
            15300,
            15350,
            15400,
            15450,
            15500,
            15550,
            15600,
            15650,
            15700,
            15750,
            15800,
            15850,
            15900,
            15000,
        ],
    },
    {
        "name": "Bitcoin (BTC)",
        "category": "asset",
        "asset_class": "crypto",
        "sheet": "Crypto",
        "section": "Crypto",
        "currency": "USD",
        "ticker": "BTC",
        "investable": "investable",
        "cash_in": 20000,
        "values": [
            14000,
            15000,
            16500,
            17000,
            16000,
            18000,
            20000,
            22000,
            21000,
            23000,
            25000,
            27000,
            24000,
            26000,
            28000,
            30000,
            29000,
            27000,
            30000,
            28000,
        ],
    },
    {
        "name": "Ethereum (ETH)",
        "category": "asset",
        "asset_class": "crypto",
        "sheet": "Crypto",
        "section": "Crypto",
        "currency": "USD",
        "ticker": "ETH",
        "investable": "investable",
        "cash_in": 8000,
        "values": [
            5500,
            6000,
            6800,
            7200,
            6500,
            7000,
            7500,
            8000,
            7800,
            8200,
            8800,
            9200,
            8500,
            9000,
            9500,
            10000,
            9800,
            9200,
            10000,
            9500,
        ],
    },
    # Debts
    {
        "name": "Mortgage — Primary Residence",
        "category": "debt",
        "asset_class": "real_estate",
        "sheet": "Real Estate",
        "section": "Liabilities",
        "currency": "USD",
        "ticker": None,
        "investable": "non_investable",
        "cash_in": 0,
        "values": [
            296000,
            295400,
            294800,
            294200,
            293600,
            293000,
            292400,
            291800,
            291200,
            290600,
            290000,
            289400,
            288800,
            288200,
            287600,
            287000,
            286400,
            285800,
            285200,
            285000,
        ],
    },
    {
        "name": "Home Equity Line of Credit",
        "category": "debt",
        "asset_class": "miscellaneous",
        "sheet": "Real Estate",
        "section": "Liabilities",
        "currency": "USD",
        "ticker": None,
        "investable": "non_investable",
        "cash_in": 0,
        "values": [
            20000,
            19800,
            19600,
            19400,
            19200,
            19000,
            18800,
            18600,
            18400,
            18200,
            18000,
            17800,
            17600,
            17400,
            17200,
            17000,
            16800,
            16600,
            16400,
            18500,
        ],
    },
]

# (asset_name, flow_date, description, cash_in, cash_in_usd, cash_out, cash_out_usd, currency)
CASHFLOWS = [
    (
        "S&P 500 Index Fund (VFIAX)",
        "2023-06-15",
        "Initial investment",
        80000,
        80000,
        0,
        0,
        "USD",
    ),
    (
        "Apple Inc (AAPL)",
        "2023-07-01",
        "Purchase AAPL 200 shares @ $140",
        28000,
        28000,
        0,
        0,
        "USD",
    ),
    (
        "Bitcoin (BTC)",
        "2023-09-10",
        "BTC purchase — 0.8 BTC @ $25K",
        20000,
        20000,
        0,
        0,
        "USD",
    ),
    (
        "Ally High-Yield Savings",
        "2023-11-20",
        "Year-end savings transfer",
        15000,
        15000,
        0,
        0,
        "USD",
    ),
    (
        "Microsoft Corp (MSFT)",
        "2024-01-15",
        "Purchase MSFT 120 shares @ $317",
        38000,
        38000,
        0,
        0,
        "USD",
    ),
    (
        "Vacation Rental Property",
        "2024-04-05",
        "Rental income Q1 2024",
        3600,
        3600,
        0,
        0,
        "USD",
    ),
    (
        "S&P 500 Index Fund (VFIAX)",
        "2024-07-15",
        "DCA addition",
        12000,
        12000,
        0,
        0,
        "USD",
    ),
    (
        "Emerging Markets ETF (VWO)",
        "2024-12-20",
        "Year-end rebalance into EM",
        10000,
        10000,
        0,
        0,
        "USD",
    ),
]

# (from_currency, rate, rate_date)  — rate is USD value of 1 unit of from_currency
EXCHANGE_RATES = [
    # EUR/USD
    ("EUR", 1.0701, "2023-06-01"),
    ("EUR", 1.0998, "2023-07-01"),
    ("EUR", 1.0986, "2023-08-01"),
    ("EUR", 1.0581, "2023-09-01"),
    ("EUR", 1.0573, "2023-10-01"),
    ("EUR", 1.0833, "2023-11-01"),
    ("EUR", 1.1049, "2023-12-01"),
    ("EUR", 1.0844, "2024-01-01"),
    ("EUR", 1.0769, "2024-02-01"),
    ("EUR", 1.0856, "2024-03-01"),
    ("EUR", 1.0723, "2024-04-01"),
    ("EUR", 1.0847, "2024-05-01"),
    ("EUR", 1.0734, "2024-06-01"),
    ("EUR", 1.0870, "2024-07-01"),
    ("EUR", 1.0997, "2024-08-01"),
    ("EUR", 1.1073, "2024-09-01"),
    ("EUR", 1.0921, "2024-10-01"),
    ("EUR", 1.0592, "2024-11-01"),
    ("EUR", 1.0503, "2024-12-01"),
    ("EUR", 1.0427, "2025-01-01"),
    # GBP/USD
    ("GBP", 1.2722, "2023-06-01"),
    ("GBP", 1.2849, "2023-07-01"),
    ("GBP", 1.2700, "2023-08-01"),
    ("GBP", 1.2196, "2023-09-01"),
    ("GBP", 1.2128, "2023-10-01"),
    ("GBP", 1.2533, "2023-11-01"),
    ("GBP", 1.2729, "2023-12-01"),
    ("GBP", 1.2698, "2024-01-01"),
    ("GBP", 1.2637, "2024-02-01"),
    ("GBP", 1.2714, "2024-03-01"),
    ("GBP", 1.2530, "2024-04-01"),
    ("GBP", 1.2700, "2024-05-01"),
    ("GBP", 1.2640, "2024-06-01"),
    ("GBP", 1.2849, "2024-07-01"),
    ("GBP", 1.3120, "2024-08-01"),
    ("GBP", 1.3195, "2024-09-01"),
    ("GBP", 1.2975, "2024-10-01"),
    ("GBP", 1.2693, "2024-11-01"),
    ("GBP", 1.2574, "2024-12-01"),
    ("GBP", 1.2500, "2025-01-01"),
    # BTC/USD (price of 1 BTC in USD)
    ("BTC", 25000.0, "2023-06-01"),
    ("BTC", 29200.0, "2023-07-01"),
    ("BTC", 26000.0, "2023-08-01"),
    ("BTC", 26800.0, "2023-09-01"),
    ("BTC", 34200.0, "2023-10-01"),
    ("BTC", 37400.0, "2023-11-01"),
    ("BTC", 42700.0, "2023-12-01"),
    ("BTC", 42800.0, "2024-01-01"),
    ("BTC", 51800.0, "2024-02-01"),
    ("BTC", 71200.0, "2024-03-01"),
    ("BTC", 63900.0, "2024-04-01"),
    ("BTC", 61400.0, "2024-05-01"),
    ("BTC", 60700.0, "2024-06-01"),
    ("BTC", 57700.0, "2024-07-01"),
    ("BTC", 59400.0, "2024-08-01"),
    ("BTC", 64600.0, "2024-09-01"),
    ("BTC", 60500.0, "2024-10-01"),
    ("BTC", 96400.0, "2024-11-01"),
    ("BTC", 97600.0, "2024-12-01"),
    ("BTC", 97900.0, "2025-01-01"),
]


# ── Seed logic ────────────────────────────────────────────────────────────────


async def seed():
    print("Seeding demo.db ...")
    await init_db()
    db = await get_db()

    # 1. Sheets
    sheet_ids: dict[str, int] = {}
    for name, sort_order in SHEETS:
        await db.execute(
            "INSERT OR IGNORE INTO sheets (name, sort_order) VALUES (?, ?)",
            (name, sort_order),
        )
    await db.commit()
    async with db.execute("SELECT id, name FROM sheets") as cur:
        async for row in cur:
            sheet_ids[row["name"]] = row["id"]

    # 2. Assets
    asset_ids: dict[str, int] = {}
    for a in ASSETS:
        current_value = a["values"][-1]  # Jan 2025 value
        await db.execute(
            """
            INSERT OR IGNORE INTO assets
                (name, category, asset_class, sheet_id, section_name,
                 currency, value, value_usd, ticker, investable,
                 cash_in, cash_in_currency, is_manual, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'USD', 1, 1)
            """,
            (
                a["name"],
                a["category"],
                a["asset_class"],
                sheet_ids[a["sheet"]],
                a["section"],
                a["currency"],
                current_value,
                current_value,
                a["ticker"],
                a["investable"],
                a["cash_in"],
            ),
        )
    await db.commit()
    async with db.execute("SELECT id, name FROM assets") as cur:
        async for row in cur:
            asset_ids[row["name"]] = row["id"]

    # 3. Snapshots — one per asset per month (skip if value == 0)
    snapshot_count = 0
    for a in ASSETS:
        aid = asset_ids[a["name"]]
        for i, month in enumerate(MONTHS):
            val = a["values"][i]
            if val == 0:
                continue
            await db.execute(
                """
                INSERT OR IGNORE INTO snapshots
                    (asset_id, snapshot_date, value, currency, value_usd)
                VALUES (?, ?, ?, 'USD', ?)
                """,
                (aid, month, val, val),
            )
            snapshot_count += 1
    await db.commit()

    # 4. Net worth history — aggregate from value lists per month
    nwh_count = 0
    for i, month in enumerate(MONTHS):
        total_assets = sum(
            a["values"][i]
            for a in ASSETS
            if a["category"] == "asset" and a["values"][i] > 0
        )
        total_debts = sum(
            a["values"][i]
            for a in ASSETS
            if a["category"] == "debt" and a["values"][i] > 0
        )
        investable_total = sum(
            a["values"][i]
            for a in ASSETS
            if a["category"] == "asset"
            and a["investable"] in ("investable", "investable_illiquid")
            and a["values"][i] > 0
        )
        net_worth = total_assets - total_debts
        await db.execute(
            """
            INSERT OR IGNORE INTO net_worth_history
                (snapshot_date, total_assets_usd, total_debts_usd, net_worth_usd, investable_total_usd)
            VALUES (?, ?, ?, ?, ?)
            """,
            (month, total_assets, total_debts, net_worth, investable_total),
        )
        nwh_count += 1
    await db.commit()

    # 5. Cashflows
    for (
        asset_name,
        flow_date,
        description,
        cash_in,
        cash_in_usd,
        cash_out,
        cash_out_usd,
        currency,
    ) in CASHFLOWS:
        aid = asset_ids.get(asset_name)
        await db.execute(
            """
            INSERT INTO cashflows
                (asset_id, asset_name, flow_date, description,
                 cash_in, cash_in_currency, cash_in_usd,
                 cash_out, cash_out_currency, cash_out_usd,
                 status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Active')
            """,
            (
                aid,
                asset_name,
                flow_date,
                description,
                cash_in,
                currency,
                cash_in_usd,
                cash_out,
                currency,
                cash_out_usd,
            ),
        )
    await db.commit()

    # 6. Exchange rates
    for from_currency, rate, rate_date in EXCHANGE_RATES:
        await db.execute(
            """
            INSERT OR IGNORE INTO exchange_rates
                (from_currency, to_currency, rate, rate_date)
            VALUES (?, 'USD', ?, ?)
            """,
            (from_currency, rate, rate_date),
        )
    await db.commit()

    # Summary
    final_nw = sum(a["values"][-1] for a in ASSETS if a["category"] == "asset") - sum(
        a["values"][-1] for a in ASSETS if a["category"] == "debt"
    )
    print(f"  Sheets:         {len(sheet_ids)}")
    print(f"  Assets:         {len(asset_ids)}")
    print(f"  Snapshots:      {snapshot_count}")
    print(f"  NW history:     {nwh_count} months")
    print(f"  Cashflows:      {len(CASHFLOWS)}")
    print(f"  Exchange rates: {len(EXCHANGE_RATES)}")
    print(f"  Net worth (Jan 2025): ${final_nw:,.0f}")
    print()
    print("Done. Run the app with:")
    print("  DB_NAME=demo.db python main.py")

    await close_db()


if __name__ == "__main__":
    asyncio.run(seed())
