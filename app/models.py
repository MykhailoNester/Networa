from pydantic import BaseModel


# --- Sheets ---
class SheetCreate(BaseModel):
    name: str
    sort_order: int = 0


class SheetUpdate(BaseModel):
    name: str | None = None
    sort_order: int | None = None


class SheetResponse(BaseModel):
    id: int
    name: str
    sort_order: int
    created_at: str


# --- Asset Classes ---
class AssetClassResponse(BaseModel):
    id: int
    name: str
    display_name: str
    color: str


# --- Assets ---
class AssetCreate(BaseModel):
    name: str
    category: str = "asset"
    asset_class: str = "miscellaneous"
    sheet_id: int | None = None
    section_name: str | None = None
    value: float = 0
    currency: str = "USD"
    value_usd: float = 0
    ticker: str | None = None
    exchange: str | None = None
    price: float | None = None
    price_currency: str | None = None
    quantity: float | None = None
    cost_basis: float | None = None
    cost_basis_currency: str = "USD"
    cost: float | None = None
    cost_currency: str | None = None
    cash_in: float = 0
    cash_in_currency: str = "USD"
    cash_out: float = 0
    cash_out_currency: str = "USD"
    irr: float | None = None
    unrealized_gain: float | None = None
    unrealized_gain_currency: str | None = None
    ownership: float = 1.0
    investable: str = "non_investable"
    description: str | None = None
    notes: str | None = None
    sub_type: str | None = None
    asset_type: str | None = None
    purchase_date: str | None = None
    tax_rate: float | None = None
    tax_status: str | None = None
    tax_on_unrealized_gain: float | None = None
    tax_on_unrealized_gain_currency: str | None = None
    country: str | None = None
    region: str | None = None
    liquidity: str | None = None
    sector: str | None = None


class AssetUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    asset_class: str | None = None
    sheet_id: int | None = None
    section_name: str | None = None
    value: float | None = None
    currency: str | None = None
    value_usd: float | None = None
    ticker: str | None = None
    exchange: str | None = None
    price: float | None = None
    price_currency: str | None = None
    quantity: float | None = None
    cost_basis: float | None = None
    cost_basis_currency: str | None = None
    cost: float | None = None
    cost_currency: str | None = None
    cash_in: float | None = None
    cash_in_currency: str | None = None
    cash_out: float | None = None
    cash_out_currency: str | None = None
    irr: float | None = None
    unrealized_gain: float | None = None
    unrealized_gain_currency: str | None = None
    ownership: float | None = None
    investable: str | None = None
    description: str | None = None
    notes: str | None = None
    sub_type: str | None = None
    asset_type: str | None = None
    purchase_date: str | None = None
    tax_rate: float | None = None
    tax_status: str | None = None
    tax_on_unrealized_gain: float | None = None
    tax_on_unrealized_gain_currency: str | None = None
    country: str | None = None
    region: str | None = None
    liquidity: str | None = None
    sector: str | None = None


class AssetResponse(BaseModel):
    id: int
    name: str
    category: str
    asset_class: str
    sheet_id: int | None = None
    sheet_name: str | None = None
    section_name: str | None = None
    value: float
    currency: str
    value_usd: float
    ticker: str | None = None
    exchange: str | None = None
    price: float | None = None
    price_currency: str | None = None
    quantity: float | None = None
    cost_basis: float | None = None
    cost_basis_currency: str | None = None
    cost: float | None = None
    cost_currency: str | None = None
    cash_in: float
    cash_in_currency: str
    cash_out: float
    cash_out_currency: str
    irr: float | None = None
    unrealized_gain: float | None = None
    unrealized_gain_currency: str | None = None
    ownership: float
    investable: str
    description: str | None = None
    notes: str | None = None
    sub_type: str | None = None
    asset_type: str | None = None
    purchase_date: str | None = None
    tax_rate: float | None = None
    tax_status: str | None = None
    tax_on_unrealized_gain: float | None = None
    tax_on_unrealized_gain_currency: str | None = None
    country: str | None = None
    region: str | None = None
    liquidity: str | None = None
    sector: str | None = None
    is_active: int = 1
    sort_order: int = 0
    created_at: str | None = None
    updated_at: str | None = None
    gain_loss: float | None = None
    gain_loss_pct: float | None = None


# --- Cashflows ---
class CashflowCreate(BaseModel):
    asset_id: int | None = None
    asset_name: str | None = None
    symbol: str | None = None
    location: str | None = None
    description: str | None = None
    flow_date: str
    notes: str | None = None
    cash_in: float = 0
    cash_in_currency: str = "USD"
    cash_in_usd: float = 0
    cash_out: float = 0
    cash_out_currency: str = "USD"
    cash_out_usd: float = 0
    status: str = "Active"


class CashflowUpdate(BaseModel):
    asset_id: int | None = None
    asset_name: str | None = None
    symbol: str | None = None
    location: str | None = None
    description: str | None = None
    flow_date: str | None = None
    notes: str | None = None
    cash_in: float | None = None
    cash_in_currency: str | None = None
    cash_in_usd: float | None = None
    cash_out: float | None = None
    cash_out_currency: str | None = None
    cash_out_usd: float | None = None
    status: str | None = None


class CashflowResponse(BaseModel):
    id: int
    asset_id: int | None = None
    asset_name: str | None = None
    symbol: str | None = None
    location: str | None = None
    description: str | None = None
    flow_date: str
    notes: str | None = None
    cash_in: float
    cash_in_currency: str
    cash_in_usd: float
    cash_out: float
    cash_out_currency: str
    cash_out_usd: float
    status: str
    created_at: str | None = None
    updated_at: str | None = None


# --- Exchange Rates ---
class ExchangeRateCreate(BaseModel):
    from_currency: str
    to_currency: str = "USD"
    rate: float
    rate_date: str


class ExchangeRateResponse(BaseModel):
    id: int
    from_currency: str
    to_currency: str
    rate: float
    rate_date: str
    created_at: str | None = None


# --- Dashboard ---
class DashboardResponse(BaseModel):
    """Shape of GET /api/v1/dashboard. net_worth is total_assets - total_debts."""

    net_worth: float
    total_assets: float
    total_debts: float
    investable_assets: float
    investable_by_type: dict[str, float]
    non_investable_assets: float
    # Keyed by asset-class name; each value carries total/display_name/color.
    allocation_by_class: dict[str, dict]
    allocation_by_sheet: dict[str, float]
    debts_by_name: dict[str, float]
    assets_count: int
    debts_count: int
    ytd_change: float | None = None
    ytd_change_pct: float | None = None
