from datetime import date, timedelta

from ..database import get_db

# Net worth is assets MINUS debts. Both live in the `assets` table, told apart
# by `category`, and a debt's value is stored as a positive number — so every
# aggregate that means "net worth" has to sign debt rows with -1. Aggregates
# that describe asset *composition* (allocation, investable, top holdings)
# stay assets-only on purpose; mixing liabilities into them would be wrong.
_SIGNED = "CASE WHEN a.category = 'debt' THEN -s.value_usd ELSE s.value_usd END"


async def _get_net_worth_at_date(db, ref_date: str) -> float | None:
    """Net worth as of a reference date: latest snapshot per active row up to
    that date, assets minus debts.

    Returns None only when nothing was snapshotted on or before ``ref_date``.
    A net worth that happens to be zero — or negative, when debts exceed
    assets — is a real answer and must not be conflated with "no data".
    """
    cursor = await db.execute(
        f"""
        SELECT COUNT(*) AS rows_found,
               COALESCE(SUM({_SIGNED}), 0) AS total
        FROM assets a
        JOIN (
            SELECT asset_id, value_usd
            FROM snapshots
            WHERE (asset_id, snapshot_date) IN (
                SELECT asset_id, MAX(snapshot_date)
                FROM snapshots WHERE snapshot_date <= ?
                GROUP BY asset_id
            )
        ) s ON a.id = s.asset_id
        WHERE a.is_active = 1
    """,
        (ref_date,),
    )
    row = await cursor.fetchone()
    if row and row["rows_found"]:
        return float(row["total"])
    return None


async def take_snapshot(snapshot_date: str | None = None) -> dict:
    """Legacy: create point-in-time snapshots for every row. Kept for API compatibility.

    Debts are snapshotted too — filtering them out froze liability balances while
    every asset advanced. ``assets_snapshot`` keeps its name for compatibility but
    now counts every row written, debts included.
    """
    db = await get_db()
    if not snapshot_date:
        snapshot_date = date.today().isoformat()  # noqa: DTZ011 - local calendar date

    from ..services.currency_service import convert_to_usd

    try:
        cursor = await db.execute(
            "SELECT id, value, currency, value_usd, category FROM assets WHERE is_active = 1"
        )
        rows = await cursor.fetchall()

        total_assets = 0.0
        total_debts = 0.0
        count = 0

        for row in rows:
            value_usd = row["value_usd"]
            if value_usd == 0 and row["currency"] != "USD":
                value_usd = await convert_to_usd(row["value"], row["currency"])

            await db.execute(
                """INSERT OR REPLACE INTO snapshots (snapshot_date, asset_id, value, currency, value_usd)
                   VALUES (?, ?, ?, ?, ?)""",
                (snapshot_date, row["id"], row["value"], row["currency"], value_usd),
            )
            if row["category"] == "debt":
                total_debts += value_usd
            else:
                total_assets += value_usd
            count += 1

        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return {
        "date": snapshot_date,
        "assets_snapshot": count,
        "total_assets": total_assets,
        "total_debts": total_debts,
        "net_worth": total_assets - total_debts,
    }


def _dates_cte(date_filters: str) -> str:
    """Every date carrying a snapshot for any active row — debts included.

    A date where the user recorded only a mortgage payment is a real point on
    the net-worth curve; filtering the date list to asset snapshots would drop
    it from the chart entirely.
    """
    return f"""
        dates AS (
            SELECT DISTINCT s.snapshot_date
            FROM snapshots s
            JOIN assets a ON s.asset_id = a.id
            WHERE a.is_active = 1
            {date_filters}
        )
    """


