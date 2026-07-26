from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import templates
from ..forms import get_float, get_opt_float, get_opt_str, get_str
from ..html import e, json_for_script
from ..models import AssetCreate, AssetUpdate
from ..services import asset_service

router = APIRouter()


# --- API Endpoints ---
@router.get("/api/v1/assets")
async def api_list_assets(
    category: str | None = None,
    sheet_id: int | None = None,
    asset_class: str | None = None,
):
    return await asset_service.list_assets(
        category=category, sheet_id=sheet_id, asset_class=asset_class
    )


@router.post("/api/v1/assets")
async def api_create_asset(data: AssetCreate):
    return await asset_service.create_asset(data)


@router.get("/api/v1/assets/{asset_id}")
async def api_get_asset(asset_id: int):
    asset = await asset_service.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


@router.put("/api/v1/assets/{asset_id}")
async def api_update_asset(asset_id: int, data: AssetUpdate):
    asset = await asset_service.update_asset(asset_id, data)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


@router.delete("/api/v1/assets/{asset_id}")
async def api_delete_asset(asset_id: int):
    await asset_service.delete_asset(asset_id)
    return {"status": "deleted"}


@router.get("/api/v1/asset-classes")
async def api_get_asset_classes():
    return await asset_service.get_asset_classes()


# --- HTML Pages ---
@router.get("/assets", response_class=HTMLResponse)
async def assets_page(request: Request, sheet_id: int | None = None, all: int = 0):
    from ..database import get_db

    db = await get_db()

    cursor = await db.execute("SELECT * FROM sheets ORDER BY sort_order")
    sheets = [dict(row) for row in await cursor.fetchall()]

    # Default to first sheet when no filter specified
    if sheet_id is None and not all and sheets:
        return RedirectResponse(f"/assets?sheet_id={sheets[0]['id']}", status_code=302)

    assets = await asset_service.list_assets(category="asset", sheet_id=sheet_id)

    total_value = sum((a.get("current_value_usd") or 0) for a in assets)
    total_in = sum((a.get("cash_in") or 0) for a in assets)
    total_out = sum((a.get("cash_out") or 0) for a in assets)
    asset_classes = await asset_service.get_asset_classes()

    # Per-sheet totals using latest snapshot values
    cursor = await db.execute("""
        SELECT s.id, s.name, s.sort_order,
               COALESCE(SUM(COALESCE(snap.value_usd, a.value_usd)), 0) as total
        FROM sheets s
        LEFT JOIN assets a ON a.sheet_id = s.id AND a.is_active = 1 AND a.category = 'asset'
        LEFT JOIN (
            SELECT asset_id, value_usd
            FROM snapshots
            WHERE (asset_id, snapshot_date) IN (
                SELECT asset_id, MAX(snapshot_date) FROM snapshots GROUP BY asset_id
            )
        ) snap ON a.id = snap.asset_id
        GROUP BY s.id, s.name, s.sort_order
        ORDER BY s.sort_order
    """)
    sheets_with_totals = [dict(row) for row in await cursor.fetchall()]

    return templates.TemplateResponse(
        request,
        "assets/list.html",
        {
            "request": request,
            "sheets": sheets,
            "sheets_with_totals": sheets_with_totals,
            "assets": assets,
            "total_value": total_value,
            "total_in": total_in,
            "total_out": total_out,
            "active_sheet_id": sheet_id,
            "asset_classes": asset_classes,
            "page": "assets",
        },
    )


