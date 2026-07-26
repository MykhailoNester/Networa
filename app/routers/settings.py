from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import scheduler, templates
from ..forms import get_int, get_str
from ..services import currency_service
from ..services.settings_service import get_setting, set_setting

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


async def _auto_valuation_context() -> dict[str, object]:
    """Everything the Settings page shows about the daily schedule: the two
    stored settings, whether the background loop is actually running right
    now (``is_running()`` reflects the live asyncio task, not just the
    setting), and when it is next expected to fire."""
    enabled = await get_setting(scheduler.SETTING_ENABLED, "0") == "1"
    run_hour = scheduler.parse_run_hour(
        await get_setting(scheduler.SETTING_RUN_HOUR, "")
    )
    last_run = await get_setting(scheduler.SETTING_LAST_RUN, "")
    now = datetime.now(tz=UTC).astimezone()
    return {
        "enabled": enabled,
        "run_hour": run_hour,
        "last_run": last_run or None,
        "is_running": scheduler.is_running(),
        "next_run": scheduler.next_run_at(last_run, now, run_hour) if enabled else None,
    }


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "request": request,
            "auto_valuation": await _auto_valuation_context(),
            "page": "settings",
        },
    )


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
    # An absent `enabled` field means "not specified", NOT "off". The control
    # is a pair of named submit buttons, not a checkbox, so only the button
    # actually pressed is submitted — and a submit that carries just the hour
    # must not silently switch the schedule off behind the user's back.
    raw_enabled = get_str(form, "enabled", "")
    enabled = (
        raw_enabled == "1"
        if raw_enabled
        else await get_setting(scheduler.SETTING_ENABLED, "0") == "1"
    )
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
