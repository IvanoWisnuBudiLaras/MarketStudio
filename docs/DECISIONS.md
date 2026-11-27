# Decision log
Status: APPROVED = persetujuan eksplisit; DIRECTION = preferensi/visi; PROPOSED = belum dikunci; OPEN = perlu keputusan.

| ID | Status | Keputusan |
|---|---|---|
| D01 | APPROVED | Nama MarketStudio; enam produk dalam satu bisnis/GOALS |
| D02 | APPROVED | Visi C+D: Business OS dan Entrepreneurship Platform |
| D03 | APPROVED | UMKM lintas industri termasuk jasa; pertahankan penelitian Bakso |
| D04 | APPROVED | A+B, accent #2563EB, navy/putih/coffee dark, customizable; logo referensi terakhir |
| D05 | APPROVED | Bahasa Indonesia utama, istilah teknis Inggris |
| D06 | DIRECTION | Gemini untuk development; Codex untuk konteks, skills, harness, MCP |
| D07 | DIRECTION | One-click commerce/social lintas kanal, Astryx dan Univer |
| D08 | PROPOSED | Next.js + FastAPI modular monolith + Supabase, Vercel/Tencent |
| D09 | PROPOSED | Business DNA, adaptive workspace, Offering, capability model |
| D10 | PROPOSED | P0 Business+Intelligence+Core; P1 Spreadsheet+Creative; P2 adapters |
| D11 | PROPOSED | Satu AI lintas studio; human-in-the-loop; freemium; PWA; CRM; offline bertahap |
| D12 | OPEN | Scope lomba final, target segmen pertama, model monetisasi, API approval, budget, model ID, MCP servers |
| D13 | OPEN | Klarifikasi unsur promosi dan eligibility karya lama kepada panitia |

Tambahkan tanggal, alasan, alternatif, dampak, status, persetujuan Product Owner untuk keputusan baru. Jangan mengubah status hanya karena agent menyukai suatu solusi.

| ID | Status | Keputusan |
|---|---|---|
| D14 | DIRECTION | Tiga teammate Atlas, Forge, Nexus; spesialisasi melalui skills, bukan 15 bot |
| D15 | APPROVED | Dokumentasi lebih informatif dan panjang, eksekusi tidak ambigu |
| D16 | PROPOSED | Orca-first; manual handoff sebagai fallback; maksimal 2–3 sesi aktif awal |
| D17 | OPEN | Model ID, reasoning effort, native Orca config, MCP permissions dan budget aktual |
| D18 | PROPOSED | Kontrak teknis dan acceptance criteria V2 sebagai candidate baseline, belum approval implementasi |
| D19 | APPROVED | (2026-11-27) PO mengotorisasi implementasi Issue #5 dan milestone slice #12/#10/#11/#32/#36/#38/#39/#20 tanpa menunggu approval lama; data sintetis lokal, tanpa merge/deploy publik |
| D20 | APPROVED | (2026-11-27) Domain scope: `goods` (barang), `service` (jasa), dan `hybrid`; Weighted Average (WA) khusus untuk fixture; jasa tidak memerlukan stock movement; pajak berstatus `not_assessed`/`unknown` dengan alasan dan tanpa `tax_amount` (bukan default `tax=0`); wajib tenant isolation, idempotency, atomicity, dan audit |
| D21 | APPROVED | (2026-11-27) Stack baseline #5: Python 3 stdlib modular monolith (`http.server` + `sqlite3` + `unittest`) dengan single browser entry point (`GET /`) dan local SQLite storage; siap migrasi bertahap ke FastAPI/PostgreSQL |

Catatan: D14 mencerminkan koreksi owner atas jumlah bot; nama dan role berasal dari usulan yang kemudian dipakai dalam diskusi. Tidak ada bukti persetujuan untuk setiap detail teknis V2. D15 tidak mengizinkan AI mengubah keputusan bisnis tanpa approval. Dokumen history/v1 hanya untuk audit.