async def get_net_worth_history(
    from_date: str | None = None, to_date: str | None = None
) -> list[dict]:
    """Net worth history using as-of-date aggregation.

    For each date that has any snapshot, net worth is the sum of the LATEST
    known value for EVERY active row up to that date, with debts subtracted.
    This prevents spiky lines caused by missing snapshots: if a row's value
    wasn't updated on a given date, its most recent previous value is carried
    forward.
    """
    db = await get_db()

    date_filters = ""
    params: list = []
    if from_date:
        date_filters += " AND s.snapshot_date >= ?"
        params.append(from_date)
    if to_date:
        date_filters += " AND s.snapshot_date <= ?"
        params.append(to_date)

    # For each distinct snapshot date, sum the latest-known value per active row
    query = f"""
        WITH {_dates_cte(date_filters)},
        latest_as_of AS (
            SELECT
                d.snapshot_date,
                a.id AS asset_id,
                a.category,
                a.investable,
                (
                    SELECT s2.value_usd
                    FROM snapshots s2
                    WHERE s2.asset_id = a.id
                      AND s2.snapshot_date <= d.snapshot_date
                    ORDER BY s2.snapshot_date DESC
                    LIMIT 1
                ) AS value_usd
            FROM dates d
            CROSS JOIN assets a
            WHERE a.is_active = 1
        )
        SELECT
            snapshot_date,
            COALESCE(SUM(CASE WHEN category = 'debt' THEN 0 ELSE value_usd END), 0) AS total_assets_usd,
            COALESCE(SUM(CASE WHEN category = 'debt' THEN value_usd ELSE 0 END), 0) AS total_debts_usd,
            COALESCE(SUM(CASE WHEN category = 'debt' THEN -value_usd ELSE value_usd END), 0) AS net_worth_usd
        FROM latest_as_of
        WHERE value_usd IS NOT NULL
        GROUP BY snapshot_date
        ORDER BY snapshot_date
    """

    cursor = await db.execute(query, params)
    rows = [dict(row) for row in await cursor.fetchall()]

    # Investable breakdown per date (same as-of-date logic). Investable is an
    # asset-side concept, so this half stays filtered to category='asset' —
    # only the date list is shared with the net-worth series above.
    inv_query = f"""
        WITH {_dates_cte(date_filters)}
        SELECT
            d.snapshot_date,
            a.investable,
            SUM(
                (SELECT s2.value_usd FROM snapshots s2
                 WHERE s2.asset_id = a.id AND s2.snapshot_date <= d.snapshot_date
                 ORDER BY s2.snapshot_date DESC LIMIT 1)
            ) AS total
        FROM dates d
        CROSS JOIN assets a
        WHERE a.is_active = 1 AND a.category = 'asset'
              AND a.investable LIKE 'investable%'
        GROUP BY d.snapshot_date, a.investable
        HAVING total IS NOT NULL
    """
    cursor = await db.execute(inv_query, params)
    inv_by_date: dict[str, dict[str, float]] = {}
    for inv_row in await cursor.fetchall():
        d = inv_row["snapshot_date"]
        if d not in inv_by_date:
            inv_by_date[d] = {}
        if inv_row["total"] is not None:
            inv_by_date[d][inv_row["investable"]] = float(inv_row["total"])

    for row in rows:
        row["investable_breakdown"] = inv_by_date.get(row["snapshot_date"], {})

    return rows


