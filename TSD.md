# Global Technical Specification
Status PROPOSED. Tidak mengunci dependency atau version tanpa spike dan approval.

## Architecture decision candidate
Next.js/React/TypeScript frontend di Vercel; FastAPI modular monolith sebagai authoritative API di Tencent Lighthouse 2 vCPU/2 GB; Supabase managed PostgreSQL/Auth/Storage. Alasan: Python ecosystem cocok untuk analytics/AI, managed DB mengurangi beban server, satu backend memudahkan transaksi dan deployment. Alternatif Next.js full-stack mengurangi runtime tetapi memerlukan strategi Python analytics; Laravel cocok bila tim lebih mahir PHP, namun menambah stack jika Python tetap dipakai. Pilih berdasarkan spike, bukan popularitas. Tidak ada benchmark RAM aktual. Jangan self-host LLM besar atau database berat pada server kecil.

## Boundaries
Frontend tidak menghitung authoritative HPP atau memegang service-role secret. Backend memvalidasi auth, workspace membership, permission, input dan transaksi. Database menjaga constraint dan audit. Worker opsional menangani job eksternal; mulai dengan mekanisme durable sederhana, bukan Redis wajib. Object storage menyimpan asset dengan access policy. AI provider dipanggil melalui adapter backend, menerima minimum necessary context. Integrasi marketplace/social melalui adapter terpisah; tidak memalsukan response.

## Data contract candidate
Workspace, Membership, Offering, Capability, InventoryBatch, StockMovement, RecipeVersion, ProductionRun, Sale, SaleLine, Expense, CashMovement, MetricSnapshot, Scenario, Asset, Draft, ChannelConnection, PublishJob, AuditEvent. Semua domain record memiliki workspace_id; identifier opaque; timestamp UTC, display timezone workspace. Rupiah integer pada transaksi, Decimal untuk quantity/unit cost dan intermediate; rounding policy harus disetujui. Tidak memakai binary float untuk uang. Ledger append-only secara logis: correction melalui reversal/adjustment, bukan edit histori tanpa jejak. Unique idempotency key scoped workspace+operation; payload mismatch conflict. Transaction boundary mencakup sale, stock issue dan cost snapshot jika penjualan mengonsumsi stok. Jangan mengurangi stok dua kali pada production dan sale.

## API convention candidate
Prefix /v1/workspaces/{workspace_id}; JSON; explicit currency IDR; quantity decimal string; error envelope code, message, field_errors, request_id. 401 unauthenticated, 403 forbidden, 404 not found (hindari tenant leakage), 409 conflict, 422 validation, 429 rate limit, 503 dependency unavailable. Pagination cursor untuk ledger; filter periode dengan timezone eksplisit. Semua endpoint dalam product TSD adalah rancangan, bukan API yang sudah tersedia.

## Security dan reliability
Server memverifikasi token issuer/audience/expiry sesuai provider; membership dan role tidak dipercaya dari body. RLS defense in depth; test lintas tenant wajib. OAuth token encrypted at rest dan tidak dikirim ke browser/log. External request timeout, bounded retry dengan jitter, circuit/queue policy bila diperlukan. Unknown outcome tidak otomatis diulang jika provider tidak mendukung idempotency. Backup dan restore drill sebelum migration destructive. Log request_id dan event metadata, redact PII/secret. SLO, retention dan budget masih OPEN; ukur latency dan memory pada deployment aktual.

## Engineering topology
Monorepo kandidat apps/web, services/backend, packages/design-system, infrastructure, tests, docs, tooling/ai-teammate. Domain modules memiliki service/repository boundary, bukan microservices. Migrations versioned; CI lint/typecheck/unit/integration/build; staging smoke sebelum production. Test command aktual harus ditemukan dari repo, jangan mengarang hasil.
