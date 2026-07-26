"""Liabilities page.

Debts live in the same `assets` table as assets, told apart by
``category='debt'``, so this router is a thin view over asset_service — there is
no debt-specific service layer and no debt-specific CRUD. Creating and editing a
debt reuses the assets router's ``/assets/create`` and ``/assets/{id}`` handlers,
which already accept ``category`` from the submitted form.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import templates
from ..services import asset_service

router = APIRouter()


@router.get("/api/v1/debts")
async def api_list_debts():
    return await asset_service.list_assets(category="debt")


@router.get("/debts", response_class=HTMLResponse)
async def debts_page(request: Request):
    from ..database import get_db

    debts = await asset_service.list_assets(category="debt")
    total_value = sum((d.get("current_value_usd") or 0) for d in debts)

    db = await get_db()
    cursor = await db.execute("SELECT * FROM sheets ORDER BY sort_order")
    sheets = [dict(row) for row in await cursor.fetchall()]
    asset_classes = await asset_service.get_asset_classes()

    return templates.TemplateResponse(
        request,
        "debts/list.html",
        {
            "request": request,
            "debts": debts,
            "total_value": total_value,
            "sheets": sheets,
            "asset_classes": asset_classes,
            "page": "debts",
        },
    )
