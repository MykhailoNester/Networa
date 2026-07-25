from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse

from .. import templates
from ..services import import_service

router = APIRouter()

# The upload is read into memory and parsed in full, so it needs a ceiling. 10 MiB
# is far more than any realistic portfolio export.
MAX_CSV_BYTES = 10 * 1024 * 1024
_CHUNK = 64 * 1024


async def _read_csv_upload(file: UploadFile) -> str:
    """Read an uploaded CSV to text, rejecting oversized or non-UTF-8 files."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_CHUNK):
        total += len(chunk)
        if total > MAX_CSV_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"CSV is larger than the {MAX_CSV_BYTES // (1024 * 1024)} MiB limit.",
            )
        chunks.append(chunk)
    try:
        return b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400, detail="CSV must be UTF-8 encoded."
        ) from exc


# --- API Endpoints ---
@router.post("/api/v1/import/assets-csv")
async def api_import_assets_csv(file: UploadFile):
    return await import_service.import_assets_csv(await _read_csv_upload(file))


@router.post("/api/v1/import/cashflow-csv")
async def api_import_cashflow_csv(file: UploadFile):
    return await import_service.import_cashflow_csv(await _read_csv_upload(file))


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


def _render(request: Request, result: dict | None) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "import.html",
        {
            "request": request,
            "page": "import",
            "result": result,
        },
    )


@router.post("/import/assets-csv", response_class=HTMLResponse)
async def import_assets_csv_form(request: Request, file: UploadFile):
    try:
        content = await _read_csv_upload(file)
        stats = await import_service.import_assets_csv(content)
        result = {"success": True, "type": "Assets CSV", **stats}
    except HTTPException as exc:  # size / encoding rejection — show the reason
        result = {"success": False, "error": exc.detail}
    except Exception as e:  # noqa: BLE001 - surface any import failure to the user
        result = {"success": False, "error": str(e)}
    return _render(request, result)


@router.post("/import/cashflow-csv", response_class=HTMLResponse)
async def import_cashflow_csv_form(request: Request, file: UploadFile):
    try:
        content = await _read_csv_upload(file)
        stats = await import_service.import_cashflow_csv(content)
        result = {"success": True, "type": "Cashflows CSV", **stats}
    except HTTPException as exc:  # size / encoding rejection — show the reason
        result = {"success": False, "error": exc.detail}
    except Exception as e:  # noqa: BLE001 - surface any import failure to the user
        result = {"success": False, "error": str(e)}
    return _render(request, result)
