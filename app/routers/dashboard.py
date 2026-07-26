from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import scheduler, templates
from ..models import DashboardResponse
from ..services import settings_service, snapshot_service

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    data = await snapshot_service.get_current_net_worth()
    history = await snapshot_service.get_net_worth_history()
    period_returns = await snapshot_service.get_period_returns(data)
    top_movers = await snapshot_service.get_top_movers(days=30, limit=5)
    # Display only — three settings reads, no arithmetic. Answers "when were
    # prices last refreshed automatically", which carry-forward otherwise hides.
    auto_valuation = {
        "enabled": await settings_service.get_setting(scheduler.SETTING_ENABLED, "0")
        == "1",
        "run_hour": scheduler.parse_run_hour(
            await settings_service.get_setting(scheduler.SETTING_RUN_HOUR, "")
        ),
        "last_run": await settings_service.get_setting(scheduler.SETTING_LAST_RUN, ""),
    }

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "data": data,
            "history": history,
            "period_returns": period_returns,
            "top_movers": top_movers,
            "auto_valuation": auto_valuation,
            "page": "dashboard",
        },
    )


@router.get("/api/v1/dashboard", response_model=DashboardResponse)
async def api_dashboard():
    return await snapshot_service.get_current_net_worth()


@router.get("/breakdown/networth", response_class=HTMLResponse)
async def breakdown_networth(request: Request):
    data = await snapshot_service.get_current_net_worth()
    top_assets = await snapshot_service.get_top_assets_by_value(limit=10)
    return templates.TemplateResponse(
        request,
        "partials/breakdown_networth.html",
        {
            "request": request,
            "top_assets": top_assets,
            "total_assets": data["total_assets"],
            "total_debts": data["total_debts"],
            "net_worth": data["net_worth"],
            "debts_by_name": data["debts_by_name"],
        },
    )


@router.get("/breakdown/assets", response_class=HTMLResponse)
async def breakdown_assets(request: Request):
    by_class = await snapshot_service.get_assets_by_class_summary()
    return templates.TemplateResponse(
        request,
        "partials/breakdown_assets.html",
        {
            "request": request,
            "by_class": by_class,
        },
    )


@router.get("/breakdown/investable", response_class=HTMLResponse)
async def breakdown_investable(request: Request):
    data = await snapshot_service.get_current_net_worth()
    return templates.TemplateResponse(
        request,
        "partials/breakdown_investable.html",
        {
            "request": request,
            "investable_by_type": data["investable_by_type"],
            "total_assets": data["total_assets"],
        },
    )


@router.get("/breakdown/period/{period_key}", response_class=HTMLResponse)
async def breakdown_period(request: Request, period_key: str):
    if period_key not in {"ytd", "qtd", "mtd", "one_year", "all_time"}:
        return HTMLResponse("Invalid period", status_code=400)
    contributors = await snapshot_service.get_period_contributors(period_key)
    period_returns = await snapshot_service.get_period_returns()
    return templates.TemplateResponse(
        request,
        "partials/breakdown_period.html",
        {
            "request": request,
            "contributors": contributors,
            "pct": period_returns.get(period_key),
            "change": period_returns.get(f"{period_key}_change"),
        },
    )