@router.get("/assets/{asset_id}", response_class=HTMLResponse)
async def asset_detail_page(request: Request, asset_id: int):
    asset = await asset_service.get_asset(asset_id)
    if not asset:
        return RedirectResponse("/assets")

    from ..database import get_db

    db = await get_db()
    cursor = await db.execute("SELECT * FROM sheets ORDER BY sort_order")
    sheets = [dict(row) for row in await cursor.fetchall()]
    asset_classes = await asset_service.get_asset_classes()

    cursor = await db.execute(
        "SELECT id, snapshot_date, value, currency, value_usd FROM snapshots WHERE asset_id = ? ORDER BY snapshot_date",
        (asset_id,),
    )
    snapshots = [dict(row) for row in await cursor.fetchall()]

    cursor = await db.execute(
        "SELECT * FROM cashflows WHERE asset_id = ? ORDER BY flow_date DESC",
        (asset_id,),
    )
    cashflows = [dict(row) for row in await cursor.fetchall()]

    # Compute day change and all-time change from snapshots
    day_change = None
    alltime_change = None
    if len(snapshots) >= 2:
        latest_val = snapshots[-1]["value_usd"]
        prev_val = snapshots[-2]["value_usd"]
        first_val = snapshots[0]["value_usd"]
        if prev_val:
            day_change = {
                "value": latest_val - prev_val,
                "pct": (latest_val - prev_val) / prev_val * 100,
            }
        if first_val:
            alltime_change = {
                "value": latest_val - first_val,
                "pct": (latest_val - first_val) / first_val * 100,
            }

    current_value_usd = asset.get("current_value_usd") or asset.get("value_usd") or 0
    cf_total_in = sum((cf.get("cash_in_usd") or 0) for cf in cashflows)
    cf_total_out = sum((cf.get("cash_out_usd") or 0) for cf in cashflows)

    return templates.TemplateResponse(
        request,
        "assets/detail.html",
        {
            "request": request,
            "asset": asset,
            "current_value_usd": current_value_usd,
            "cf_total_in": cf_total_in,
            "cf_total_out": cf_total_out,
            "sheets": sheets,
            "asset_classes": asset_classes,
            "snapshots": snapshots,
            "cashflows": cashflows,
            "day_change": day_change,
            "alltime_change": alltime_change,
            "today": date.today().isoformat(),  # noqa: DTZ011 - local calendar date
            "page": "debts" if asset.get("category") == "debt" else "assets",
        },
    )


@router.post("/assets/{asset_id}/edit")
async def asset_edit_submit(request: Request, asset_id: int):
    form = await request.form()
    updates: dict[str, Any] = {}

    str_fields = [
        "name",
        "currency",
        "asset_class",
        "ticker",
        "description",
        "notes",
        "investable",
        "purchase_date",
        "tax_status",
        "cash_in_currency",
        "cash_out_currency",
        "unrealized_gain_currency",
        "cost_basis_currency",
        "liquidity",
        "country",
        "region",
        "sector",
    ]
    # Note: "value" is intentionally excluded — values are managed via the VALUE tab (snapshots)
    float_fields = [
        "quantity",
        "cost_basis",
        "tax_rate",
        "cash_in",
        "cash_out",
        "irr",
        "unrealized_gain",
    ]

    for key in str_fields:
        sval = get_opt_str(form, key)
        if sval is not None:
            updates[key] = sval

    for key in float_fields:
        fval = get_opt_float(form, key)
        if fval is not None:
            updates[key] = fval

    # ownership is submitted as 0-100 percentage, stored as 0-1 decimal
    ownership_pct = get_opt_float(form, "ownership")
    if ownership_pct is not None:
        updates["ownership"] = ownership_pct / 100.0

    sheet_id_raw = form.get("sheet_id")
    if isinstance(sheet_id_raw, str) and sheet_id_raw:
        try:
            updates["sheet_id"] = int(sheet_id_raw)
        except ValueError:
            pass

    if updates:
        data = AssetUpdate(**updates)
        await asset_service.update_asset(asset_id, data)

    tab = get_str(form, "tab", "overview")
    return RedirectResponse(f"/assets/{asset_id}?saved=1&tab={tab}", status_code=303)


@router.post("/assets/create")
async def asset_create_submit(request: Request):
    form = await request.form()

    currency = get_str(form, "currency", "USD")
    value = get_float(form, "value")

    data = AssetCreate(
        name=get_str(form, "name", "New Asset"),
        category=get_str(form, "category", "asset"),
        asset_class=get_str(form, "asset_class", "miscellaneous"),
        value=value,
        currency=currency,
        ticker=get_opt_str(form, "ticker"),
        quantity=get_float(form, "quantity") or None,
        cost_basis=get_float(form, "cost_basis") or None,
        purchase_date=get_opt_str(form, "purchase_date"),
        investable=get_str(form, "investable", "non_investable"),
        description=get_opt_str(form, "description"),
    )
    sheet_id_raw = form.get("sheet_id")
    if isinstance(sheet_id_raw, str) and sheet_id_raw:
        try:
            data.sheet_id = int(sheet_id_raw)
        except ValueError:
            pass
    asset = await asset_service.create_asset(data)

    # Create initial snapshot if a non-zero value was provided
    if value and value > 0:
        from ..database import get_db

        db = await get_db()
        value_usd = asset["value_usd"] or 0
        await db.execute(
            "INSERT OR REPLACE INTO snapshots (snapshot_date, asset_id, value, currency, value_usd) VALUES (?, ?, ?, ?, ?)",
            (date.today().isoformat(), asset["id"], value, currency, value_usd),  # noqa: DTZ011 - local calendar date
        )
        await db.commit()

    return RedirectResponse(f"/assets/{asset['id']}", status_code=303)


