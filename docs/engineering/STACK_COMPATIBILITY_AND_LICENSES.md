# Kompatibilitas Stack, Lisensi Resmi & Hasil Benchmark Spike MVP

Dokumen ini memverifikasi kompatibilitas opsi stack kandidat alur #1, lisensi dan versi resmi, serta mendokumentasikan hasil spike minimum terukur yang dapat diulang (Issue #29, Refs #29 / Closes #29).

---

## 1. Ringkasan Eksekutif & Status Keputusan

Berdasarkan evaluasi terhadap [TSD.md](../../TSD.md), [docs/DECISIONS.md](../DECISIONS.md), dan implementasi runnable baseline (Issue #5):

1. **Baseline Terpilih (D21 - APPROVED):**
   MarketStudio mengadopsi modular monolith berbasis **Python 3 standard library** (`http.server`, `sqlite3`, `unittest`, `dataclasses`, `json`, `decimal`) dengan antarmuka web browser tunggal (`GET /` -> `app/web/index.html`) dan penyimpanan persisten lokal SQLite (`data/marketstudio.db`).
   - **Zero External Runtime Dependency:** Clone bersih langsung dapat dijalankan tanpa `pip install` atau kompilasi node_modules.
   - **In-process Initialization Cepat:** Inisialisasi server dan SQLite dalam proses selesai dalam **< 6 ms** (terukur rata-rata ~3.9–5.2 ms).
   - **Footprint Memori Sangat Hemat:** Idle RSS **~30.4 MB**, loaded RSS **~33.9 MB**, sangat optimal untuk VPS spesifikasi minimal (2 vCPU / 2 GB RAM) maupun lingkungan lokal offline.
   - **Dual-Backend Ready:** Jalur migrasi opsional PostgreSQL 17 / Supabase telah tersedia via database adapter (`POSTGRES_SUPABASE.md` / Issue #54) tanpa merusak profil default SQLite.

2. **Hubungan dengan D08 (PROPOSED):**
   D08 mengusulkan *Next.js + FastAPI + Supabase*. Spike ini menegaskan bahwa untuk validasi alur #1 (profil usaha, katalog barang/jasa, pencatatan kulakan, transaksi penjualan, dan laporan harian), pemisahan frontend Next.js dan backend FastAPI menghasilkan overhead deployment, latensi jaringan antar-layanan, dan kompleksitas dependency yang belum diperlukan (YAGNI). D08 disimpan sebagai arah evolusi jangka panjang (khususnya untuk Studio Creative atau portal katalog publik berskala besar), bukan prasyarat MVP.

---

## 2. Analisis & Evaluasi Komparatif Opsi Kandidat

Tabel berikut membandingkan empat opsi arsitektur kandidat yang dipertimbangkan untuk alur #1.

*Catatan Metodologis:* Angka metrik untuk **Opsi A (Baseline D21)** merupakan hasil ukur empiris langsung di lingkungan pengujian lokal repositori ini. Angka untuk **Opsi B (FastAPI), Opsi C (Next.js + FastAPI), dan Opsi D (Supabase)** merupakan estimasi konseptual/referensi standar industri berdasarkan karakteristik tipikal runtime masing-masing dan **belum diuji secara empiris** pada repositori ini.

| Dimensi Evaluasi | Opsi A: Python 3 Stdlib Monolith (Baseline D21 - Terukur Empiris) | Opsi B: FastAPI Modular Monolith (Estimasi Konseptual) | Opsi C: Next.js + FastAPI Decoupled (D08 - Estimasi Konseptual) | Opsi D: Supabase Managed Backend (Estimasi Konseptual) |
|---|---|---|---|---|
| **Komponen Utama** | Python 3.11+, `http.server`, `sqlite3`, Vanilla JS/HTML | Python 3.11+, FastAPI, Pydantic v2, Starlette, Uvicorn, SQLite/PG | Next.js (React 19, TS) di Vercel + FastAPI di VPS | Supabase PostgreSQL, Supabase Auth (GoTrue), Supabase Storage |
| **Runtime Dependency** | **0 package** (100% Python stdlib) | ~15–20 package via pip | Node.js ecosystem (npm) + Python pip | Client libraries (JS/Python) + Managed cloud service |
| **In-process Init / Startup** | **~3.9–5.2 ms** (in-process server & SQLite init) | ~120–250 ms (estimasi ASGI boot) | Backend ~150 ms; Frontend Node ~500–1200 ms | Bergantung koneksi jaringan cloud (cold pool ~500–2000 ms) |
| **Memory RSS (Idle / Loaded)** | **~30.4 MB / ~34.0 MB** (terukur) | ~55 MB / ~80 MB (estimasi) | Frontend ~120 MB + Backend ~70 MB (estimasi) | Client ~35 MB (beban database di-offload ke cloud) |
| **Latensi Alur #1 (Lokal)** | **~20–21 ms total** (7 request, terukur) | ~25–35 ms total (estimasi) | ~60–120 ms (overhead cross-origin/network hop) | ~150–350 ms (latensi internet WAN ke Supabase) |
| **Kesiapan Offline Total** | **Sangat Baik** (100% lokal tanpa jaringan) | **Sangat Baik** (100% lokal) | Buruk (tergantung koneksi edge Vercel) | Tidak bisa offline tanpa local Supabase CLI Docker |
| **Setup & Build Tooling** | Langsung jalan (`python3 -m app.server`) | Memerlukan `pip install` (virtualenv) | Dual build: npm run build + pip install; CORS setup | Konfigurasi project Supabase, URL, API keys, dan network access |
| **Isolasi Tenant & Keamanan** | App-level tenant isolation + PBKDF2 passcodes | App-level via dependency injection | Token passing via edge + app-level authorization | Row Level Security (RLS) di level engine PostgreSQL |
| **Rekomendasi Status** | **APPROVED (Baseline Alur #1)** | **CANDIDATE UPGRADE (Fase Lanjut)** | **DEFERRED (Non-MVP)** | **OPTIONAL ADAPTER (Issue #54)** |

### Evaluasi Rinci Pro & Kontra

#### Opsi A: Python 3 Standard Library Modular Monolith (Baseline D21)
- **Kelebihan:**
  - Nol kerentanan rantai pasok eksternal (*supply-chain security risk* = 0).
  - Portabilitas maksimal antar sistem operasi (Linux, macOS, Windows) tanpa compiler C/Rust eksternal.
  - Setup CI/CD dan pengujian sangat cepat (seluruh test suite berjalan dalam ~40 detik).
  - Konsumsi memori minimal memungkinkan ratusan instance pengujian atau proses berdampingan di server murah.
- **Kekurangan:**
  - Routing HTTP dilakukan via pencocokan regex manual (`app/server.py`).
  - Serialisasi dan validasi data ditulis manual pada layer domain (`app/domain.py`) tanpa generator schema otomatis.
  - Model eksekusi request menggunakan `ThreadingHTTPServer` (thread-per-connection), bukan asynchronous I/O event loop.

#### Opsi B: FastAPI Modular Monolith
- **Kelebihan:**
  - Validasi schema request/response otomatis menggunakan Pydantic v2.
  - Dokumentasi interaktif OpenAPI/Swagger out-of-the-box di endpoint `/docs`.
  - Dukungan native `async`/`await` untuk penanganan I/O bound (panggilan API model AI eksternal).
- **Kekurangan:**
  - Menambah dependensi pihak ketiga (~15 package) yang harus diaudit dan dipelihara.
  - Ukuran image/container dan kebutuhan memori RAM meningkat (~2× lipat Opsi A).

#### Opsi C: Next.js + FastAPI Decoupled (D08)
- **Kelebihan:**
  - Ekosistem antarmuka React modern dengan rendering server-side (SSR) untuk katalog publik SEO.
  - Pemisahan siklus rilis dan tanggung jawab tim antara frontend engineer dan backend engineer.
- **Kekurangan:**
  - Membutuhkan dua runtime berbeda (Node.js dan Python) serta manajemen build ganda.
  - Memperkenalkan latensi jaringan tambahan dan risiko CORS / token leakage antara browser, Vercel edge, dan VPS.
  - Terlalu kompleks untuk tahap validasi ide alur #1 dengan satu atau dua pengembang.

#### Opsi D: Supabase Managed Backend
- **Kelebihan:**
  - Pengelolaan database PostgreSQL, connection pooler (Supavisor), dan backup terotomatisasi di cloud.
  - RLS (*Row Level Security*) memberikan pertahanan berlapis (*defense-in-depth*) untuk isolasi tenant.
- **Kekurangan:**
  - Membutuhkan koneksi internet aktif; tidak mendukung operasi UMKM di daerah dengan koneksi tidak stabil tanpa Docker lokal yang berat.
  - Risiko vendor lock-in atau biaya tak terduga bila kuota melampaui free tier.

---

## 3. Verifikasi Versi & Lisensi Komponen Stack

Seluruh komponen stack yang diuji dan dipertimbangkan telah diverifikasi lisensi resminya berdasarkan metadata proyek upstream:

| Komponen Stack | Versi Teruji / Minimum | Lisensi Resmi Upstream | Tautan Dokumentasi Resmi | Tautan Lisensi Resmi | Status Kepatuhan & Analisis Lisensi |
|---|---|---|---|---|---|
| **Python** | 3.11+ (teruji pada 3.12 & 3.14) | PSF License v2 | [docs.python.org/3](https://docs.python.org/3/) | [python.org/psf/license](https://docs.python.org/3/license.html) | **Permissive / Open Source** (Bebas komersial & kompetisi) |
| **SQLite** | 3.39+ (bawaan Python stdlib) | Public Domain (Blessing) | [sqlite.org/docs](https://www.sqlite.org/docs.html) | [sqlite.org/copyright](https://www.sqlite.org/copyright.html) | **Public Domain** (100% bebas copyleft & komersial) |
| **psycopg 3** (opsional) | >= 3.2, < 4.0 (`pyproject.toml`) | **LGPL-3.0-only** | [psycopg.org/psycopg3/docs](https://psycopg.org/psycopg3/docs/) | [psycopg/pyproject.toml](https://github.com/psycopg/psycopg/blob/master/psycopg/pyproject.toml) | **Copyleft Terbatas (Weak Copyleft)** — Wajib relinking capability; opsional di luar baseline |
| **FastAPI** (kandidat) | >= 0.110.0 | MIT License | [fastapi.tiangolo.com](https://fastapi.tiangolo.com/) | [github.com/fastapi/fastapi/LICENSE](https://github.com/fastapi/fastapi/blob/master/LICENSE) | **Permissive** (Bebas komersial & kompetisi) |
| **Next.js** (kandidat) | >= 14.2 / 15.0 | MIT License | [nextjs.org/docs](https://nextjs.org/docs) | [github.com/vercel/next.js/license.md](https://github.com/vercel/next.js/blob/canary/license.md) | **Permissive** (Bebas komersial & kompetisi) |
| **PostgreSQL** (opsional) | 15+ (teruji pada PG 17) | PostgreSQL License (BSD-like) | [postgresql.org/docs](https://www.postgresql.org/docs/) | [postgresql.org/about/licence](https://www.postgresql.org/about/licence/) | **Permissive** (Bebas komersial & kompetisi) |
| **Supabase Client** (kandidat) | Client v2 / SDK | Apache-2.0 / MIT | [supabase.com/docs](https://supabase.com/docs) | [github.com/supabase/supabase/LICENSE](https://github.com/supabase/supabase/blob/master/LICENSE) | **Permissive** (Standar industri) |

### Analisis Kepatuhan Lisensi & Kewajiban Distribusi

1. **Analisis Lisensi psycopg 3 (LGPL-3.0-only):**
   - Berdasarkan metadata upstream resmi `psycopg/pyproject.toml`, lisensi `psycopg` adalah **LGPL-3.0-only** (*GNU Lesser General Public License version 3.0 only*).
   - **Bukan Runtime Exception:** Lisensi psycopg tidak memuat *runtime exception* atau klausul pengecualian komersial khusus.
   - **Kewajiban Distribusi LGPL-3.0:**
     * Jika aplikasi didistribusikan dalam bentuk biner terkompilasi / *packaged application* yang menyertakan pustaka psycopg, pengguna akhir harus memiliki hak dan sarana teknis untuk memodifikasi atau mengganti pustaka psycopg tersebut (*relinking / dynamic linking requirement*). Distribusi melalui standar wheel `pip` dan modul Python terpisah memenuhi persyaratan dynamic linking ini.
     * Modifikasi terhadap kode sumber internal psycopg (jika ada) wajib dirilis di bawah LGPL-3.0.
     * Teks lisensi LGPL-3.0 dan GPL-3.0 beserta atribusi hak cipta wajib disertakan dalam distribusi produk yang memuatnya.
   - **Status di MarketStudio:**
     * `psycopg[pool]` berstatus **kandidat adapter opsional** (`[project.optional-dependencies] postgres` pada `pyproject.toml`), dan **sama sekali tidak dimuat** pada runtime baseline stdlib D21 (`dependencies = []`).
     * Distribusi dan penggunaan baseline MVP alur #1 bebas dari kewajiban LGPL-3.0 karena berjalan 100% di atas Python stdlib (`sqlite3`).

2. **Kesesuaian Komersial & Lomba untuk Runtime Baseline:**
   - Seluruh komponen runtime baseline D21 (Python stdlib dan SQLite) menggunakan lisensi PSFL v2 dan Public Domain.
   - Tidak ada ketergantungan terhadap lisensi copyleft kuat (*viral copyleft* seperti GPL-3.0 atau AGPL-3.0), sehingga kode aplikasi berpemilik MarketStudio terlindungi sepenuhnya dan aman untuk komersialisasi UMKM maupun aturan kompetisi inovasi perangkat lunak.

---

## 4. Hasil Ukur Spike Minimum yang Dapat Diulang (Alur #1)

Spike benchmarking dieksekusi secara mandiri menggunakan skrip `scripts/spike_stack_metrics.py`. Skrip ini mengisolasi backend secara ketat ke SQLite lokal (menolak file database yang sudah ada dan mengabaikan environment PostgreSQL eksternal).

### Metodologi Pengujian
- **Alur yang Dieksekusi:**
  1. Booting server HTTP & inisialisasi database SQLite terisolasi.
  2. Pengukuran In-process Server & SQLite Initialization Time serta Idle Memory RSS.
  3. Autentikasi sesi: `POST /v1/sessions` (menerima bearer token).
  4. Pembuatan profil usaha: `POST /v1/workspaces`.
  5. Pembuatan produk barang (*goods*): `POST /v1/workspaces/{id}/offerings`.
  6. Pembuatan produk jasa (*service*): `POST /v1/workspaces/{id}/offerings`.
  7. Pembelian stok kulakan (*purchase*): `POST /v1/workspaces/{id}/purchases`.
  8. Penjualan gabungan barang & jasa (*sale*): `POST /v1/workspaces/{id}/sales`.
  9. Pembuatan laporan harian (*daily report*): `GET /v1/workspaces/{id}/reports/daily`.
  10. Pengukuran Loaded Memory RSS, Peak RSS, dan Ukuran File Database Disk.

*Catatan Definisi Timer:* Pengukuran inisialisasi server melingkupi resolusi konfigurasi database, inisialisasi schema `init_db(auto_migrate=True)`, instansiasi `ThreadingHTTPServer`, dan binding socket port ephemeral setelah modul Python diimpor dan sebelum `serve_forever`. Pengukuran ini merefleksikan **in-process server and SQLite initialization**, bukan full cold boot proses OS (yang membutuhkan waktu tambahan untuk pemuatan interpreter Python dari disk).

### Perintah Eksekusi Spike

```sh
# Menjalankan spike dengan output teks standar (3 iterasi)
python3 scripts/spike_stack_metrics.py

# Menjalankan spike dalam format JSON terstruktur
python3 scripts/spike_stack_metrics.py --json

# Menjalankan dengan file database kustom baru (menolak file existing)
python3 scripts/spike_stack_metrics.py --db-path data/benchmark_new.db --iterations 5
```

### Hasil Ukur Aktual Terverifikasi

Hasil benchmark yang diambil dari lingkungan kerja aktual (Linux 64-bit, Python 3.14 / 3.12, 3 iterasi alur penuh pada isolated fixture):

| Metrik Kuantitatif | Nilai Terukur | Keterangan & Batas Toleransi |
|---|---|---|
| **In-process Init Time** | **~3.9–5.2 ms** | Inisialisasi server, binding socket port ephemeral, dan auto-migrate schema SQLite |
| **Idle Memory RSS** | **~30.4 MB** | Penggunaan RAM proses saat server siap menerima koneksi pertama |
| **Loaded Memory RSS** | **~34.0 MB** | Penggunaan RAM proses setelah menyelesaikan 3 iterasi alur penuh #1 |
| **Peak Memory RSS (HWM)** | **~34.0 MB** | Titik tertinggi alokasi memori (*High Water Mark*) |
| **Database File Size** | **208.0 KB** | Ukuran file SQLite di disk (termasuk 13 tabel, indeks, dan data transaksi) |
| **Total Flow Mean Latency** | **~20.1–20.7 ms** | Total waktu kumulatif mengeksekusi ke-7 langkah alur #1 |

### Rincian Latensi per Endpoint (Alur #1)

| Langkah Alur | HTTP Endpoint | Rata-rata (*Mean*) | Minimum (*Min*) | Maksimum (*Max*) |
|---|---|---|---|---|
| 1. Autentikasi Sesi | `POST /v1/sessions` | **~2.6–2.7 ms** | 1.22 ms | 5.60 ms |
| 2. Buat Profil Usaha | `POST /v1/workspaces` | **~7.6–8.3 ms** | 6.93 ms | 8.52 ms |
| 3. Buat Offering Barang | `POST /v1/workspaces/{id}/offerings` | **~1.6–1.9 ms** | 1.25 ms | 2.11 ms |
| 4. Buat Offering Jasa | `POST /v1/workspaces/{id}/offerings` | **~1.6–1.7 ms** | 1.40 ms | 1.93 ms |
| 5. Kulakan Barang (Stok) | `POST /v1/workspaces/{id}/purchases` | **~1.5–2.0 ms** | 1.38 ms | 2.47 ms |
| 6. Penjualan Barang + Jasa | `POST /v1/workspaces/{id}/sales` | **~1.9–2.0 ms** | 1.33 ms | 2.27 ms |
| 7. Laporan Harian | `GET /v1/workspaces/{id}/reports/daily` | **~2.6–2.7 ms** | 1.54 ms | 4.67 ms |

*Catatan: Seluruh request dieksekusi melalui HTTP loopback (`127.0.0.1`) dengan pembacaan dan parsing JSON lengkap.*

---

## 5. Keputusan yang Dibutuhkan & Keputusan yang Tersisa

### Keputusan yang Ditutup oleh Spike Ini
1. **Keputusan Stack MVP Alur #1 (Konfirmasi D21):**
   Stack Python 3 standard library modular monolith (`http.server` + `sqlite3` + `unittest`) terbukti secara kuantitatif sangat efisien (in-process init < 6 ms, RAM ~34 MB, latensi per request < 9 ms), andal, dan memenuhi 100% kriteria penerimaan fungsional tanpa beban dependensi eksternal.
2. **Kepatuhan Lisensi:**
   Komponen runtime baseline D21 (Python dan SQLite) 100% bebas dari copyleft. Pustaka opsional `psycopg` teridentifikasi berlisensi LGPL-3.0-only tanpa runtime exception dan diisolasi sebagai adapter opsional di luar runtime baseline.
3. **Arsitektur Dual-Storage Berkelanjutan:**
   Strategi database adapter dual-mode (`sqlite` default untuk portabilitas offline/lokal dan `postgres` opsional untuk skalabilitas cloud) berhasil mempertahankan kesederhanaan monolitik tanpa mengorbankan jalur migrasi masa depan.

### Keputusan Teknis yang Masih Tersisa (*Remaining Open Decisions*)
1. **Adopsi UI Framework (Vanilla DOM vs Next.js/React):**
   - Saat ini antarmuka browser menggunakan single-page HTML/CSS/JS native yang disajikan langsung oleh server (`GET /`).
   - *Pertimbangan:* Apakah Studio Creative (desain grafis/poster) dan Studio Spreadsheet (tabel dinamis) tetap menggunakan vanilla JS dengan library terkurasi atau memerlukan adopsi framework frontend modern pada milestone berikutnya.
2. **Hosting Production & Alokasi Anggaran Cloud:**
   - Evaluasi hosting VPS tunggal (Tencent Cloud Lighthouse 2 vCPU / 2 GB RAM ~$5-8/bulan) untuk modular monolith vs managed PaaS/Serverless (Vercel + Supabase Free/Pro Tier).
3. **Penyedia AI & Integrasi Kunci API Live:**
   - Penentuan model AI utama (Gemini API vs OpenAI) untuk fitur AI Review dan AI Copy, kebijakan pembatasan token, serta mekanisme fallback deterministik ketika kuota habis atau jaringan terputus.
4. **Penyedia Autentikasi Pengguna Riil:**
   - Transisi dari token sesi berbasis passcode sintetis lokal (`POST /v1/sessions`) ke penyedia OAuth 2.0 (Google Workspace / WhatsApp OTP / Supabase Auth) ketika aplikasi dibuka untuk multi-user publik.

---

## 6. Verifikasi & Pengujian Otomatis

Skrip spike dilengkapi dengan unit test otomatis di `tests/test_stack_spike.py`:

```sh
# Menjalankan unit test skrip spike
python3 -W error::ResourceWarning -m unittest tests/test_stack_spike.py -v

# Menjalankan seluruh test suite aplikasi
python3 -W error::ResourceWarning -m unittest discover -s tests -v

# Memverifikasi integritas dokumen dan kepatuhan repository
python3 scripts/check_repository.py
```

Seluruh pengujian terverifikasi: **113 tests lulus**, **10 tests dilewati** (10 pengujian integrasi live PostgreSQL 17 dilewati secara aman karena `MARKETSTUDIO_TEST_POSTGRES_URL` tidak diset), total 123 tests tanpa peringatan kebocoran sumber daya (*zero ResourceWarning*).
