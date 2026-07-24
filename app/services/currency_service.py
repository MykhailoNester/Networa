from datetime import date

from ..database import get_db

# Default exchange rates (fallback when no DB rate and NBU unavailable)
DEFAULT_RATES = {
    "EUR": 1.0834,
    "UAH": 0.02415,
    "GBP": 1.27,
    "CHF": 1.12,
    "USD": 1.0,
}

# Canonical currency-symbol map, shared by the display state and the Jinja
# format_currency filter (imported by app/__init__.py).
CURRENCY_SYMBOLS = {
    "USD": "$",
    "JPY": "¥",
    "CNY": "¥",
    "CAD": "C$",
    "AUD": "A$",
    "NZD": "NZ$",
    "HKD": "HK$",
    "SGD": "S$",
    "SEK": "kr ",
    "NOK": "kr ",
    "DKK": "kr ",
    "PLN": "zł ",
    "CZK": "Kč ",
    "HUF": "Ft ",
    "BRL": "R$",
    "MXN": "MX$",
    "INR": "₹",
    "KRW": "₩",
    "THB": "฿",
    "EUR": "€",
    "UAH": "₴",
    "GBP": "£",
    "CHF": "CHF ",
}

# Module-level display state (currency, multiplier, symbol) — updated by reload_display_state()
_display_state: dict = {"currency": "USD", "multiplier": 1.0, "symbol": "$"}


async def get_rate(from_currency: str, to_currency: str = "USD") -> float:
    if from_currency == to_currency:
        return 1.0
    db = await get_db()
    cursor = await db.execute(
        """SELECT rate FROM exchange_rates
           WHERE from_currency = ? AND to_currency = ?
           ORDER BY rate_date DESC LIMIT 1""",
        (from_currency, to_currency),
    )
    row = await cursor.fetchone()
    if row:
        return row["rate"]
    return DEFAULT_RATES.get(from_currency, 1.0)


async def convert_to_usd(amount: float, currency: str) -> float:
    if currency == "USD":
        return amount
    rate = await get_rate(currency, "USD")
    return amount * rate


async def save_rate(from_currency: str, to_currency: str, rate: float, rate_date: str):
    db = await get_db()
    await db.execute(
        """INSERT OR REPLACE INTO exchange_rates (from_currency, to_currency, rate, rate_date)
           VALUES (?, ?, ?, ?)""",
        (from_currency, to_currency, rate, rate_date),
    )
    await db.commit()


async def get_all_rates() -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        """SELECT * FROM exchange_rates ORDER BY from_currency, rate_date DESC"""
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def recalculate_all_usd_values():
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, value, currency FROM assets WHERE is_active = 1"
    )
    rows = await cursor.fetchall()
    for row in rows:
        value_usd = await convert_to_usd(row["value"], row["currency"])
        await db.execute(
            "UPDATE assets SET value_usd = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (value_usd, row["id"]),
        )
    await db.commit()


async def fetch_rates_from_nbu(rate_date: str | None = None) -> dict[str, float]:
    """Fetch exchange rates from the National Bank of Ukraine API.

    Returns a dict of {currency_code: usd_rate} for each currency saved.
    Falls back silently to an empty dict on any network/parse error.
    """
    import httpx

    date_str = rate_date or date.today().isoformat()  # noqa: DTZ011 - local calendar date
    date_compact = date_str.replace("-", "")  # YYYYMMDD required by NBU

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"
                f"?date={date_compact}&json"
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:  # noqa: BLE001 - fall back silently on any network/parse error
        return {}

    # NBU returns UAH-per-foreign-currency rates: {cc: "EUR", rate: 41.12, ...}
    nbu_rates = {item["cc"]: item["rate"] for item in data}
    usd_uah = nbu_rates.get("USD")
    if not usd_uah:
        return {}

    saved: dict[str, float] = {}

    # Compute cross-rates vs USD for the currencies we support
    for cc in ("EUR", "GBP", "CHF"):
        uah_rate = nbu_rates.get(cc)
        if uah_rate:
            usd_rate = round(uah_rate / usd_uah, 6)  # 1 cc = usd_rate USD
            await save_rate(cc, "USD", usd_rate, date_str)
            saved[cc] = usd_rate

    # UAH → USD
    uah_to_usd = round(1.0 / usd_uah, 6)
    await save_rate("UAH", "USD", uah_to_usd, date_str)
    saved["UAH"] = uah_to_usd

    return saved


async def reload_display_state():
    """Read the display_currency setting from DB and update the module-level _display_state."""
    from .settings_service import get_setting

    currency = await get_setting("display_currency", "USD")

    if currency == "USD":
        multiplier = 1.0
    else:
        rate = await get_rate(currency, "USD")  # 1 currency = rate USD
        multiplier = (
            round(1.0 / rate, 8) if rate else 1.0
        )  # 1 USD = multiplier currency units

    symbol = CURRENCY_SYMBOLS.get(currency, currency + " ")
    _display_state.update(
        {"currency": currency, "multiplier": multiplier, "symbol": symbol}
    )