@router.post("/assets/{asset_id}/delete")
async def asset_delete_submit(asset_id: int):
    await asset_service.delete_asset(asset_id)
    return RedirectResponse("/assets", status_code=303)


# --- HTMX Inline Value Edit ---
@router.get("/assets/{asset_id}/inline-edit", response_class=HTMLResponse)
async def asset_inline_edit_form(asset_id: int):
    asset = await asset_service.get_asset(asset_id)
    if not asset:
        return HTMLResponse("", status_code=404)
    # Show current value (from latest snapshot) as default
    current_val = (
        asset.get("current_value_usd")
        or asset.get("value_usd")
        or asset.get("value")
        or 0
    )
    # For non-USD assets, show native value
    if asset["currency"] != "USD":
        current_val = asset.get("value") or 0
    return HTMLResponse(f"""
<td id="value-cell-{asset_id}" class="text-right">
    <form hx-post="/assets/{asset_id}/inline-save"
          hx-target="#value-cell-{asset_id}"
          hx-swap="outerHTML"
          style="display:inline-flex; gap:4px; align-items:center; justify-content:flex-end">
        <input type="number" name="value" step="0.01" value="{current_val}"
               style="width:110px; text-align:right" autofocus>
        <button type="submit" class="btn btn-primary btn-sm" style="padding:4px 8px">&#10003;</button>
        <button type="button" class="btn btn-secondary btn-sm" style="padding:4px 8px"
                hx-get="/assets/{asset_id}/inline-display"
                hx-target="#value-cell-{asset_id}" hx-swap="outerHTML">&#10005;</button>
    </form>
</td>
""")


@router.post("/assets/{asset_id}/inline-save", response_class=HTMLResponse)
async def asset_inline_save(asset_id: int, request: Request):
    """Save inline value edit: inserts a snapshot for today and updates asset cache."""
    from ..database import get_db
    from ..services import currency_service

    form = await request.form()
    # Kept inline (not get_float): this handler intentionally has no try/except,
    # so a non-numeric value raises rather than silently falling back to 0.
    raw_value = form.get("value", 0)
    value = float(raw_value) if isinstance(raw_value, (str, int)) else 0.0

    asset = await asset_service.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    currency = asset.get("currency", "USD")
    value_usd = await currency_service.convert_to_usd(value, currency)
    today = date.today().isoformat()  # noqa: DTZ011 - local calendar date

    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO snapshots (snapshot_date, asset_id, value, currency, value_usd) VALUES (?, ?, ?, ?, ?)",
        (today, asset_id, value, currency, round(value_usd, 2)),
    )
    # Keep assets table in sync as denormalized cache
    await db.execute(
        "UPDATE assets SET value = ?, value_usd = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (value, round(value_usd, 2), asset_id),
    )
    await db.commit()

    asset = await asset_service.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return HTMLResponse(_value_cell_html(asset))


@router.get("/assets/{asset_id}/inline-display", response_class=HTMLResponse)
async def asset_inline_display(asset_id: int):
    asset = await asset_service.get_asset(asset_id)
    if not asset:
        return HTMLResponse("", status_code=404)
    return HTMLResponse(_value_cell_html(asset))


def _value_cell_html(asset: dict) -> str:
    from ..services.currency_service import display_state

    aid = asset["id"]
    # Escaped once here so every interpolation below is safe.
    disp_cur = e(display_state()["currency"])
    disp_sym = e(display_state()["symbol"])
    disp_mult = display_state()["multiplier"]
    current_usd = asset.get("current_value_usd") or asset.get("value_usd") or 0
    disp_val = current_usd * disp_mult

    if asset["currency"] != "USD":
        native = f"{e(asset['currency'])} {asset['value']:,.0f}"
        if asset["currency"] == display_state()["currency"]:
            main = native
        else:
            main = f'{native} <div class="text-muted" style="font-size:11px">{disp_sym}{disp_val:,.0f} {disp_cur}</div>'
    else:
        main = f"{disp_sym}{disp_val:,.0f}"

    ticker_line = ""
    if asset.get("ticker"):
        qty = f" {asset['quantity']:,.0f}" if asset.get("quantity") else ""
        ticker_line = f'<div class="text-muted" style="font-size:11px; margin-top:2px">{e(asset["ticker"])}{qty}</div>'
    tone = " text-negative" if asset.get("category") == "debt" else ""
    return f"""<td id="value-cell-{aid}" class="text-right"
    hx-get="/assets/{aid}/inline-edit"
    hx-target="#value-cell-{aid}" hx-swap="outerHTML"
    style="cursor:pointer" title="Click to record new value">
    <div class="mono{tone}" style="font-size:15px; font-weight:600">{main}</div>
    {ticker_line}
</td>"""


