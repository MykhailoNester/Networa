import json
import math
from collections.abc import Collection
from datetime import UTC, date, datetime, timedelta

import aiosqlite

from ..database import get_db
from . import currency_service, market_service, settings_service

# Assets and debts share the `assets` table, told apart by `category`, and a
# debt's value is stored positive — so anything meaning "net worth" signs debt
# rows with -1, while anything describing asset *composition* stays assets-only.
_SIGNED = "CASE WHEN a.category = 'debt' THEN -s.value_usd ELSE s.value_usd END"

# The value each row was last known to have.
_LATEST_PER_ASSET = """
    SELECT asset_id, value_usd, snapshot_date
    FROM snapshots
    WHERE (asset_id, snapshot_date) IN (
        SELECT asset_id, MAX(snapshot_date) FROM snapshots GROUP BY asset_id
    )
"""

# The same, as of a reference date. Consumes one positional parameter — mind the
# placeholder order when interpolating it alongside others.
_LATEST_PER_ASSET_AS_OF = """
    SELECT asset_id, value_usd, snapshot_date
    FROM snapshots
    WHERE (asset_id, snapshot_date) IN (
        SELECT asset_id, MAX(snapshot_date)
        FROM snapshots WHERE snapshot_date <= ?
        GROUP BY asset_id
    )
"""

# Rows the price path may touch: an active *asset* (never a debt — a
# liability's balance is an amortisation schedule, not quantity x market
# price) carrying both a ticker and a non-zero quantity.
_PRICEABLE = """
    a.is_active = 1 AND a.category = 'asset'
    AND a.ticker IS NOT NULL AND TRIM(a.ticker) <> ''
    AND a.quantity IS NOT NULL AND a.quantity <> 0
"""

# Shared by the batch's SQL-filtered skip branch and revalue_asset_from_market's
# own guard below, so both callers report a debt the identical way.
_LIABILITY_SKIP_REASON = "liability — valued by balance, not by market price"

# Written unconditionally by every refresh_all_prices call — the manual
# button, the JSON API, and the daily job (run_daily_valuation calls this
# function too) all funnel through here, so this is a single source for "when
# did a refresh last run", not "when did something last change".
SETTING_PRICES_REFRESHED_AT = "prices_last_refreshed_at"


async def stamp_prices_refreshed() -> None:
    """Record that a market price was fetched just now.

    Lives here rather than at each call site so the batch refresh, the JSON
    API, the daily job and the per-asset "Auto" button all write the one
    format the dashboard's freshness line parses. Uses the same
    ``datetime.now(tz=UTC).astimezone()`` basis as ``app/scheduler.py``.
    """
    await settings_service.set_setting(
        SETTING_PRICES_REFRESHED_AT,
        datetime.now(tz=UTC).astimezone().strftime("%Y-%m-%d %H:%M"),
    )


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
        JOIN ({_LATEST_PER_ASSET_AS_OF}) s ON a.id = s.asset_id
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


def _price_outcome(
    asset_id: int,
    name: str,
    ticker: str,
    symbol: str | None,
    status: str,
    detail: str,
    *,
    source: str = "market",
    value_usd: float | None = None,
    value_native: float | None = None,
    currency: str = "USD",
) -> dict:
    """Shape shared by every per-asset outcome the price and FX passes report."""
    return {
        "asset_id": asset_id,
        "name": name,
        "ticker": ticker,
        "symbol": symbol,
        "status": status,
        "source": source,
        "detail": detail,
        "value_usd": value_usd,
        "value_native": value_native,
        "currency": currency,
    }


