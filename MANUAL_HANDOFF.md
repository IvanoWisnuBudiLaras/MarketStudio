# MANUAL DEVELOPMENT HANDOFF · MARKETSTUDIO

**Document Version:** 1.1.0 (V3 P0–P1, Issue #81)
**Authority:** Product Owner Directive (Section 28)  
**Primary Target:** Human Developer Onboarding & Continuous Development  
**Language:** Bahasa Indonesia dengan English technical terminology  

---

## V3 P0–P1 · Pencatatan dari skema kosong

`web/app/page.tsx` menyediakan Business Studio. Browser mengakses `web/app/api/[...route]/route.ts` melalui origin yang sama. Route handler meneruskan endpoint yang diizinkan ke FastAPI di loopback. `app/v3.py` menerbitkan OpenAPI dan meneruskan operasi ke `BaselineService`, adapter SQLite, dan skema existing.

Jalankan dari root repo dengan Python 3.11+, uv, dan Node 22+. Siapkan direktori lokal baru dan berkas identitas privat mode 0600. Isi JSON dengan pemetaan ID principal ke kode akses unik hasil generator acak, minimal 24 karakter. Hanya berkas konfigurasi lokal ini yang menyimpan kode akses. Gunakan nama berkas SQLite baru untuk perjalanan clean-state.

```sh
uv sync --locked --extra v3
npm --prefix web ci
NEXT_TELEMETRY_DISABLED=1 npm --prefix web run build
MARKETSTUDIO_ENV=development MARKETSTUDIO_V3_SQLITE=/path/private/business.sqlite3 \
  MARKETSTUDIO_V3_IDENTITIES=/path/private/identities.json \
  uv run --locked --extra v3 uvicorn app.v3:app --host 127.0.0.1 --port 8101
```

Di terminal kedua, jalankan `MARKETSTUDIO_ENV=development MARKETSTUDIO_V3_API_PORT=8101 npm --prefix web start -- --hostname 127.0.0.1 --port 3101`. Buka `http://127.0.0.1:3101`, masuk memakai identitas privat, buat profil usaha, lalu tambah produk dan catat transaksi. API menjalankan inisialisasi skema saat startup. OpenAPI tersedia di `http://127.0.0.1:8101/openapi.json`. Simpan path SQLite agar data tetap tersedia setelah restart.

Komponen `Panel` menggunakan Astryx Card 0.7.17 (MIT) dan stylesheet distribusinya, dengan token MarketStudio di `web/app/style.css`. Tambahkan halaman melalui App Router dan perluas allowlist proxy bersamaan dengan endpoint FastAPI. Gunakan envelope error existing serta `Idempotency-Key` pada write.

Perintah verifikasi:

```sh
npm --prefix web run typecheck
uv run --locked --extra v3 python -W error::ResourceWarning -m unittest discover -s tests
cd web
npx playwright install chromium
npx playwright test
```

Playwright membuat SQLite sementara, file identitas acak privat, dan port loopback sendiri. Dataset bisnis berasal dari form UI. Skenario menguji nilai laporan, kegagalan atomik, submit ganda, respons sukses yang hilang, restart API, relogin dan batas akses tenant. Screenshot tersimpan pada `web/test-results/`. Untuk Chromium lokal, atur `MARKETSTUDIO_TEST_CHROMIUM=/path/to/chromium`.

Rollback lokal memakai commit `2966d968852b1079e688e3596a51bea21b6f944b` di checkout terpisah dan perintah baseline di bawah. Simpan file SQLite V3 sebagai artefak, dan biarkan Docker preview baseline berjalan dengan penyimpanan aslinya. Batch ini menggunakan skema existing. Mode produksi gagal tertutup sampai Supabase Auth tersedia. Integrasi Supabase/PG17 dan rilis menunggu environment terisolasi atau izin deploy. Setelah slice diterima, tugas berikutnya adalah membuktikan satu worksheet Univer editable dengan persistensi dan sumber data laporan yang otoritatif.

## 1. Cara Menjalankan Aplikasi

MarketStudio dirancang sebagai runnable baseline modular monolith tanpa dependensi eksternal wajib untuk eksekusi lokal standar.

### 1.1 Menjalankan Server Pengembangan Lokal (SQLite)
```sh
# Menggunakan environment default (SQLite file di data/marketstudio.sqlite3)
python3 -m app.server --port 8000

# Atau menggunakan perintah instan python
python3 -c 'from app.server import create_server; create_server(port=8000, db_path="data/marketstudio.sqlite3", backend="sqlite").serve_forever()'
```
Buka browser pada: `http://127.0.0.1:8000/`

### 1.2 Menjalankan dengan PostgreSQL 17 Lokal (Opsional)
```sh
export MARKETSTUDIO_DATABASE_URL="postgresql://marketstudio:marketstudio@127.0.0.1:5432/marketstudio"
python3 -m app.server --port 8000 --backend postgres
```

---

## 2. Current Architecture

MarketStudio mengadopsi pola **Modular Monolith** dengan batasan domain yang jelas dan terisolasi:

```
┌─────────────────────────────────────────────────────────────┐
│                 Shared Application Shell                    │
│   (Collapsible Navy Sidebar 240px/64px + Topbar 60px)       │
├─────────────┬─────────────┬─────────────┬───────────────────┤
│  Business   │Intelligence │ Spreadsheet │ Creative / Comm.  │
│   Studio    │   Studio    │   Studio    │   / Social        │
├─────────────┴─────────────┴─────────────┴───────────────────┤
│            Service Layer & Domain Invariants                │
│   (Financial Ledger, Costing WA, Role Auth, Idempotency)    │
├─────────────────────────────────────────────────────────────┤
│         Database Adapter (SQLite / PostgreSQL 17)           │
└─────────────────────────────────────────────────────────────┘
```

- **Domain Boundaries:**
  - `app/domain.py`: Entitas murni domain, aturan bisnis finansial, validasi nominal, penentuan status HPP, otorisasi peran (Owner/Operator/Viewer), dan isolasi tenant.
  - `app/service.py`: Service layer orchestrator (`BaselineService`), manajemen sesi, transaksi atomik, audit log, dan mutasi persediaan.
  - `app/db.py`: Abstraksi dual-engine database (SQLite untuk pengujian cepat/lokal, PostgreSQL 17 dengan RLS dan connection pool).
  - `app/catalog.py`: Manajemen katalog publik dan snapshot penawaran.
  - `app/creative.py`, `app/ai_copy.py`, `app/ai_image.py`, `app/ai_review.py`: Layanan modul Creative dan Intelligence dengan pola fallback deterministik aman.
  - `app/server.py`: Standard library HTTP server (`ThreadingHTTPServer`) melayani REST API `/v1/` dan SPA `/`.

---

## 3. Frontend Entry Points

- **Single Page Application:** `app/web/index.html`
  - Seluruh antarmuka web berada pada satu file HTML terpadu (`app/web/index.html`) bebas dependensi bundle eksternal yang rumit (zero npm build step needed for core app).
  - Menggunakan CSS semantic variables, native SVG symbols, dan Vanilla JavaScript berbasis DOM manipulation tanpa `innerHTML` (anti-XSS).
- **Branding Assets:**
  - `/brand/lockup.png` -> `assets/branding/marketstudio-lockup.png` (Logo kucing resmi + wordmark)
  - `/brand/mark.png` -> `assets/branding/marketstudio-mark.png` (Logo kucing resmi kotak rounded)
  - `/brand/logo.png` -> `assets/branding/logo-reference.png` (Aset referensi utama)

---

## 4. Backend Entry Points

- **CLI Server Runner:** `app/server.py` (`python3 -m app.server`)
- **Library Server Factory:** `app.server.create_server(port, db_path, backend)`
- **Core Domain Service:** `app.service.BaselineService`
- **Database Initializer & Migrations:** `app.migrations.run_migrations(conn)` dan `app.db.init_db()`
- **Backup & Restore Tool:** `scripts/backup_restore.py`
- **Health Check & Smoke Tool:** `scripts/smoke_check.py`

---

## 5. Database Setup

### 5.1 SQLite (Default)
Database SQLite dibuat dan dimigrasi secara otomatis saat server dimulai jika file belum ada.
- Default path: `data/marketstudio.sqlite3`
- Migrasi: Dijalankan otomatis melalui `app/migrations.py`.

### 5.2 PostgreSQL 17
1. Buat database dan role:
   ```sql
   CREATE USER marketstudio WITH PASSWORD 'marketstudio';
   CREATE DATABASE marketstudio OWNER marketstudio;
   ```
2. Jalankan migrasi:
   ```sh
   export MARKETSTUDIO_DATABASE_URL="postgresql://marketstudio:marketstudio@127.0.0.1:5432/marketstudio"
   python3 -c "from app.db import init_db; init_db()"
   ```

---

## 6. Environment Variables (Tanpa Secret)

Konfigurasi dibaca melalui environment variables dengan nilai default aman:

| Variable | Default | Deskripsi |
|---|---|---|
| `PORT` | `8000` | Port listen HTTP server |
| `MARKETSTUDIO_BACKEND` | `sqlite` | Backend database: `sqlite` atau `postgres` |
| `MARKETSTUDIO_DB_PATH` | `data/marketstudio.sqlite3` | Path file SQLite lokal |
| `MARKETSTUDIO_DATABASE_URL` | None | Connection string PostgreSQL (DSN) |
| `AI_PROVIDER` | `mock` / `stub` | Provider AI: `stub`, `openai`, `gemini` |
| `AI_API_KEY` | None | API key provider (jangan di-commit ke git) |
| `AI_TIMEOUT_SECONDS` | `10` | Timeout pemanggilan outbound model AI |

---

## 7. Existing API Contracts

Semua API di bawah prefix `/v1/workspaces/{workspace_id}/`:

- **Sesi & Autentikasi:**
  - `POST /v1/sessions`: Pembuatan sesi aktor (`actor_id`, `passcode`)
- **Workspace:**
  - `GET /v1/workspaces`: Daftar workspace anggota
  - `POST /v1/workspaces`: Buat workspace baru
  - `POST /v1/workspaces/demo`: Buat atau reset workspace demo Warung Bakso & Sembako (idempoten)
- **Katalog & Offering:**
  - `GET /v1/workspaces/{ws_id}/offerings`: Ambil daftar barang/jasa/hybrid
  - `POST /v1/workspaces/{ws_id}/offerings`: Tambah offering baru
  - `POST /v1/workspaces/{ws_id}/offerings/{id}/archive`: Arsipkan offering
  - `POST /v1/workspaces/{ws_id}/offerings/{id}/pricing`: Rekam keputusan harga jual
- **Operasional Transaksi:**
  - `POST /v1/workspaces/{ws_id}/purchases`: Catat pembelian stok (idempotency key aman)
  - `POST /v1/workspaces/{ws_id}/sales`: Catat transaksi penjualan multi-item (idempotency key aman)
- **Laporan & Review:**
  - `GET /v1/workspaces/{ws_id}/reports/daily?date=YYYY-MM-DD`: Laporan kas, HPP, laba kotor, dan stok akhir
  - `GET /v1/workspaces/{ws_id}/reports/daily/ai-review`: Jalankan AI Business Review analitikal
- **Simulasi & Benchmark:**
  - `POST /v1/workspaces/{ws_id}/simulations`: Hitung simulasi margin dan break-even
  - `GET /v1/workspaces/{ws_id}/price-benchmarks/snapshots`: Ambil data benchmark pasar Bapanas/sintetis
- **Creative & Katalog Publik:**
  - `POST /v1/workspaces/{ws_id}/creative-drafts/sample`: Buat contoh draft poster
  - `POST /v1/workspaces/{ws_id}/creative-drafts/{id}/export`: Ekspor aset poster SVG/PNG
  - `GET /katalog/{public_slug}`: Halaman katalog publik mandiri

---

## 8. AI Provider Configuration

Sistem AI di MarketStudio mengusung prinsip **AI As Accelerative Engine, Not Authority**:
- Modul AI tidak pernah mengubah ledger keuangan atau database secara mandiri tanpa konfirmasi user.
- Menggunakan pola fallback deterministik: bila provider timeout, kuota habis, atau unconfigured, sistem menyajikan interpretasi berbasis fakta data lokal tanpa error fatal.
- Outbound payload minimizer: data sensitif pelanggan tidak dikirimkan ke provider AI luar.

---

## 9. Component Architecture & Design System

- **Shared Application Shell:**
  - Sidebar collapsible: Lebar normal `240px`, lebar ringkas icon rail `64px` (toggle via `#sidebarCollapseBtn`).
  - Warna Sidebar: Enterprise Navy `#142B52`, Border `#1E3A66`.
  - Navigasi 6 studio: Business, Intelligence, Spreadsheet, Creative, Commerce, Social + Profil & Pengaturan.
  - Topbar: Tinggi `60px` (`56–64px`), memuat judul konteks, status workspace, dan tombol aksi utama.
- **Hierarki Business Studio Overview:**
  1. Header + Date Picker laporan
  2. Hero Greeting Banner + Tombol langsung AI Business Review
  3. 4 KPI Utama Grid (Arus kas bersih, Laba kotor, Omzet, Nilai persediaan)
  4. Ringkasan Arus Kas Masuk/Keluar + Catatan edukasi laba vs kas
  5. Ringkasan Persediaan & Peringatan Stok Kritis
  6. Pusat Rekomendasi & AI Review Spotlight
  7. Daftar Transaksi Terbaru
  8. Rincian Laporan & Jejak Audit (Disclosure)

---

## 10. Design Tokens

| Token | Nilai | Penggunaan |
|---|---|---|
| `--accent` | `#2563EB` | Primary action button, active nav badge, link focus |
| `--accent-hover`| `#1D4ED8` | Hover state tombol utama |
| `--brand-navy` | `#142B52` | Sidebar latar belakang, heading level 1 & 2 |
| `--canvas` | `#F7F8FA` | Latar belakang kanvas aplikasi |
| `--surface` | `#FFFFFF` | Latar belakang kartu, topbar, modal dialog |
| `--surface-elevated`| `#EFF6FF` | Hero banner, kartu terpilih, callout info |
| `--border` | `#E2E6EC` | Garis pembatas kartu, tabel, dan form input |
| `--text` | `#172033` | Warna teks utama body |
| `--muted` | `#526077` | Warna teks sekunder / keterangan |

---

## 11. Cara Menambah Halaman Baru

1. **Tambahkan Navigasi:**
   Buka `app/web/index.html`, tambahkan elemen link di `<nav>` sidebar:
   ```html
   <a href="#studio-baru" class="nav-link" data-route="studio-baru" title="Studio Baru">
     <span class="nav-link-main">
       <svg class="ui-icon"><use href="#icon-baru"/></svg>
       <span class="nav-link-text">
         <span>Studio Baru</span>
         <span class="nav-link-sub">Keterangan Singkat</span>
       </span>
     </span>
   </a>
   ```
2. **Tambahkan View Container:**
   Di dalam `<main id="main-content">`, tambahkan:
   ```html
   <section id="view-studio-baru" class="view-section hidden" aria-label="Studio Baru">
     <!-- Konten Studio Baru -->
   </section>
   ```
3. **Daftarkan Route di JavaScript:**
   Di dalam blok `<script>` `app/web/index.html`:
   - Tambahkan key pada `SCREEN_TITLES`:
     ```javascript
     const SCREEN_TITLES = {
       ...
       "studio-baru": "Studio Baru"
     };
     ```
   - Tambahkan pemetaan pada `applyRoute`:
     ```javascript
     const studioNames = {
       ...
       "studio-baru": "Studio Baru"
     };
     ```

---

## 12. Cara Menambah Fitur Backend Baru

1. **Domain Layer:** Definisikan tipe dan fungsi murni di `app/domain.py`.
2. **Database Layer:** Tambahkan query SQL di `app/service.py` dan jika ada tabel baru buat file migrasi di `migrations/` dan `app/migrations.py`.
3. **HTTP Server Handler:** Tambahkan routing regex dan handler method di `app/server.py`.
4. **Unit Test:** Buat test case di `tests/test_<fitur>.py` memastikan isolasi tenant dan invariansi state.

---

## 13. Cara Menjalankan Tests

```sh
# Menjalankan seluruh test suite unit & integrasi (123+ test cases)
python3 -W error::ResourceWarning -m unittest discover -s tests -v

# Menjalankan pemeriksaan format repository, token, dan skema dokumen
python3 scripts/check_repository.py

# Menjalankan verifikasi alur core Playwright (contoh 1440px desktop)
node scripts/check_core_workflows.cjs http://127.0.0.1:8000 1440 /tmp/evidence

# Menjalankan penangkapan bukti visual lengkap P1–P2
python3 -c '
import subprocess
for w in [1440, 1280, 768, 390]:
    subprocess.run(["node", "scripts/capture_p1_p2_evidence.cjs", "http://127.0.0.1:8000", str(w), "docs/design-system/evidence/p1-p2"])
'
```

---

## 14. Deployment Instructions

### 14.1 Docker Container
1. Build image:
   ```sh
   docker build -t marketstudio:latest .
   ```
2. Jalankan container:
   ```sh
   docker run -d --name marketstudio -p 8000:8000 -v marketstudio_data:/app/data marketstudio:latest
   ```

### 14.2 Production Server (Tencent Lighthouse / VPS Linux)
- Spesifikasi target: 2 vCPU, 2 GB RAM, Arch Linux / Ubuntu 24.04.
- Reverse Proxy: Nginx atau Caddy mengarahkan traffic HTTPS port 443 ke `127.0.0.1:8000`.
- Service Manager: Systemd unit `marketstudio.service`.

---

## 15. Known Limitations

1. **Live External Marketplaces:** Integrasi API langsung ke TikTok Shop / Shopee / Tokopedia masih berstatus Roadmap menunggu perizinan resmi API developer keys.
2. **Spreadsheet Engine:** Integrasi library Univer direncanakan untuk tahap P3; saat ini modul Analisis & Harga menggunakan simulator berbasis formula deterministik.
3. **AI Provider Outbound:** Pemanggilan Gemini Neon / OpenAI live memerlukan API key resmi pada environment production; default lokal menggunakan stub/fallback cerdas berbasis data riil.

---

## 16. Remaining Prioritized Tasks

Mengikuti Product Alignment Matrix:
- **P3 — Intelligence & Spreadsheet:** Finalisasi laporan AI Review, benchmark harga pasar Bapanas terintegrasi, simulasi margin/diskon.
- **P4 — Creative, Commerce & Social:** Penyempurnaan kanvas poster, katalog publik terbagi (shareable link), composer konten media sosial.
- **P5 — Cross-Studio Polish:** Pengalaman terpadu siklus bisnis UMKM (Catat -> Analisis -> Rencana Harga -> Buat Materi -> Bagikan -> Evaluasi).
- **P6 — Competition & Final Handoff:** Gladi bersih demonstrasi Techcomfest 2027 dan audit kepatuhan final.

---

## 17. Current Commit & Checkpoint

- **Branch Aktif:** `IvanoWisnuBudiLaras/shared-shell-76`
- **Tujuan Merge:** `origin/main` (Issue #76 Closes #76)
- **Base Commit:** `88009ad86650b751c3347c15788e3ec0a659110d`
- **Pekerjaan Terkini:** P1 Shared Shell (Navy Collapsible Sidebar 240px/64px + Topbar) dan P2 Business Studio Overview (4 KPIs, Cash Summary, Critical Stock, Recent Transactions, AI Review Spotlight).