# --- Snapshot inline edit (VALUE tab history table) ---


async def _build_value_oob_html(db, asset_id: int) -> str:
    """Build HTMX OOB swap fragments: header value, stats cards, and chart data update."""
    from ..services.currency_service import CURRENCY_SYMBOLS as _CURRENCY_SYMBOLS
    from ..services.currency_service import display_state

    asset = await asset_service.get_asset(asset_id)
    if not asset:
        return ""

    current_usd = asset.get("current_value_usd") or asset.get("value_usd") or 0
    state = display_state()
    # Escaped once here so every interpolation below is safe.
    disp_sym = e(state["symbol"])
    disp_mult = state["multiplier"]
    disp_cur = e(state["currency"])

    def _fmt(val):
        """Format USD value in display currency."""
        return f"{disp_sym}{(val or 0) * disp_mult:,.0f}"

    def _fmt_change(val):
        """Format a signed change value: +$1,234 or -$1,234"""
        converted = (val or 0) * disp_mult
        if val >= 0:
            return f"+{disp_sym}{converted:,.0f}"
        return f"-{disp_sym}{abs(converted):,.0f}"

    # ── Header OOB ────────────────────────────────────────────
    native_html = ""
    if asset.get("currency", "USD") != "USD":
        sym = e(
            _CURRENCY_SYMBOLS.get(
                (asset["currency"]).upper(), asset["currency"] + "\u202f"
            )
        )
        native_html = (
            f'<div class="text-muted mono" style="font-size: 14px;">'
            f"{sym}{(asset.get('value') or 0):,.0f} {e(asset['currency'])}</div>\n"
        )

    # Keep in step with assets/detail.html, which hides both badges for debts.
    is_debt = asset.get("category") == "debt"

    tax_html = ""
    estimated_tax = asset.get("estimated_tax")
    if estimated_tax and not is_debt:
        tax_html = (
            f'<span style="background: rgba(245,158,11,0.15); color: #f59e0b; '
            f'border-radius: 12px; padding: 2px 10px; font-size: 12px; font-weight: 600;">'
            f"Est. Tax: {_fmt(estimated_tax)}</span>\n"
        )

    gain_html = ""
    gain_loss = asset.get("gain_loss")
    gain_loss_pct = asset.get("gain_loss_pct")
    if gain_loss is not None and not is_debt:
        g_cls = "text-positive" if gain_loss > 0 else "text-negative"
        pct_str = f" ({gain_loss_pct:+.1f}%)" if gain_loss_pct is not None else ""
        disp_gain = (gain_loss or 0) * disp_mult
        sign = "+" if gain_loss >= 0 else ""
        if gain_loss >= 0:
            g_val = f"{sign}{disp_sym}{disp_gain:,.0f}"
        else:
            g_val = f"{disp_sym}{disp_gain:,.0f}"  # negative number includes minus
        gain_html = (
            f'<div class="{g_cls} mono" style="font-size: 13px;">'
            f"{g_val}{pct_str}</div>\n"
        )

    header_oob = (
        f'<div id="asset-value-header" hx-swap-oob="true" '
        f'style="text-align: right; display: flex; flex-direction: column; align-items: flex-end; gap: 6px;">\n'
        f'<div class="mono" style="font-size: 30px; font-weight: 700; line-height: 1.1;">'
        f"{_fmt(current_usd)} {disp_cur}</div>\n"
        f"{native_html}{tax_html}{gain_html}"
        f"</div>\n"
    )

    # ── Stats OOB ─────────────────────────────────────────────
    cursor = await db.execute(
        "SELECT id, snapshot_date, value, currency, value_usd FROM snapshots "
        "WHERE asset_id = ? ORDER BY snapshot_date",
        (asset_id,),
    )
    snapshots = [dict(row) for row in await cursor.fetchall()]

    day_change = None
    alltime_change = None
    if len(snapshots) >= 2:
        latest_val = snapshots[-1]["value_usd"] or 0
        prev_val = snapshots[-2]["value_usd"] or 0
        first_val = snapshots[0]["value_usd"] or 0
        if prev_val:
            day_change = {
                "value": latest_val - prev_val,
                "pct": (latest_val - prev_val) / prev_val * 100,
            }
        if first_val:
            alltime_change = {
                "value": latest_val - first_val,
                "pct": (latest_val - first_val) / first_val * 100,
            }

    def _stat_card(label, change):
        if change:
            cls = "text-positive" if change["value"] >= 0 else "text-negative"
            return (
                f'<div class="card" style="text-align: center; padding: 16px;">'
                f'<div class="text-muted" style="font-size: 11px; text-transform: uppercase; '
                f'letter-spacing: 1px; margin-bottom: 6px;">{label}</div>'
                f'<div class="mono {cls}" style="font-size: 20px; font-weight: 700;">'
                f"{_fmt_change(change['value'])}</div>"
                f'<div class="mono {cls}" style="font-size: 13px;">{change["pct"]:+.2f}%</div>'
                f"</div>"
            )
        return (
            f'<div class="card" style="text-align: center; padding: 16px;">'
            f'<div class="text-muted" style="font-size: 11px; text-transform: uppercase; '
            f'letter-spacing: 1px; margin-bottom: 6px;">{label}</div>'
            f'<div class="text-muted">--</div>'
            f"</div>"
        )

    stats_oob = (
        f'<div id="value-stats-cards" hx-swap-oob="true" '
        f'style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px;">\n'
        f"{_stat_card('1 DAY', day_change)}\n"
        f"{_stat_card('ALL-TIME', alltime_change)}\n"
        f"</div>\n"
    )

    # ── Chart data OOB ────────────────────────────────────────
    # json_for_script, not json.dumps: snapshots carry a user-set currency, and a
    # value containing "</script>" would otherwise break out of the block below.
    snaps_json = json_for_script(snapshots)
    chart_oob = (
        f'<div id="snap-chart-data" hx-swap-oob="true" style="display:none">'
        f"<script>"
        f"snapData={snaps_json};"
        f"if(activeChart){{"
        f"var _f=filterSnapshots(currentRange);"
        f"activeChart.data.labels=_f.map(function(s){{return s.snapshot_date;}});"
        f"activeChart.data.datasets[0].data=_f.map(function(s){{return s.value_usd;}});"
        f"activeChart.update();"
        f"}}"
        f"</script>"
        f"</div>\n"
    )

    return header_oob + stats_oob + chart_oob


