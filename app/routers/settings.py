from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from ..forms import get_str
from ..services import currency_service
from ..services.settings_service import set_setting

router = APIRouter()

_ALLOWED_CURRENCIES = {"USD", "EUR", "UAH"}


@router.post("/settings/display-currency")
async def set_display_currency(request: Request):
    from .. import _sync_display_globals

    form = await request.form()
    currency = (get_str(form, "currency") or "USD").upper()
    if currency not in _ALLOWED_CURRENCIES:
        currency = "USD"

    await set_setting("display_currency", currency)
    # Refresh NBU rates so the conversion is up-to-date, then reload state
    await currency_service.fetch_rates_from_nbu()
    await currency_service.reload_display_state()
    _sync_display_globals()

    referer = request.headers.get("referer", "/")
    return RedirectResponse(referer, status_code=303)