async def revalue_asset_from_market(
    db: aiosqlite.Connection, asset: dict, price_date: str
) -> dict:
    """Reprice one ticker-bearing asset and write its snapshot + cache.

    Behaviour-preserving lift of the market-price branch that used to live in
    ``app/routers/assets.py``'s add-auto handler, so both the manual button and
    the batch share one implementation. Writes and commits immediately — one
    asset per transaction — so the fetch above never leaves an open write for
    the next asset's network call to wait behind.
    """
    asset_id = asset["id"]
    name = asset["name"]
    ticker = (asset["ticker"] or "").strip()
    quantity = asset["quantity"]
    asset_currency = asset["currency"] or "USD"

    if asset.get("category") == "debt":
        # The batch's _PRICEABLE SQL filter already keeps a debt row out of the
        # loop that calls this function, but the manual per-asset "Auto" button
        # (app/routers/assets.py's snapshot_add_auto) has no such filter and can
        # reach a debt directly — e.g. one given a ticker/quantity via CSV
        # import. The guard has to live here too so the invariant holds for
        # both callers, not just the batch.
        return _price_outcome(
            asset_id,
            name,
            ticker,
            ticker or None,
            "skipped",
            _LIABILITY_SKIP_REASON,
            currency=asset_currency,
        )

    symbol = market_service.resolve_symbol(ticker, asset.get("asset_class"))

    try:
        price_data = await market_service.fetch_ticker_price(symbol, price_date)
        if price_data is None and symbol != ticker:
            # A crypto-flavoured ticker that is really an equity (GBTC) has no
            # -USD pair; retry with what the user actually typed.
            retry_data = await market_service.fetch_ticker_price(ticker, price_date)
            if retry_data is not None:
                symbol = ticker
                price_data = retry_data

        if price_data is None:
            return _price_outcome(
                asset_id,
                name,
                ticker,
                symbol,
                "failed",
                f"no price returned for {symbol}",
                currency=asset_currency,
            )

        price, price_currency = price_data
        # A delisted ticker returning 0 (or a negative/NaN) must not overwrite a
        # real holding with a zero snapshot — leave the previous value alone.
        if not math.isfinite(price) or price <= 0:
            return _price_outcome(
                asset_id,
                name,
                ticker,
                symbol,
                "failed",
                f"non-positive price from {symbol}",
                currency=asset_currency,
            )

        price_in_usd = await currency_service.convert_to_usd(price, price_currency)
        value_usd = round(price_in_usd * quantity, 2)

        if asset_currency == "USD":
            value_native = value_usd
            price_native = price_in_usd
        else:
            rate = await currency_service.get_rate(asset_currency, "USD")
            value_native = round(value_usd / rate, 4) if rate else value_usd
            price_native = (
                price
                if price_currency == asset_currency
                else (round(price_in_usd / rate, 6) if rate else price_in_usd)
            )

        await db.execute(
            """UPDATE assets SET price = ?, price_currency = ?, value = ?, value_usd = ?,
               updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (price_native, asset_currency, value_native, value_usd, asset_id),
        )
        await db.execute(
            """INSERT OR REPLACE INTO snapshots
               (snapshot_date, asset_id, value, currency, value_usd)
               VALUES (?, ?, ?, ?, ?)""",
            (price_date, asset_id, value_native, asset_currency, value_usd),
        )
        await db.commit()

        return _price_outcome(
            asset_id,
            name,
            ticker,
            symbol,
            "updated",
            f"{symbol} @ {price_in_usd:.4f} USD",
            value_usd=value_usd,
            value_native=value_native,
            currency=asset_currency,
        )
    except Exception as exc:  # noqa: BLE001 - one bad row must not abort a batch
        # Same pattern as take_snapshot above: a failure between the UPDATE and
        # the commit must not leave a dangling write on the shared connection
        # for the next asset's commit() in the batch loop to silently flush.
        await db.rollback()
        return _price_outcome(
            asset_id,
            name,
            ticker,
            symbol,
            "failed",
            f"{type(exc).__name__}: {exc}",
            currency=asset_currency,
        )


async def refresh_all_prices(price_date: str | None = None) -> dict:
    """Reprice every active, ticker-and-quantity-bearing asset.

    Writes only ``snapshots`` and the ``assets`` price/value cache, and never
    for a ``category = 'debt'`` row — a liability's balance is not
    ``quantity x market price``. USD is the denomination of every ``value_usd``
    in the report. One failing ticker is reported ``failed`` and does not stop
    the rest of the run.
    """
    db = await get_db()
    if not price_date:
        price_date = date.today().isoformat()  # noqa: DTZ011 - local calendar date

    cursor = await db.execute(f"""
        SELECT a.id, a.name, a.category, a.ticker, a.quantity, a.currency, a.asset_class,
               CASE WHEN {_PRICEABLE} THEN 1 ELSE 0 END AS priceable
        FROM assets a
        WHERE a.is_active = 1
        ORDER BY a.id
    """)
    rows = [dict(row) for row in await cursor.fetchall()]

    outcomes = []
    for row in rows:
        ticker = (row["ticker"] or "").strip()
        if row["priceable"]:
            outcomes.append(await revalue_asset_from_market(db, row, price_date))
        elif row["category"] == "debt":
            outcomes.append(
                _price_outcome(
                    row["id"],
                    row["name"],
                    ticker,
                    ticker or None,
                    "skipped",
                    _LIABILITY_SKIP_REASON,
                    currency=row["currency"] or "USD",
                )
            )
        elif not ticker:
            outcomes.append(
                _price_outcome(
                    row["id"],
                    row["name"],
                    ticker,
                    None,
                    "skipped",
                    "no ticker",
                    currency=row["currency"] or "USD",
                )
            )
        else:
            outcomes.append(
                _price_outcome(
                    row["id"],
                    row["name"],
                    ticker,
                    ticker,
                    "skipped",
                    "no quantity",
                    currency=row["currency"] or "USD",
                )
            )

    # Stamped whether or not anything actually moved (an empty portfolio, or a
    # run that only hit skips/failures, still counts as "a refresh happened
    # just now") — this is the dashboard's only source for prices staleness,
    # and a silent no-op refresh is exactly the case carry-forward would
    # otherwise hide.
    await stamp_prices_refreshed()

    return {
        "price_date": price_date,
        "updated": sum(1 for o in outcomes if o["status"] == "updated"),
        "skipped": sum(1 for o in outcomes if o["status"] == "skipped"),
        "failed": sum(1 for o in outcomes if o["status"] == "failed"),
        "outcomes": outcomes,
    }


async def reconvert_foreign_currency_rows(
    price_date: str | None = None,
    *,
    skip_asset_ids: Collection[int] | None = None,
) -> dict:
    """Reconvert every non-USD active row's cached USD value at the latest rate.

    A debt is included and its ``value`` is written positive, unchanged — signing
    belongs to the aggregates (``_SIGNED``), not to this write. No network call
    happens here (rates are already saved in the DB), so the whole pass is one
    transaction.
    """
    db = await get_db()
    if not price_date:
        price_date = date.today().isoformat()  # noqa: DTZ011 - local calendar date
    skip = set(skip_asset_ids or ())

    cursor = await db.execute("""
        SELECT id, name, category, currency, value FROM assets
        WHERE is_active = 1 AND currency <> 'USD'
        ORDER BY id
    """)
    rows = [dict(row) for row in await cursor.fetchall()]

    outcomes = []
    for row in rows:
        asset_id = row["id"]
        if asset_id in skip:
            continue
        value_usd = round(
            await currency_service.convert_to_usd(row["value"], row["currency"]), 2
        )
        await db.execute(
            "UPDATE assets SET value_usd = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (value_usd, asset_id),
        )
        await db.execute(
            """INSERT OR REPLACE INTO snapshots
               (snapshot_date, asset_id, value, currency, value_usd)
               VALUES (?, ?, ?, ?, ?)""",
            (price_date, asset_id, row["value"], row["currency"], value_usd),
        )
        outcomes.append(
            _price_outcome(
                asset_id,
                row["name"],
                "",
                None,
                "updated",
                f"reconverted at the latest {row['currency']}→USD rate",
                source="fx",
                value_usd=value_usd,
                value_native=row["value"],
                currency=row["currency"],
            )
        )

    await db.commit()
    return {
        "price_date": price_date,
        "reconverted": len(outcomes),
        "outcomes": outcomes,
    }


async def write_net_worth_history(day: str | None = None) -> dict:
    """Write today's assets-minus-debts row into ``net_worth_history``.

    Uses the chart's own as-of basis (``_LATEST_PER_ASSET_AS_OF``) so this row
    can never disagree with ``get_net_worth_history``'s curve. When nothing was
    ever snapshotted on or before ``day``, writes nothing — a row of zeros would
    assert "net worth is zero", which is exactly the confusion
    ``_get_net_worth_at_date`` exists to avoid. ``INSERT OR REPLACE`` so a
    second run the same day corrects the row rather than duplicating it.
    """
    db = await get_db()
    if not day:
        day = date.today().isoformat()  # noqa: DTZ011 - local calendar date

    cursor = await db.execute(
        f"""
        SELECT COUNT(*) AS rows_found,
               COALESCE(SUM(CASE WHEN a.category = 'debt' THEN 0 ELSE s.value_usd END), 0)
                   AS total_assets_usd,
               COALESCE(SUM(CASE WHEN a.category = 'debt' THEN s.value_usd ELSE 0 END), 0)
                   AS total_debts_usd,
               COALESCE(SUM({_SIGNED}), 0) AS net_worth_usd
        FROM assets a
        JOIN ({_LATEST_PER_ASSET_AS_OF}) s ON a.id = s.asset_id
        WHERE a.is_active = 1
        """,
        (day,),
    )
    row = await cursor.fetchone()
    if not row or not row["rows_found"]:
        return {"written": False, "reason": f"no snapshots on or before {day}"}

    total_assets_usd = float(row["total_assets_usd"])
    total_debts_usd = float(row["total_debts_usd"])
    net_worth_usd = float(row["net_worth_usd"])

    # Investable is asset-side and gross-assets denominated, matching
    # get_net_worth_history's inv_query.
    inv_cursor = await db.execute(
        f"""
        SELECT a.investable AS investable, SUM(s.value_usd) AS total
        FROM assets a
        JOIN ({_LATEST_PER_ASSET_AS_OF}) s ON a.id = s.asset_id
        WHERE a.is_active = 1 AND a.category = 'asset' AND a.investable LIKE 'investable%'
        GROUP BY a.investable
        """,
        (day,),
    )
    investable_breakdown = {
        inv_row["investable"]: float(inv_row["total"])
        for inv_row in await inv_cursor.fetchall()
        if inv_row["total"] is not None
    }
    investable_total_usd = sum(investable_breakdown.values())

    await db.execute(
        """INSERT OR REPLACE INTO net_worth_history
           (snapshot_date, total_assets_usd, total_debts_usd, net_worth_usd,
            investable_total_usd, investable_breakdown)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            day,
            total_assets_usd,
            total_debts_usd,
            net_worth_usd,
            investable_total_usd,
            json.dumps(investable_breakdown),
        ),
    )
    await db.commit()

    return {
        "written": True,
        "snapshot_date": day,
        "total_assets_usd": total_assets_usd,
        "total_debts_usd": total_debts_usd,
        "net_worth_usd": net_worth_usd,
    }


