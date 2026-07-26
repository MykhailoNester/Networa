"""Market-price and FX refresh endpoints.

No arithmetic here — every number comes from ``snapshot_service``. The HTMX
route only reprices tickers; it never touches FX or writes a
``net_worth_history`` row, so it stays fast, predictable, and works
identically whether or not the daily schedule (``app/scheduler.py``) is turned
on. The two JSON routes are the machine-readable equivalents:
``/api/v1/prices/refresh`` is the same prices-only pass, and
``/api/v1/valuation/daily-run`` is the full daily job (FX + prices + history)
for anyone who would rather drive it from system cron than the in-app
scheduler — see ``docs/auto-valuation.md``.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import templates
from ..services import snapshot_service

router = APIRouter()


@router.post("/prices/refresh", response_class=HTMLResponse)
async def refresh_prices(request: Request) -> HTMLResponse:
    """Reprice every ticker-and-quantity-bearing asset and report the outcome.

    Rendered through a Jinja partial (not an f-string) so the name/ticker/
    detail values the report interpolates — all user- or import-supplied — are
    escaped automatically.
    """
    report = await snapshot_service.refresh_all_prices()
    return templates.TemplateResponse(
        request,
        "partials/refresh_prices.html",
        {"request": request, "report": report},
    )


@router.post("/api/v1/prices/refresh")
async def api_refresh_prices() -> dict:
    return await snapshot_service.refresh_all_prices()


@router.post("/api/v1/valuation/daily-run")
async def api_daily_run() -> dict:
    """The same job the in-app scheduler runs once a day: fresh FX rates,
    ticker prices, FX reconversion for the rest, and a net_worth_history row.
    A cron entry can POST here directly instead of enabling the schedule:

        curl -X POST http://127.0.0.1:8000/api/v1/valuation/daily-run
    """
    return await snapshot_service.run_daily_valuation()
