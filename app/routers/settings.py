from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from .. import scheduler
from ..forms import get_int, get_str
from ..services import currency_service
from ..services.settings_service import set_setting

router = APIRouter()

_ALLOWED_CURRENCIES = {"USD", "EUR", "UAH"}


def _safe_referer_path(request: Request) -> str:
    """The path to bounce back to after a settings POST, but only ever a path on
    this app — Referer is attacker-settable, and echoing it verbatim into a
    redirect turns this into an open redirect."""
    referer = request.headers.get("referer", "/")
    path = urlsplit(referer).path or "/"
    if not path.startswith("/") or path.startswith("//"):
        path = "/"
    return path


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

    return RedirectResponse(_safe_referer_path(request), status_code=303)


@router.post("/settings/auto-valuation")
async def set_auto_valuation(request: Request) -> RedirectResponse:
    """Turn the opt-in daily schedule on/off and set its run hour.

    No network call and no money math — it only writes two settings and
    starts/stops the app/scheduler.py loop, which is why this lives here
    rather than in a service.
    """
    form = await request.form()
    enabled = get_str(form, "enabled", "0") == "1"
    run_hour = scheduler.parse_run_hour(
        str(get_int(form, "run_hour", scheduler.DEFAULT_RUN_HOUR))
    )

    await set_setting(scheduler.SETTING_ENABLED, "1" if enabled else "0")
    await set_setting(scheduler.SETTING_RUN_HOUR, str(run_hour))

    if enabled:
        await scheduler.start()
    else:
        await scheduler.stop()

    return RedirectResponse(_safe_referer_path(request), status_code=303)
