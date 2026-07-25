from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import templates
from ..database import get_db
from ..forms import get_float, get_opt_str, get_str
from ..html import e as _e
from ..models import CashflowCreate, CashflowUpdate
from ..services import cashflow_service

router = APIRouter()

_CURRENCIES = ["USD", "EUR", "UAH", "GBP", "CHF"]
_STATUSES = ["Active", "Pending", "Completed"]


# --- API Endpoints ---
@router.get("/api/v1/cashflows")
async def api_list_cashflows(
    asset_id: int | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
):
    return await cashflow_service.list_cashflows(
        asset_id=asset_id, from_date=from_date, to_date=to_date
    )


@router.post("/api/v1/cashflows")
async def api_create_cashflow(data: CashflowCreate):
    return await cashflow_service.create_cashflow(data.model_dump())


@router.get("/api/v1/cashflows/{cashflow_id}")
async def api_get_cashflow(cashflow_id: int):
    cf = await cashflow_service.get_cashflow(cashflow_id)
    if not cf:
        raise HTTPException(status_code=404, detail="Cashflow not found")
    return cf


@router.put("/api/v1/cashflows/{cashflow_id}")
async def api_update_cashflow(cashflow_id: int, data: CashflowUpdate):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    cf = await cashflow_service.update_cashflow(cashflow_id, updates)
    if not cf:
        raise HTTPException(status_code=404, detail="Cashflow not found")
    return cf


@router.delete("/api/v1/cashflows/{cashflow_id}")
async def api_delete_cashflow(cashflow_id: int):
    return await cashflow_service.delete_cashflow(cashflow_id)


# --- HTML Pages ---
@router.get("/cashflows", response_class=HTMLResponse)
async def cashflows_page(
    request: Request, from_date: str | None = None, to_date: str | None = None
):
    cashflows = await cashflow_service.list_cashflows(
        from_date=from_date, to_date=to_date
    )
    total_in = sum(c["cash_in_usd"] for c in cashflows)
    total_out = sum(c["cash_out_usd"] for c in cashflows)

    db = await get_db()
    cursor = await db.execute(
        "SELECT id, name FROM assets WHERE is_active = 1 ORDER BY name"
    )
    assets = [dict(row) for row in await cursor.fetchall()]

    sold_positions = await cashflow_service.get_sold_positions_summary()

    return templates.TemplateResponse(
        request,
        "cashflows/list.html",
        {
            "request": request,
            "cashflows": cashflows,
            "total_in": total_in,
            "total_out": total_out,
            "from_date": from_date or "",
            "to_date": to_date or "",
            "assets": assets,
            "sold_positions": sold_positions,
            "page": "cashflows",
        },
    )


@router.post("/cashflows/create")
async def cashflow_create_submit(request: Request):
    form = await request.form()

    asset_id_raw = form.get("asset_id")
    asset_id = (
        int(asset_id_raw) if isinstance(asset_id_raw, str) and asset_id_raw else None
    )

    data = {
        "flow_date": form.get("flow_date"),
        "description": get_opt_str(form, "description"),
        "notes": get_opt_str(form, "notes"),
        "cash_in": get_float(form, "cash_in"),
        "cash_in_currency": get_str(form, "cash_in_currency") or "USD",
        "cash_out": get_float(form, "cash_out"),
        "cash_out_currency": get_str(form, "cash_out_currency") or "USD",
        "status": get_str(form, "status") or "Active",
    }
    if asset_id:
        data["asset_id"] = asset_id
        db = await get_db()
        cursor = await db.execute("SELECT name FROM assets WHERE id = ?", (asset_id,))
        row = await cursor.fetchone()
        if row:
            data["asset_name"] = row["name"]

    await cashflow_service.create_cashflow(data)

    redirect_to = get_str(form, "redirect_to") or "/cashflows"
    return RedirectResponse(redirect_to, status_code=303)


