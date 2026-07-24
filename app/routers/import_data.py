from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import HTMLResponse

from .. import templates
from ..services import import_service

router = APIRouter()


# --- API Endpoints ---
@router.post("/api/v1/import/assets-csv")
async def api_import_assets_csv(file: UploadFile):
    content = await file.read()
    return await import_service.import_assets_csv(content.decode("utf-8"))


@router.post("/api/v1/import/cashflow-csv")
async def api_import_cashflow_csv(file: UploadFile):
    content = await file.read()
    return await import_service.import_cashflow_csv(content.decode("utf-8"))


# --- HTML Pages ---
@router.get("/import", response_class=HTMLResponse)
async def import_page(request: Request):
    return templates.TemplateResponse(
        request,
        "import.html",
        {
            "request": request,
            "page": "import",
            "result": None,
        },
    )


@router.post("/import/assets-csv", response_class=HTMLResponse)
async def import_assets_csv_form(request: Request, file: UploadFile):
    content = await file.read()
    try:
        stats = await import_service.import_assets_csv(content.decode("utf-8"))
        result = {"success": True, "type": "Assets CSV", **stats}
    except Exception as e:  # noqa: BLE001 - surface any import failure to the user
        result = {"success": False, "error": str(e)}
    return templates.TemplateResponse(
        request,
        "import.html",
        {
            "request": request,
            "page": "import",
            "result": result,
        },
    )


@router.post("/import/cashflow-csv", response_class=HTMLResponse)
async def import_cashflow_csv_form(request: Request, file: UploadFile):
    content = await file.read()
    try:
        stats = await import_service.import_cashflow_csv(content.decode("utf-8"))
        result = {"success": True, "type": "Cashflows CSV", **stats}
    except Exception as e:  # noqa: BLE001 - surface any import failure to the user
        result = {"success": False, "error": str(e)}
    return templates.TemplateResponse(
        request,
        "import.html",
        {
            "request": request,
            "page": "import",
            "result": result,
        },
    )