async def _sync_asset_value_from_latest_snapshot(db, asset_id: int):
    """Keep assets.value and assets.value_usd in sync with the latest snapshot."""
    cursor = await db.execute(
        "SELECT value, value_usd FROM snapshots WHERE asset_id = ? ORDER BY snapshot_date DESC LIMIT 1",
        (asset_id,),
    )
    row = await cursor.fetchone()
    if row:
        await db.execute(
            "UPDATE assets SET value = ?, value_usd = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (row["value"], row["value_usd"], asset_id),
        )


def _snap_display_row(snap: dict, has_ticker: bool, ticker: str = "") -> str:
    from ..services.currency_service import display_state

    sid = snap["id"]
    disp_sym = e(display_state()["symbol"])
    disp_mult = display_state()["multiplier"]
    converted = (snap["value_usd"] or 0) * disp_mult
    val_fmt = f"{disp_sym}{converted:,.2f}"
    ticker_cell = f'<td class="text-muted mono">{e(ticker)}</td>' if has_ticker else ""
    return f"""
<tr id="snap-row-{sid}">
    <td class="mono">{e(snap["snapshot_date"])}</td>
    {ticker_cell}
    <td class="text-right mono">{val_fmt}</td>
    <td>
        <div style="display:flex; gap:4px">
            <button class="btn btn-sm btn-secondary"
                    hx-get="/assets/{snap["asset_id"]}/snapshots/{sid}/edit-row"
                    hx-target="#snap-row-{sid}"
                    hx-swap="outerHTML">Edit</button>
            <button class="btn btn-sm btn-danger"
                    hx-post="/assets/{snap["asset_id"]}/snapshots/{sid}/delete"
                    hx-target="#snap-row-{sid}"
                    hx-swap="outerHTML"
                    hx-confirm="Delete this value record?">Delete</button>
        </div>
    </td>
</tr>"""


