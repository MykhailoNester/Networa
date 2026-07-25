"""Market data service — fetch ticker prices from Yahoo Finance."""

from datetime import UTC, datetime
from urllib.parse import quote


async def fetch_ticker_price(ticker: str, price_date: str) -> tuple[float, str] | None:
    """Fetch the closing price for `ticker` on `price_date` (YYYY-MM-DD).

    Returns (price, currency_code) on success, or None on any failure.
    If the market was closed on that date, Yahoo returns the nearest prior
    trading day's data, which is acceptable for snapshot purposes.
    """
    import httpx

    try:
        dt = datetime.strptime(price_date, "%Y-%m-%d").replace(tzinfo=UTC)
        period1 = int(dt.timestamp())
        period2 = period1 + 86400  # one full day window

        # Tickers are free-text user input, so percent-encode before splicing
        # into the path — an unencoded "?" or "/" would otherwise rewrite the
        # query string or walk the path.
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker, safe='')}"
            f"?interval=1d&period1={period1}&period2={period2}"
        )
        headers = {"User-Agent": "Mozilla/5.0"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        result = data["chart"]["result"][0]
        currency = result["meta"].get("currency", "USD")

        # Prefer the actual closing price for the date
        price = None
        try:
            closes = result["indicators"]["quote"][0]["close"]
            price = next((c for c in closes if c is not None), None)
        except (KeyError, IndexError, TypeError):
            pass

        # Fall back to regularMarketPrice (current price or last known)
        if price is None:
            price = result["meta"].get("regularMarketPrice")

        if price is None:
            return None

        # Normalize GBX (London pence) → GBP
        if currency == "GBX":
            price = price / 100
            currency = "GBP"

        return float(price), currency

    except Exception:  # noqa: BLE001 - network/parse errors fall back to None
        return None
