from urllib.parse import urlsplit

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

    # Bounce back to the page the switch was used on, but only ever to a path on
    # this app — Referer is attacker-settable, and echoing it verbatim into a
    # redirect turns this into an open redirect.
    referer = request.headers.get("referer", "/")
    path = urlsplit(referer).path or "/"
    if not path.startswith("/") or path.startswith("//"):
        path = "/"
    return RedirectResponse(path, status_code=303)