@router.get(
    "/assets/{asset_id}/snapshots/{snapshot_id}/edit-row", response_class=HTMLResponse
)
async def snapshot_edit_row(asset_id: int, snapshot_id: int):
    from ..database import get_db

    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM snapshots WHERE id = ? AND asset_id = ?", (snapshot_id, asset_id)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    snap = dict(row)
    asset = await asset_service.get_asset(asset_id)
    has_ticker = bool(asset and asset.get("ticker"))
    ticker = asset.get("ticker", "") if asset else ""
    ticker_cell = f'<td class="text-muted mono">{e(ticker)}</td>' if has_ticker else ""
    return HTMLResponse(f"""
<tr id="snap-row-{snapshot_id}">
    <td class="mono">{e(snap["snapshot_date"])}</td>
    {ticker_cell}
    <td>
        <input type="number" name="value_usd" id="snap-val-{snapshot_id}"
               step="0.01" value="{snap["value_usd"]}"
               style="width:130px; text-align:right">
    </td>
    <td>
        <div style="display:flex; gap:4px">
            <button class="btn btn-sm btn-primary"
                    hx-post="/assets/{asset_id}/snapshots/{snapshot_id}/edit"
                    hx-target="#snap-row-{snapshot_id}"
                    hx-swap="outerHTML"
                    hx-include="#snap-val-{snapshot_id}">Save</button>
            <button class="btn btn-sm btn-secondary"
                    hx-get="/assets/{asset_id}/snapshots/{snapshot_id}/display-row"
                    hx-target="#snap-row-{snapshot_id}"
                    hx-swap="outerHTML">Cancel</button>
            <button class="btn btn-sm btn-danger"
                    hx-post="/assets/{asset_id}/snapshots/{snapshot_id}/delete"
                    hx-target="#snap-row-{snapshot_id}"
                    hx-swap="outerHTML"
                    hx-confirm="Delete this value record?">Delete</button>
        </div>
    </td>
</tr>""")


@router.post(
    "/assets/{asset_id}/snapshots/{snapshot_id}/edit", response_class=HTMLResponse
)
async def snapshot_edit_save(asset_id: int, snapshot_id: int, request: Request):
    from ..database import get_db

    form = await request.form()
    value_usd = get_float(form, "value_usd")
    db = await get_db()
    await db.execute(
        "UPDATE snapshots SET value = ?, value_usd = ? WHERE id = ? AND asset_id = ?",
        (value_usd, value_usd, snapshot_id, asset_id),
    )
    await _sync_asset_value_from_latest_snapshot(db, asset_id)
    await db.commit()
    cursor = await db.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,))
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    snap = dict(row)
    asset = await asset_service.get_asset(asset_id)
    has_ticker = bool(asset and asset.get("ticker"))
    ticker = asset.get("ticker", "") if asset else ""
    oob = await _build_value_oob_html(db, asset_id)
    return HTMLResponse(_snap_display_row(snap, has_ticker, ticker) + oob)


@router.get(
    "/assets/{asset_id}/snapshots/{snapshot_id}/display-row",
    response_class=HTMLResponse,
)
async def snapshot_display_row(asset_id: int, snapshot_id: int):
    from ..database import get_db

    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM snapshots WHERE id = ? AND asset_id = ?", (snapshot_id, asset_id)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    snap = dict(row)
    asset = await asset_service.get_asset(asset_id)
    has_ticker = bool(asset and asset.get("ticker"))
    ticker = asset.get("ticker", "") if asset else ""
    return HTMLResponse(_snap_display_row(snap, has_ticker, ticker))


@router.post(
    "/assets/{asset_id}/snapshots/{snapshot_id}/delete", response_class=HTMLResponse
)
async def snapshot_delete(asset_id: int, snapshot_id: int):
    from ..database import get_db

    db = await get_db()
    await db.execute(
        "DELETE FROM snapshots WHERE id = ? AND asset_id = ?", (snapshot_id, asset_id)
    )
    await _sync_asset_value_from_latest_snapshot(db, asset_id)
    await db.commit()
    # OOB elements update header/stats/chart; main response is empty → row gets removed (outerHTML swap)
    oob = await _build_value_oob_html(db, asset_id)
    return HTMLResponse(oob)


