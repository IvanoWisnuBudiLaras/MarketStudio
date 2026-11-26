# Global TSD — proposal
Monorepo: apps/web (Next.js), services/backend (FastAPI), packages/design-system, infrastructure, tests. Satu PostgreSQL managed via Supabase; Auth dan Storage kandidat. Frontend Vercel, backend Tencent Lighthouse 2 vCPU/2 GB. Caddy/Nginx + Docker Compose; mulai satu web process, worker hanya jika perlu; ukur RAM/latency, jangan mengasumsikan kapasitas. Redis opsional. No Kubernetes/microservices/local LLM.

Domain: workspace, membership, offering, variant, customer, transaction, ledger/financial records, inventory movement, service order, booking, asset, campaign, publication job, audit event. Ini model konseptual bukan schema final. Offering bisa barang/jasa/digital/rental/bundle; subscription lebih tepat dimodelkan juga sebagai revenue arrangement. Pisahkan atribut domain dan hindari satu tabel serba guna.

API: typed contracts/OpenAPI, Pydantic, SQLAlchemy kandidat; validasi tenant di setiap akses, idempotency untuk transaksi dan publish, explicit rounding, migrations dan backup/restore test. Supabase RLS jika akses langsung; service role hanya server. Jangan mengandalkan UI untuk authorization.

AI: satu provider abstraction tipis, structured context, tool allowlist, deterministic calculations, human approval untuk side effects. Forecast sederhana jika data cukup, tampilkan error/ketidakpastian. No vector DB/agent framework sampai kebutuhan terbukti.

Publishing: canonical draft → channel adaptation → validate → approval → queue → adapter → status/retry/audit. OAuth token server-side, scope minimal, redaction, retry dengan backoff dan idempotency. Sandbox/mock diberi label. Tidak ada kredensial di repo.

Verifikasi kompatibilitas React/Astryx/Univer, license, bundle size dan API aktual sebelum implementasi. TSD produk dapat berkembang dengan ADR; tidak boleh mengubah business requirements diam-diam.
