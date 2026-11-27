# AI Business Review — Data Contract & Provider Access (#40)

Status: **PROPOSED / Contract Verified (Provider Unconfigured)**

## Candidate Model & Environment Variables
- `MARKETSTUDIO_AI_PROVIDER=gemini`
- `MARKETSTUDIO_AI_MODEL=gemini-2.5-flash`
- `GEMINI_API_KEY` (or `GOOGLE_API_KEY`)

## Cost, Quota & Open Decisions (D12 / D17)
- **D12 / D17 (OPEN)**: Model ID final, budget/quota API aktual, dan approval provider berbayar masih menunggu keputusan Product Owner (PO).
- Tidak ada pengadaan layanan berbayar otomatis; integrasi live hanya berjalan jika env var legal/zero-cost sudah dikonfigurasi di runtime.
Runtime environment currently has none of the above variables set (`configured=False`).
To enable live provider calls without changing code, set:
`MARKETSTUDIO_AI_PROVIDER=gemini`, `MARKETSTUDIO_AI_MODEL=gemini-2.5-flash`, and `GEMINI_API_KEY`.
Stub/fallback tests do **not** constitute live external integration acceptance.

## Minimum-Necessary Anonymized `MetricSnapshot`
Outbound payload sent to the AI provider adapter contains **only**:
- `snapshot_id`, `period` (`date`, `timezone`), `currency` (`IDR`), `policy_version`, `tax_status`, `cost_status`
- `metrics` (`revenue_idr`, `cogs_idr`, `cogs_status`, `gross_profit_idr`, `gross_profit_status`, `cash_in_idr`, `cash_out_idr`, `net_cash_flow_idr`, `ending_inventory_value_idr`, `sales_count`, `purchases_count`)
- `source_ids` (opaque transaction/movement IDs)

**Never sent**: `workspace_id`, `workspace.name`, `actor_id`, member details, PII, or secrets.
