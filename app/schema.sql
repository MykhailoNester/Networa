-- Networa — canonical database schema.
-- This single file is the source of truth for the schema and replaces the old
-- migrations/ directory. init_db() applies it (idempotently) on startup, and
-- scripts/seed_demo.py applies it before loading the shipped demo dataset.
-- To evolve the schema, edit this file (all statements are IF NOT EXISTS-safe).

-- Organizational grouping (sheets)
CREATE TABLE IF NOT EXISTS sheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Asset class reference for UI dropdowns and chart colors
CREATE TABLE IF NOT EXISTS asset_classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '#888888'
);

-- Core assets table (both assets and debts)
CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'asset',
    asset_class TEXT NOT NULL,
    sheet_id INTEGER REFERENCES sheets(id),
    section_name TEXT,

    -- Current valuation
    value REAL NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'USD',
    value_usd REAL NOT NULL DEFAULT 0,

    -- Market data
    ticker TEXT,
    exchange TEXT,
    price REAL,
    price_currency TEXT,
    quantity REAL,

    -- Cost basis & returns
    cost_basis REAL,
    cost_basis_currency TEXT DEFAULT 'USD',
    cost REAL,
    cost_currency TEXT,
    cash_in REAL DEFAULT 0,
    cash_in_currency TEXT DEFAULT 'USD',
    cash_out REAL DEFAULT 0,
    cash_out_currency TEXT DEFAULT 'USD',
    irr REAL,
    unrealized_gain REAL,
    unrealized_gain_currency TEXT DEFAULT 'USD',

    -- Metadata
    ownership REAL DEFAULT 1.0,
    investable TEXT DEFAULT 'non_investable',
    description TEXT,
    notes TEXT,
    sub_type TEXT,
    asset_type TEXT,
    purchase_date DATE,
    holding_period_days INTEGER,
    is_manual INTEGER DEFAULT 1,

    -- Tax fields
    tax_rate REAL,
    tax_status TEXT,
    tax_on_unrealized_gain REAL,
    tax_on_unrealized_gain_currency TEXT,

    -- Geography
    country TEXT,
    region TEXT,

    -- Liquidity & sector
    liquidity TEXT,
    sector TEXT,

    -- Status
    is_active INTEGER DEFAULT 1,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Historical value snapshots per asset
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date DATE NOT NULL,
    asset_id INTEGER REFERENCES assets(id),
    value REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    value_usd REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(snapshot_date, asset_id)
);

-- Aggregated daily net worth
CREATE TABLE IF NOT EXISTS net_worth_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date DATE NOT NULL UNIQUE,
    total_assets_usd REAL NOT NULL DEFAULT 0,
    total_debts_usd REAL NOT NULL DEFAULT 0,
    net_worth_usd REAL NOT NULL DEFAULT 0,
    investable_total_usd REAL DEFAULT 0,
    investable_breakdown TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Cash flow entries
CREATE TABLE IF NOT EXISTS cashflows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER REFERENCES assets(id),
    asset_name TEXT,
    symbol TEXT,
    location TEXT,
    description TEXT,
    flow_date DATE NOT NULL,
    notes TEXT,
    cash_in REAL DEFAULT 0,
    cash_in_currency TEXT DEFAULT 'USD',
    cash_in_usd REAL DEFAULT 0,
    cash_out REAL DEFAULT 0,
    cash_out_currency TEXT DEFAULT 'USD',
    cash_out_usd REAL DEFAULT 0,
    status TEXT DEFAULT 'Active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Exchange rates
CREATE TABLE IF NOT EXISTS exchange_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_currency TEXT NOT NULL,
    to_currency TEXT NOT NULL DEFAULT 'USD',
    rate REAL NOT NULL,
    rate_date DATE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(from_currency, to_currency, rate_date)
);

-- Key/value app settings (e.g. display_currency preference)
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_assets_category ON assets(category);
CREATE INDEX IF NOT EXISTS idx_assets_asset_class ON assets(asset_class);
CREATE INDEX IF NOT EXISTS idx_assets_sheet_id ON assets(sheet_id);
CREATE INDEX IF NOT EXISTS idx_assets_is_active ON assets(is_active);
CREATE INDEX IF NOT EXISTS idx_snapshots_date ON snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_snapshots_asset ON snapshots(asset_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_asset_date ON snapshots(asset_id, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_net_worth_history_date ON net_worth_history(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_cashflows_asset ON cashflows(asset_id);
CREATE INDEX IF NOT EXISTS idx_cashflows_date ON cashflows(flow_date);

-- Seed data: default display currency + the nine asset classes with chart colors.
INSERT OR IGNORE INTO settings (key, value) VALUES ('display_currency', 'USD');

INSERT OR IGNORE INTO asset_classes (name, display_name, color) VALUES
    ('real_estate',    'Real Estate',    '#7c4dff'),
    ('precious_metal', 'Precious Metal', '#00bfa5'),
    ('cash',           'Cash',           '#00c853'),
    ('stock',          'Stock',          '#2979ff'),
    ('fund',           'Fund',           '#448aff'),
    ('crypto',         'Crypto',         '#ff9100'),
    ('vehicle',        'Vehicle',        '#ff6d00'),
    ('investment',     'Investment',     '#ffab00'),
    ('miscellaneous',  'Miscellaneous',  '#78909c');