async def get_current_net_worth() -> dict:
    db = await get_db()

    # Latest snapshot value per active row (fallback to assets.value_usd if no snapshot)
    cursor = await db.execute("""
        SELECT a.id, a.category, a.investable, a.sheet_id, a.asset_class, a.name,
               COALESCE(snap.value_usd, a.value_usd) as current_value_usd
        FROM assets a
        LEFT JOIN (
            SELECT asset_id, value_usd
            FROM snapshots
            WHERE (asset_id, snapshot_date) IN (
                SELECT asset_id, MAX(snapshot_date) FROM snapshots GROUP BY asset_id
            )
        ) snap ON a.id = snap.asset_id
        WHERE a.is_active = 1
    """)
    all_rows = list(await cursor.fetchall())
    # The composition breakdowns below are asset-side views, so they iterate
    # asset_rows; only the headline totals see debts.
    asset_rows = [row for row in all_rows if row["category"] != "debt"]
    debt_rows = [row for row in all_rows if row["category"] == "debt"]

    total_assets = sum((row["current_value_usd"] or 0) for row in asset_rows)
    total_debts = sum((row["current_value_usd"] or 0) for row in debt_rows)
    net_worth = total_assets - total_debts

    # Allocation by class
    cursor = await db.execute("SELECT name, display_name, color FROM asset_classes")
    class_info = {
        row["name"]: {"display_name": row["display_name"], "color": row["color"]}
        for row in await cursor.fetchall()
    }
    allocation_by_class: dict = {}
    for row in asset_rows:
        val = row["current_value_usd"] or 0
        if val <= 0:
            continue
        cls = row["asset_class"] or "miscellaneous"
        info = class_info.get(cls, {"display_name": cls, "color": "#888"})
        if cls not in allocation_by_class:
            allocation_by_class[cls] = {
                "total": 0,
                "display_name": info["display_name"] or cls,
                "color": info["color"] or "#888",
            }
        allocation_by_class[cls]["total"] += val
    allocation_by_class = dict(
        sorted(allocation_by_class.items(), key=lambda x: -x[1]["total"])
    )

    # Allocation by sheet
    cursor = await db.execute("SELECT id, name FROM sheets")
    sheet_names = {row["id"]: row["name"] for row in await cursor.fetchall()}
    allocation_by_sheet: dict = {}
    for row in asset_rows:
        val = row["current_value_usd"] or 0
        if val <= 0:
            continue
        sname = sheet_names.get(row["sheet_id"]) or "Unassigned"
        allocation_by_sheet[sname] = allocation_by_sheet.get(sname, 0) + val
    allocation_by_sheet = dict(sorted(allocation_by_sheet.items(), key=lambda x: -x[1]))

    # Investable breakdown
    investable_by_type: dict = {}
    for row in asset_rows:
        inv = row["investable"] or ""
        if not inv.startswith("investable"):
            continue
        val = row["current_value_usd"] or 0
        investable_by_type[inv] = investable_by_type.get(inv, 0) + val
    investable_assets = sum(investable_by_type.values())
    non_investable_assets = total_assets - investable_assets

    assets_count = len(asset_rows)
    debts_count = len(debt_rows)

    # Largest debts, for the dashboard liabilities card and its breakdown
    debts_by_name = {
        row["name"]: row["current_value_usd"] or 0
        for row in sorted(debt_rows, key=lambda r: -(r["current_value_usd"] or 0))
        if (row["current_value_usd"] or 0) > 0
    }

    # YTD change from snapshot as-of Jan 1
    today = date.today()  # noqa: DTZ011 - local calendar date
    ytd_start = await _get_net_worth_at_date(db, f"{today.year}-01-01")
    if ytd_start is not None:
        ytd_change = net_worth - ytd_start
        # A percentage against a zero or negative starting net worth is
        # meaningless (and sign-flipped), so report the absolute change only.
        ytd_change_pct = (ytd_change / ytd_start) * 100 if ytd_start > 0 else None
    else:
        ytd_change = None
        ytd_change_pct = None

    return {
        "net_worth": net_worth,
        "total_assets": total_assets,
        "total_debts": total_debts,
        "investable_assets": investable_assets,
        "investable_by_type": investable_by_type,
        "non_investable_assets": non_investable_assets,
        "allocation_by_class": allocation_by_class,
        "allocation_by_sheet": allocation_by_sheet,
        "debts_by_name": debts_by_name,
        "assets_count": assets_count,
        "debts_count": debts_count,
        "ytd_change": ytd_change,
        "ytd_change_pct": ytd_change_pct,
    }