@router.post("/assets/{asset_id}/snapshots/add-auto", response_class=HTMLResponse)
async def snapshot_add_auto(asset_id: int, request: Request):
    """Add a snapshot using market price (for ticker assets) or NBU exchange rate."""
    from ..database import get_db
    from ..services import currency_service, snapshot_service

    form = await request.form()
    snapshot_date = get_str(form, "snapshot_date") or date.today().isoformat()  # noqa: DTZ011 - local calendar date

    asset = await asset_service.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    asset_value = asset.get("value") or 0.0
    asset_currency = asset.get("currency") or "USD"
    ticker = asset.get("ticker")
    quantity = asset.get("quantity")
    db = await get_db()

    ticker_success = False

    if ticker and quantity:
        # Shared with the batch "Refresh prices" action (snapshot_service).
        outcome = await snapshot_service.revalue_asset_from_market(
            db, asset, snapshot_date
        )
        ticker_success = outcome["status"] == "updated"
        if ticker_success:
            # The dashboard's freshness line exists so staleness is never
            # hidden, so it has to count this path too: pricing one asset here
            # is still "a market price was fetched just now". Only on a real
            # market hit — the NBU/stored-value fallback below is not one.
            await snapshot_service.stamp_prices_refreshed()

    if not ticker_success:
        # Fall back to NBU exchange rate (for non-USD assets) or stored value
        if asset_currency != "USD":
            nbu_rates = await currency_service.fetch_rates_from_nbu(snapshot_date)
            rate = nbu_rates.get(asset_currency) or await currency_service.get_rate(
                asset_currency
            )
            value_usd = asset_value * rate
        else:
            value_usd = asset_value

        await db.execute(
            """INSERT OR REPLACE INTO snapshots
               (snapshot_date, asset_id, value, currency, value_usd)
               VALUES (?, ?, ?, ?, ?)""",
            (snapshot_date, asset_id, asset_value, asset_currency, round(value_usd, 2)),
        )
        await _sync_asset_value_from_latest_snapshot(db, asset_id)
        await db.commit()

    # Re-fetch asset and snapshots for the HTML response
    asset = await asset_service.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    cursor = await db.execute(
        "SELECT * FROM snapshots WHERE asset_id = ? ORDER BY snapshot_date DESC",
        (asset_id,),
    )
    snapshots = [dict(row) for row in await cursor.fetchall()]
    has_ticker = bool(asset.get("ticker"))
    ticker_val = asset.get("ticker", "") or ""
    rows_html = "\n".join(
        _snap_display_row(s, has_ticker, ticker_val) for s in snapshots
    )
    if len(snapshots) == 1:
        return HTMLResponse(
            rows_html, headers={"HX-Redirect": f"/assets/{asset_id}?tab=value"}
        )
    oob = await _build_value_oob_html(db, asset_id)
    return HTMLResponse(rows_html + oob)


@router.post("/assets/{asset_id}/snapshots/add", response_class=HTMLResponse)
async def snapshot_add(asset_id: int, request: Request):
    from ..database import get_db

    form = await request.form()
    snapshot_date = get_str(form, "snapshot_date") or date.today().isoformat()  # noqa: DTZ011 - local calendar date
    value_usd = get_float(form, "value_usd")
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO snapshots (snapshot_date, asset_id, value, currency, value_usd) VALUES (?, ?, ?, 'USD', ?)",
        (snapshot_date, asset_id, value_usd, value_usd),
    )
    await _sync_asset_value_from_latest_snapshot(db, asset_id)
    await db.commit()
    cursor = await db.execute(
        "SELECT * FROM snapshots WHERE asset_id = ? ORDER BY snapshot_date DESC",
        (asset_id,),
    )
    snapshots = [dict(row) for row in await cursor.fetchall()]
    asset = await asset_service.get_asset(asset_id)
    has_ticker = bool(asset and asset.get("ticker"))
    ticker = asset.get("ticker", "") if asset else ""
    rows_html = "\n".join(_snap_display_row(s, has_ticker, ticker) for s in snapshots)
    # First snapshot: reload the page so chart and stats section appear
    if len(snapshots) == 1:
        return HTMLResponse(
            rows_html, headers={"HX-Redirect": f"/assets/{asset_id}?tab=value"}
        )
    oob = await _build_value_oob_html(db, asset_id)
    return HTMLResponse(rows_html + oob)
