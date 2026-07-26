import json

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import templates
from ..database import get_db
from ..models import SheetCreate, SheetUpdate

router = APIRouter()


@router.get("/api/v1/sheets")
async def list_sheets():
    db = await get_db()
    cursor = await db.execute("SELECT * FROM sheets ORDER BY sort_order, name")
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


@router.post("/api/v1/sheets")
async def create_sheet(data: SheetCreate):
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO sheets (name, sort_order) VALUES (?, ?)",
        (data.name, data.sort_order),
    )
    await db.commit()
    cursor = await db.execute("SELECT * FROM sheets WHERE id = ?", (cursor.lastrowid,))
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Sheet not found")
    return dict(row)


@router.put("/api/v1/sheets/{sheet_id}")
async def update_sheet(sheet_id: int, data: SheetUpdate):
    db = await get_db()
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if updates:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = [*updates.values(), sheet_id]
        await db.execute(f"UPDATE sheets SET {set_clause} WHERE id = ?", values)
        await db.commit()
    cursor = await db.execute("SELECT * FROM sheets WHERE id = ?", (sheet_id,))
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Sheet not found")
    return dict(row)


@router.delete("/api/v1/sheets/{sheet_id}")
async def delete_sheet(sheet_id: int):
    db = await get_db()
    await db.execute("DELETE FROM sheets WHERE id = ?", (sheet_id,))
    await db.commit()
    return {"status": "deleted"}


# --- HTML page endpoints ---


@router.get("/sheets", response_class=HTMLResponse)
async def sheets_page(request: Request):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM sheets ORDER BY sort_order, name")
    sheets = [dict(row) for row in await cursor.fetchall()]
    # Get asset count per sheet
    cursor = await db.execute(
        "SELECT sheet_id, COUNT(*) as cnt FROM assets WHERE sheet_id IS NOT NULL GROUP BY sheet_id"
    )
    counts = {row["sheet_id"]: row["cnt"] for row in await cursor.fetchall()}
    for sheet in sheets:
        sheet["asset_count"] = counts.get(sheet["id"], 0)
    return templates.TemplateResponse(
        request,
        "sheets/list.html",
        {
            "request": request,
            "sheets": sheets,
            "page": "sheets",
        },
    )


@router.post("/sheets/create")
async def create_sheet_form(
    name: str = Form(...),
    sort_order: int = Form(0),
):
    name = name.strip()
    if not name:
        return RedirectResponse("/sheets?error=empty_name", status_code=303)
    db = await get_db()
    await db.execute(
        "INSERT INTO sheets (name, sort_order) VALUES (?, ?)",
        (name, sort_order),
    )
    await db.commit()
    return RedirectResponse("/sheets?saved=1", status_code=303)


@router.post("/sheets/{sheet_id}/edit")
async def edit_sheet_form(
    sheet_id: int,
    request: Request,
    name: str = Form(...),
    sort_order: int = Form(0),
):
    name = name.strip()
    if not name:
        return RedirectResponse("/sheets?error=empty_name", status_code=303)
    db = await get_db()
    await db.execute(
        "UPDATE sheets SET name = ?, sort_order = ? WHERE id = ?",
        (name, sort_order, sheet_id),
    )
    await db.commit()
    cursor = await db.execute("SELECT * FROM sheets WHERE id = ?", (sheet_id,))
    row = await cursor.fetchone()
    if row is None:
        return RedirectResponse("/sheets", status_code=303)
    cursor2 = await db.execute(
        "SELECT COUNT(*) as cnt FROM assets WHERE sheet_id = ?", (sheet_id,)
    )
    cnt_row = await cursor2.fetchone()
    sheet = dict(row)
    sheet["asset_count"] = cnt_row["cnt"] if cnt_row else 0
    return templates.TemplateResponse(
        request,
        "sheets/partials/display_row.html",
        {
            "request": request,
            "sheet": sheet,
        },
    )


@router.post("/sheets/{sheet_id}/delete", response_class=HTMLResponse)
async def delete_sheet_form(sheet_id: int, request: Request):
    db = await get_db()
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM assets WHERE sheet_id = ?", (sheet_id,)
    )
    row = await cursor.fetchone()
    if row and row["cnt"] > 0:
        # Return the existing row with an error trigger
        cursor2 = await db.execute("SELECT * FROM sheets WHERE id = ?", (sheet_id,))
        sheet_row = await cursor2.fetchone()
        if sheet_row is None:
            return HTMLResponse("", status_code=404)
        cursor3 = await db.execute(
            "SELECT COUNT(*) as cnt FROM assets WHERE sheet_id = ?", (sheet_id,)
        )
        cnt_row = await cursor3.fetchone()
        sheet = dict(sheet_row)
        sheet["asset_count"] = cnt_row["cnt"] if cnt_row else 0
        resp = templates.TemplateResponse(
            request,
            "sheets/partials/display_row.html",
            {
                "request": request,
                "sheet": sheet,
            },
        )
        resp.headers["HX-Trigger"] = json.dumps(
            {"showError": "Cannot delete a sheet with assigned assets."}
        )
        return resp
    await db.execute("DELETE FROM sheets WHERE id = ?", (sheet_id,))
    await db.commit()
    return HTMLResponse("")


@router.get("/sheets/{sheet_id}/edit-form", response_class=HTMLResponse)
async def sheet_edit_form(sheet_id: int, request: Request):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM sheets WHERE id = ?", (sheet_id,))
    row = await cursor.fetchone()
    if row is None:
        return HTMLResponse("Not found", status_code=404)
    cursor2 = await db.execute(
        "SELECT COUNT(*) as cnt FROM assets WHERE sheet_id = ?", (sheet_id,)
    )
    cnt_row = await cursor2.fetchone()
    sheet = dict(row)
    sheet["asset_count"] = cnt_row["cnt"] if cnt_row else 0
    return templates.TemplateResponse(
        request,
        "sheets/partials/edit_row.html",
        {
            "request": request,
            "sheet": sheet,
        },
    )


@router.get("/sheets/{sheet_id}/display-row", response_class=HTMLResponse)
async def sheet_display_row(sheet_id: int, request: Request):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM sheets WHERE id = ?", (sheet_id,))
    row = await cursor.fetchone()
    if row is None:
        return HTMLResponse("Not found", status_code=404)
    cursor2 = await db.execute(
        "SELECT COUNT(*) as cnt FROM assets WHERE sheet_id = ?", (sheet_id,)
    )
    cnt_row = await cursor2.fetchone()
    sheet = dict(row)
    sheet["asset_count"] = cnt_row["cnt"] if cnt_row else 0
    return templates.TemplateResponse(
        request,
        "sheets/partials/display_row.html",
        {
            "request": request,
            "sheet": sheet,
        },
    )
