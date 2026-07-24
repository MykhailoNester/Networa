# CSV Import Format

Networa imports data from two generic CSV shapes: an **Assets CSV**
and a **Cashflows CSV**. Upload either file from the **Import** page in the
sidebar. Column names are matched by header; column order does not matter.

All amounts are stored internally in USD. Amounts given in another currency are
converted using the app's exchange rates (`currency_service.convert_to_usd`).

---

## Assets CSV

Imports rows into the `assets` table.

| Column | Required? | Maps to / notes |
|--------|-----------|-----------------|
| `name` | Required | Asset display name. |
| `asset_class` | Required | One of: `real_estate`, `precious_metal`, `cash`, `stock`, `fund`, `crypto`, `vehicle`, `investment`, `miscellaneous`. |
| `value` | Required | Numeric current value. |
| `currency` | Optional | ISO 4217 code. Defaults to `USD`. Converted to USD via `currency_service.convert_to_usd`. |
| `category` | Optional | `asset` or `debt`. Defaults to `asset`. |
| `sheet` | Optional | Sheet name to group the asset under. If the sheet does not exist it is auto-created. |
| `section` | Optional | Maps to `section_name`. |
| `ticker` | Optional | Symbol/ticker for stocks, funds, or crypto. |
| `quantity` | Optional | Units held. |
| `price` | Optional | Maps to `price` / `price_currency`. |
| `cost_basis` | Optional | Original cost basis. |
| `cost_basis_currency` | Optional | ISO 4217 code for the cost basis. Defaults to `USD`. |
| `notes` | Optional | Free-text notes. |

Notes:

- Any legacy external-ID column is no longer supported and will be ignored.
- Deduplication is optional. Skipping a row when an active asset with the same
  `name` already exists is acceptable; a plain insert is also fine.

---

## Cashflows CSV

Imports rows into the `cashflows` table.

| Column | Required? | Maps to / notes |
|--------|-----------|-----------------|
| `date` | Required | `YYYY-MM-DD`. Maps to `flow_date`. |
| `asset` | Optional | Matches an existing **active** asset by `name`; sets `asset_id` and `asset_name`. |
| `cash_in` | Optional | Inbound amount. Accepts a bare number (`65.25`) or a currency-prefixed form (`USD 65.25`). |
| `cash_out` | Optional | Outbound amount. Same formats as `cash_in`. |
| `currency` | Optional | ISO 4217 code. Defaults to `USD`. |
| `description` | Optional | Short description of the flow. |
| `notes` | Optional | Free-text notes. |
| `status` | Optional | Defaults to `Active`. |

Amount parsing for `cash_in` / `cash_out` is handled by the importer's existing
`_parse_currency_amount` / `_parse_float` helpers, which accept both the bare
number and the `"USD 65.25"` forms.