@router.post("/cashflows/{cashflow_id}/edit")
async def cashflow_edit_submit(cashflow_id: int, request: Request):
    form = await request.form()

    existing = await cashflow_service.get_cashflow(cashflow_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Cashflow not found")

    data = {
        "flow_date": get_str(form, "flow_date") or existing["flow_date"],
        "description": get_opt_str(form, "description"),
        "notes": get_opt_str(form, "notes"),
        "cash_in": get_float(form, "cash_in", existing["cash_in"]),
        "cash_in_currency": get_str(form, "cash_in_currency")
        or existing["cash_in_currency"],
        "cash_out": get_float(form, "cash_out", existing["cash_out"]),
        "cash_out_currency": get_str(form, "cash_out_currency")
        or existing["cash_out_currency"],
        "status": get_str(form, "status") or existing["status"],
    }

    cf = await cashflow_service.update_cashflow(cashflow_id, data)
    source = get_str(form, "source", "cashflows")
    if source == "asset":
        return _asset_display_row_html(cf)
    return _display_row_html(cf)


@router.post("/cashflows/{cashflow_id}/delete", response_class=HTMLResponse)
async def cashflow_delete_submit(cashflow_id: int):
    await cashflow_service.delete_cashflow(cashflow_id)
    return HTMLResponse("")


@router.get("/cashflows/{cashflow_id}/edit-form", response_class=HTMLResponse)
async def cashflow_edit_form(cashflow_id: int, source: str = "cashflows"):
    cf = await cashflow_service.get_cashflow(cashflow_id)
    if not cf:
        raise HTTPException(status_code=404, detail="Cashflow not found")
    if source == "asset":
        return _asset_edit_row_html(cf)
    return _edit_row_html(cf)


@router.get("/cashflows/{cashflow_id}/display-row", response_class=HTMLResponse)
async def cashflow_display_row(cashflow_id: int, source: str = "cashflows"):
    cf = await cashflow_service.get_cashflow(cashflow_id)
    if not cf:
        raise HTTPException(status_code=404, detail="Cashflow not found")
    if source == "asset":
        return _asset_display_row_html(cf)
    return _display_row_html(cf)


# --- HTML helpers ---


def _fmt_usd(val) -> str:
    if val and float(val) > 0:
        return f"${float(val):,.2f}"
    return ""


def _currency_options(selected: str) -> str:
    return "".join(
        f'<option value="{c}" {"selected" if c == selected else ""}>{c}</option>'
        for c in _CURRENCIES
    )


def _status_options(selected: str) -> str:
    return "".join(
        f'<option value="{s}" {"selected" if s == selected else ""}>{s}</option>'
        for s in _STATUSES
    )


def _display_row_html(cf: dict) -> HTMLResponse:
    cid = cf["id"]
    return HTMLResponse(f"""
<tr id="cf-row-{cid}">
    <td class="mono">{_e(cf.get("flow_date"))}</td>
    <td>{_e(cf.get("asset_name"))}</td>
    <td class="mono text-muted">{_e(cf.get("symbol"))}</td>
    <td class="text-muted" style="max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap">{_e(cf.get("description"))}</td>
    <td class="text-muted" style="max-width:220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap">{_e(cf.get("notes"))}</td>
    <td class="text-right mono text-positive">{_fmt_usd(cf.get("cash_in_usd"))}</td>
    <td class="text-right mono text-negative">{_fmt_usd(cf.get("cash_out_usd"))}</td>
    <td><span class="text-muted" style="font-size:12px">{_e(cf.get("status"))}</span></td>
    <td>
        <div style="display:flex; gap:4px">
            <button class="btn btn-sm btn-secondary"
                    hx-get="/cashflows/{cid}/edit-form"
                    hx-target="#cf-row-{cid}"
                    hx-swap="outerHTML">Edit</button>
            <button class="btn btn-sm btn-danger"
                    hx-post="/cashflows/{cid}/delete"
                    hx-confirm="Delete this cash flow entry?"
                    hx-target="#cf-row-{cid}"
                    hx-swap="outerHTML">Del</button>
        </div>
    </td>
</tr>""")


def _edit_row_html(cf: dict) -> HTMLResponse:
    cid = cf["id"]
    return HTMLResponse(f"""
<tr id="cf-row-{cid}">
    <td><input type="date" name="flow_date" value="{_e(cf.get("flow_date"))}" style="width:130px"></td>
    <td class="text-muted" style="font-size:12px">{_e(cf.get("asset_name"))}</td>
    <td></td>
    <td><input type="text" name="description" value="{_e(cf.get("description"))}" placeholder="Description" style="width:100%"></td>
    <td><input type="text" name="notes" value="{_e(cf.get("notes"))}" placeholder="Notes" style="width:100%"></td>
    <td>
        <div style="display:flex; gap:4px; align-items:center; flex-wrap:nowrap">
            <input type="number" name="cash_in" step="0.01" value="{cf.get("cash_in", 0)}" style="width:90px">
            <select name="cash_in_currency" style="width:64px">{_currency_options(cf.get("cash_in_currency", "USD"))}</select>
        </div>
    </td>
    <td>
        <div style="display:flex; gap:4px; align-items:center; flex-wrap:nowrap">
            <input type="number" name="cash_out" step="0.01" value="{cf.get("cash_out", 0)}" style="width:90px">
            <select name="cash_out_currency" style="width:64px">{_currency_options(cf.get("cash_out_currency", "USD"))}</select>
        </div>
    </td>
    <td><select name="status" style="width:96px">{_status_options(cf.get("status", "Active"))}</select></td>
    <td>
        <div style="display:flex; gap:4px">
            <button class="btn btn-sm btn-primary"
                    hx-post="/cashflows/{cid}/edit"
                    hx-target="#cf-row-{cid}"
                    hx-swap="outerHTML"
                    hx-include="closest tr">Save</button>
            <button class="btn btn-sm btn-secondary"
                    hx-get="/cashflows/{cid}/display-row"
                    hx-target="#cf-row-{cid}"
                    hx-swap="outerHTML">Cancel</button>
        </div>
    </td>
</tr>""")


def _asset_display_row_html(cf: dict) -> HTMLResponse:
    cid = cf["id"]
    desc = _e(cf.get("description") or cf.get("notes"))
    return HTMLResponse(f"""
<tr id="asset-cf-row-{cid}">
    <td class="mono">{_e(cf.get("flow_date"))}</td>
    <td class="text-muted">{desc}</td>
    <td class="text-right mono text-positive">{_fmt_usd(cf.get("cash_in_usd"))}</td>
    <td class="text-right mono text-negative">{_fmt_usd(cf.get("cash_out_usd"))}</td>
    <td>
        <div style="display:flex; gap:4px">
            <button class="btn btn-sm btn-secondary"
                    hx-get="/cashflows/{cid}/edit-form?source=asset"
                    hx-target="#asset-cf-row-{cid}"
                    hx-swap="outerHTML">Edit</button>
            <button class="btn btn-sm btn-danger"
                    hx-post="/cashflows/{cid}/delete"
                    hx-confirm="Delete this transaction?"
                    hx-target="#asset-cf-row-{cid}"
                    hx-swap="outerHTML">Del</button>
        </div>
    </td>
</tr>""")


def _asset_edit_row_html(cf: dict) -> HTMLResponse:
    cid = cf["id"]
    desc = _e(cf.get("description") or cf.get("notes"))
    return HTMLResponse(f"""
<tr id="asset-cf-row-{cid}">
    <td><input type="date" name="flow_date" value="{_e(cf.get("flow_date"))}" style="width:130px"></td>
    <td><input type="text" name="description" value="{desc}" placeholder="Description" style="width:100%">
        <input type="hidden" name="source" value="asset"></td>
    <td><input type="number" name="cash_in" step="0.01" value="{cf.get("cash_in", 0)}" style="width:90px"></td>
    <td><input type="number" name="cash_out" step="0.01" value="{cf.get("cash_out", 0)}" style="width:90px"></td>
    <td>
        <div style="display:flex; gap:4px">
            <button class="btn btn-sm btn-primary"
                    hx-post="/cashflows/{cid}/edit"
                    hx-target="#asset-cf-row-{cid}"
                    hx-swap="outerHTML"
                    hx-include="closest tr">Save</button>
            <button class="btn btn-sm btn-secondary"
                    hx-get="/cashflows/{cid}/display-row?source=asset"
                    hx-target="#asset-cf-row-{cid}"
                    hx-swap="outerHTML">Cancel</button>
        </div>
    </td>
</tr>""")