async def run_daily_valuation(price_date: str | None = None) -> dict:
    """The opt-in daily job: fresh FX, then prices, then FX reconversion, then
    the net_worth_history row — in that order, because each step reads what the
    one before it wrote.

    ``fetch_rates_from_nbu`` already returns ``{}`` on any failure, so a dead
    NBU degrades to "prices only" rather than aborting the run.
    """
    if not price_date:
        price_date = date.today().isoformat()  # noqa: DTZ011 - local calendar date

    fx_rates = await currency_service.fetch_rates_from_nbu(price_date)
    prices = await refresh_all_prices(price_date)
    # The price path already wrote a fresher USD figure for these rows; the FX
    # pass must not immediately overwrite it with a same-day reconversion.
    priced_ids = {o["asset_id"] for o in prices["outcomes"] if o["status"] == "updated"}
    fx = await reconvert_foreign_currency_rows(price_date, skip_asset_ids=priced_ids)
    history = await write_net_worth_history(price_date)

    return {
        "price_date": price_date,
        "updated": prices["updated"],
        "skipped": prices["skipped"],
        "failed": prices["failed"],
        "reconverted": fx["reconverted"],
        "outcomes": prices["outcomes"] + fx["outcomes"],
        "fx_rates": fx_rates,
        "history": history,
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

    # Investable is asset-side, so only the date list is shared with the series above.
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

    cursor = await db.execute(f"""
        SELECT a.id, a.category, a.investable, a.sheet_id, a.asset_class, a.name,
               COALESCE(snap.value_usd, a.value_usd) as current_value_usd
        FROM assets a
        LEFT JOIN ({_LATEST_PER_ASSET}) snap ON a.id = snap.asset_id
        WHERE a.is_active = 1
    """)
    all_rows = list(await cursor.fetchall())
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
        # Against a zero or negative base a ratio is meaningless and sign-flipped.
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


async def get_period_returns(nw_data: dict | None = None) -> dict:
    """Period returns on net worth. Pass an existing get_current_net_worth()
    result to avoid recomputing the whole aggregate."""
    db = await get_db()
    today = date.today()  # noqa: DTZ011 - local calendar date

    if nw_data is None:
        nw_data = await get_current_net_worth()
    current = nw_data["net_worth"]
    # Tests the portfolio, not the total: a net worth of zero is a real figure.
    if not nw_data["assets_count"] and not nw_data["debts_count"]:
        return {}

    def pct(ref: float | None) -> float | None:
        # Withheld only when unknowable: no snapshot on or before the date, or a
        # base a ratio cannot describe. A period that happens to be flat is 0.0 —
        # returning None there made "unchanged" render as "no data".
        if ref is not None and ref > 0:
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
        f"""
        WITH latest AS ({_LATEST_PER_ASSET}),
        ref AS ({_LATEST_PER_ASSET_AS_OF})
        SELECT
            a.name,
            a.category,
            latest.value_usd  AS current_val,
            ref.value_usd     AS ref_val,
            latest.snapshot_date AS current_date,
            ref.snapshot_date    AS ref_date,
            -- A shrinking debt moves net worth up, so debts negate.
            CASE WHEN a.category = 'debt'
                 THEN ref.value_usd - latest.value_usd
                 ELSE latest.value_usd - ref.value_usd END AS change_val,
            -- ABS denominator, so the percentage's sign follows change_val.
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

    cursor = await db.execute(f"""
        SELECT a.id, a.name, a.asset_class, a.category,
               COALESCE(snap.value_usd, a.value_usd) AS current_val
        FROM assets a
        LEFT JOIN ({_LATEST_PER_ASSET}) snap ON a.id = snap.asset_id
        WHERE a.is_active = 1
    """)
    current_rows = {row["id"]: dict(row) for row in await cursor.fetchall()}

    cursor = await db.execute(_LATEST_PER_ASSET_AS_OF, (ref_date,))
    ref_vals = {
        row["asset_id"]: float(row["value_usd"]) for row in await cursor.fetchall()
    }

    results = []
    for asset_id, asset in current_rows.items():
        is_debt = asset["category"] == "debt"
        current_val = float(asset["current_val"] or 0)
        ref_val = ref_vals.get(asset_id, 0)
        delta = current_val - ref_val
        # Negating debts is what makes these contributions sum to the period's
        # net-worth change.
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
    """Largest holdings. Assets only, and denominated by gross assets."""
    db = await get_db()
    cursor = await db.execute(
        f"""
        SELECT a.name, a.asset_class,
               COALESCE(snap.value_usd, a.value_usd) AS current_value_usd
        FROM assets a
        LEFT JOIN ({_LATEST_PER_ASSET}) snap ON a.id = snap.asset_id
        WHERE a.is_active = 1 AND a.category = 'asset'
          AND COALESCE(snap.value_usd, a.value_usd) > 0
        ORDER BY current_value_usd DESC
        LIMIT ?
    """,
        (limit,),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def get_assets_by_class_summary() -> list[dict]:
    """Asset allocation by class. Assets only — a liability is not an asset class."""
    db = await get_db()
    cursor = await db.execute(f"""
        SELECT
            COALESCE(a.asset_class, 'miscellaneous') AS asset_class,
            COALESCE(ac.display_name, a.asset_class, 'Misc') AS display_name,
            COALESCE(ac.color, '#888') AS color,
            COUNT(*) AS count,
            SUM(COALESCE(snap.value_usd, a.value_usd)) AS total_value
        FROM assets a
        LEFT JOIN asset_classes ac ON ac.name = a.asset_class
        LEFT JOIN ({_LATEST_PER_ASSET}) snap ON a.id = snap.asset_id
        WHERE a.is_active = 1 AND a.category = 'asset'
        GROUP BY a.asset_class
        ORDER BY total_value DESC
    """)
    return [dict(row) for row in await cursor.fetchall()]