async def get_period_returns() -> dict:
    db = await get_db()
    today = date.today()  # noqa: DTZ011 - local calendar date

    nw_data = await get_current_net_worth()
    current = nw_data["net_worth"]
    # Test the portfolio, not the total: with debts subtracted a net worth of
    # zero is a legitimate figure, whereas an empty portfolio has no returns.
    if not nw_data["assets_count"] and not nw_data["debts_count"]:
        return {}

    def pct(ref: float | None) -> float | None:
        # Only meaningful against a positive reference — see the ytd_change_pct
        # note in get_current_net_worth().
        if ref is not None and ref > 0 and ref != current:
            return (current - ref) / ref * 100
        return None

    ytd_ref = await _get_net_worth_at_date(db, f"{today.year}-01-01")
    mtd_ref = await _get_net_worth_at_date(
        db, date(today.year, today.month, 1).isoformat()
    )
    qm = ((today.month - 1) // 3) * 3 + 1
    qtd_ref = await _get_net_worth_at_date(db, date(today.year, qm, 1).isoformat())
    try:
        one_year_ref = await _get_net_worth_at_date(
            db, today.replace(year=today.year - 1).isoformat()
        )
    except ValueError:
        one_year_ref = await _get_net_worth_at_date(
            db, (today - timedelta(days=365)).isoformat()
        )

    # All-time: net worth at the very first snapshot date
    cursor = await db.execute("""
        SELECT MIN(s.snapshot_date) as first_date
        FROM snapshots s
        JOIN assets a ON s.asset_id = a.id
        WHERE a.is_active = 1
    """)
    first_row = await cursor.fetchone()
    alltime_ref = None
    if first_row and first_row["first_date"]:
        alltime_ref = await _get_net_worth_at_date(db, first_row["first_date"])

    def chg(ref: float | None) -> float | None:
        return round(current - ref, 2) if ref is not None else None

    return {
        "mtd": pct(mtd_ref),
        "qtd": pct(qtd_ref),
        "ytd": pct(ytd_ref),
        "one_year": pct(one_year_ref),
        "all_time": pct(alltime_ref),
        "mtd_change": chg(mtd_ref),
        "qtd_change": chg(qtd_ref),
        "ytd_change": chg(ytd_ref),
        "one_year_change": chg(one_year_ref),
        "all_time_change": chg(alltime_ref),
    }


async def get_top_movers(days: int = 30, limit: int = 5) -> list[dict]:
    db = await get_db()
    ref_date = (date.today() - timedelta(days=days)).isoformat()  # noqa: DTZ011 - local calendar date

    cursor = await db.execute(
        """
        WITH latest AS (
            SELECT asset_id, value_usd, snapshot_date
            FROM snapshots
            WHERE (asset_id, snapshot_date) IN (
                SELECT asset_id, MAX(snapshot_date) FROM snapshots GROUP BY asset_id
            )
        ),
        ref AS (
            SELECT asset_id, value_usd, snapshot_date
            FROM snapshots
            WHERE (asset_id, snapshot_date) IN (
                SELECT asset_id, MAX(snapshot_date)
                FROM snapshots WHERE snapshot_date <= ?
                GROUP BY asset_id
            )
        )
        SELECT
            a.name,
            a.category,
            latest.value_usd  AS current_val,
            ref.value_usd     AS ref_val,
            latest.snapshot_date AS current_date,
            ref.snapshot_date    AS ref_date,
            -- Movement in NET WORTH terms: a shrinking debt moves net worth up,
            -- so a debt's contribution is the negation of its value change.
            CASE WHEN a.category = 'debt'
                 THEN ref.value_usd - latest.value_usd
                 ELSE latest.value_usd - ref.value_usd END AS change_val,
            -- Denominated by the magnitude of the reference value, so the sign
            -- of the percentage matches the sign of change_val for debts too.
            CASE WHEN ref.value_usd != 0
                 THEN (CASE WHEN a.category = 'debt'
                            THEN ref.value_usd - latest.value_usd
                            ELSE latest.value_usd - ref.value_usd END)
                      / ABS(ref.value_usd) * 100
                 ELSE NULL END AS change_pct
        FROM assets a
        JOIN latest ON a.id = latest.asset_id
        JOIN ref    ON a.id = ref.asset_id
        WHERE a.is_active = 1
          AND latest.snapshot_date > ref.snapshot_date
        ORDER BY ABS(change_val) DESC
        LIMIT ?
    """,
        (ref_date, limit),
    )

    return [dict(row) for row in await cursor.fetchall()]


async def get_period_contributors(period_key: str) -> list[dict]:
    """Per-asset gain/loss for a given period (ytd, qtd, mtd, one_year, all_time)."""
    db = await get_db()
    today = date.today()  # noqa: DTZ011 - local calendar date

    ref_date: str | None
    if period_key == "ytd":
        ref_date = f"{today.year}-01-01"
    elif period_key == "mtd":
        ref_date = date(today.year, today.month, 1).isoformat()
    elif period_key == "qtd":
        qm = ((today.month - 1) // 3) * 3 + 1
        ref_date = date(today.year, qm, 1).isoformat()
    elif period_key == "one_year":
        try:
            ref_date = today.replace(year=today.year - 1).isoformat()
        except ValueError:
            ref_date = (today - timedelta(days=365)).isoformat()
    elif period_key == "all_time":
        cursor = await db.execute("""
            SELECT MIN(s.snapshot_date) FROM snapshots s
            JOIN assets a ON s.asset_id = a.id
            WHERE a.is_active = 1
        """)
        row = await cursor.fetchone()
        ref_date = row[0] if row and row[0] else None
    else:
        return []

    if not ref_date:
        return []

    cursor = await db.execute("""
        SELECT a.id, a.name, a.asset_class, a.category,
               COALESCE(snap.value_usd, a.value_usd) AS current_val
        FROM assets a
        LEFT JOIN (
            SELECT asset_id, value_usd FROM snapshots
            WHERE (asset_id, snapshot_date) IN (
                SELECT asset_id, MAX(snapshot_date) FROM snapshots GROUP BY asset_id
            )
        ) snap ON a.id = snap.asset_id
        WHERE a.is_active = 1
    """)
    current_rows = {row["id"]: dict(row) for row in await cursor.fetchall()}

    cursor = await db.execute(
        """
        SELECT asset_id, value_usd FROM snapshots
        WHERE (asset_id, snapshot_date) IN (
            SELECT asset_id, MAX(snapshot_date)
            FROM snapshots WHERE snapshot_date <= ?
            GROUP BY asset_id
        )
    """,
        (ref_date,),
    )
    ref_vals = {
        row["asset_id"]: float(row["value_usd"]) for row in await cursor.fetchall()
    }

    results = []
    for asset_id, asset in current_rows.items():
        is_debt = asset["category"] == "debt"
        current_val = float(asset["current_val"] or 0)
        ref_val = ref_vals.get(asset_id, 0)
        delta = current_val - ref_val
        # Contribution to NET WORTH: paying a mortgage down shrinks the debt and
        # so lifts net worth. Signing debts this way keeps the contributor list
        # summing to the period's net-worth change.
        change = -delta if is_debt else delta
        if abs(change) < 0.01:
            continue
        results.append(
            {
                "name": asset["name"],
                "asset_class": asset["asset_class"] or "miscellaneous",
                "category": asset["category"],
                "current_val": current_val,
                "ref_val": ref_val,
                "change": round(change, 2),
                "change_pct": round(change / abs(ref_val) * 100, 2)
                if ref_val != 0
                else None,
            }
        )

    results.sort(key=lambda x: -abs(x["change"]))
    return results


async def get_top_assets_by_value(limit: int = 10) -> list[dict]:
    """Largest holdings. Assets only — this is a composition view, so its
    percentages are denominated by gross assets, not by net worth."""
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT a.name, a.asset_class,
               COALESCE(snap.value_usd, a.value_usd) AS current_value_usd
        FROM assets a
        LEFT JOIN (
            SELECT asset_id, value_usd FROM snapshots
            WHERE (asset_id, snapshot_date) IN (
                SELECT asset_id, MAX(snapshot_date) FROM snapshots GROUP BY asset_id
            )
        ) snap ON a.id = snap.asset_id
        WHERE a.is_active = 1 AND a.category = 'asset'
          AND COALESCE(snap.value_usd, a.value_usd) > 0
        ORDER BY current_value_usd DESC
        LIMIT ?
    """,
        (limit,),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def get_assets_by_class_summary() -> list[dict]:
    """Asset allocation by class. Assets only, for the same reason as
    get_top_assets_by_value() — liabilities are not an asset class."""
    db = await get_db()
    cursor = await db.execute("""
        SELECT
            COALESCE(a.asset_class, 'miscellaneous') AS asset_class,
            COALESCE(ac.display_name, a.asset_class, 'Misc') AS display_name,
            COALESCE(ac.color, '#888') AS color,
            COUNT(*) AS count,
            SUM(COALESCE(snap.value_usd, a.value_usd)) AS total_value
        FROM assets a
        LEFT JOIN asset_classes ac ON ac.name = a.asset_class
        LEFT JOIN (
            SELECT asset_id, value_usd FROM snapshots
            WHERE (asset_id, snapshot_date) IN (
                SELECT asset_id, MAX(snapshot_date) FROM snapshots GROUP BY asset_id
            )
        ) snap ON a.id = snap.asset_id
        WHERE a.is_active = 1 AND a.category = 'asset'
        GROUP BY a.asset_class
        ORDER BY total_value DESC
    """)
    return [dict(row) for row in await cursor.fetchall()]
