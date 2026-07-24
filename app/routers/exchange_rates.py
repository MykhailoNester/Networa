from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import templates
from ..forms import get_str
from ..models import ExchangeRateCreate
from ..services import currency_service

router = APIRouter()


@router.get("/exchange-rates", response_class=HTMLResponse)
async def exchange_rates_page(request: Request):
    rates = await currency_service.get_all_rates()
    return templates.TemplateResponse(
        request,
        "exchange_rates.html",
        {
            "request": request,
            "rates": rates,
            "today": date.today().isoformat(),  # noqa: DTZ011 - local calendar date
            "page": "exchange_rates",
        },
    )


@router.post("/exchange-rates")
async def exchange_rates_save(request: Request):
    form = await request.form()
    await currency_service.save_rate(
        get_str(form, "from_currency"),
        get_str(form, "to_currency", "USD"),
        float(get_str(form, "rate")),
        get_str(form, "rate_date"),
    )
    rates = await currency_service.get_all_rates()
    return templates.TemplateResponse(
        request,
        "exchange_rates.html",
        {
            "request": request,
            "rates": rates,
            "today": date.today().isoformat(),  # noqa: DTZ011 - local calendar date
            "page": "exchange_rates",
            "success": "Rate saved successfully.",
        },
    )


@router.post("/exchange-rates/recalculate")
async def exchange_rates_recalculate():
    await currency_service.recalculate_all_usd_values()
    return RedirectResponse("/exchange-rates?recalculated=1", status_code=303)


# --- JSON API ---
@router.get("/api/v1/exchange-rates")
async def list_rates():
    return await currency_service.get_all_rates()


@router.post("/api/v1/exchange-rates")
async def create_rate(data: ExchangeRateCreate):
    await currency_service.save_rate(
        data.from_currency, data.to_currency, data.rate, data.rate_date
    )
    return {"status": "saved"}


@router.post("/api/v1/exchange-rates/recalculate")
async def recalculate():
    await currency_service.recalculate_all_usd_values()
    return {"status": "recalculated"}


@router.post("/exchange-rates/fetch-nbu")
async def exchange_rates_fetch_nbu():
    """Fetch today's rates from NBU and redirect back to the exchange rates page."""
    await currency_service.fetch_rates_from_nbu()
    return RedirectResponse("/exchange-rates?fetched=1", status_code=303)


@router.post("/api/v1/exchange-rates/fetch-nbu")
async def api_fetch_nbu():
    rates = await currency_service.fetch_rates_from_nbu()
    return {"status": "ok", "rates": rates}
