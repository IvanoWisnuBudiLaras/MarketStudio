# MarketStudio Database Backup & Restore Verification

Dokumentasi implementasi dan pembuktian prosedur backup dan restore ke target basis data baru terpisah menggunakan dataset sintetis (Issue #44, Gate 2, Gate release).

Skrip `scripts/backup_restore.py` adalah alat otomasi berbasis **Python 3 standard library** (tanpa dependensi eksternal pihak ketiga) untuk mengeksekusi pencadangan (backup) online & atomik, pemulihan (restore) ke target terpisah, serta verifikasi integritas kuantitatif, laporan keuangan, isolasi keamanan tenant, dan kesiapan operasional server.

---

## 1. Arsitektur & Spesifikasi Alat

### Mekanisme Backup & Restore

| Profil Basis Data | Metode Backup | Metode Restore | Integritas & Verifikasi |
|---|---|---|---|
| **SQLite (Default)** | Online atomic backup via `sqlite3.Connection.backup()` ke berkas sementara, dilanjutkan swap atomik `os.replace` | Restore aman ke target berkas terpisah via `sqlite3.backup()` setelah validasi header & `PRAGMA integrity_check` | Pemeriksaan magic header `SQLite format 3\x00`, `PRAGMA integrity_check`, dan verifikasi checksum SHA-256 |
| **PostgreSQL (Lokal/Tools)** | Snapshot custom archive terkompresi via `pg_dump --format=c` | Pemulihan aman via `pg_restore --clean --if-exists --no-owner --no-privileges` | Validasi konektivitas DSN (redacted untuk keamanan log), verifikasi checksum SHA-256 |

### Metadata & Artefak Sidecar

Setiap pencadangan menghasilkan berkas snapshot mandiri serta dapat menulis metadata JSON sidecar (`*.json`) yang memuat:
- `backend`: Jenis basis data (`sqlite` atau `postgres`).
- `source`: Path sumber (atau DSN ter-redact).
- `backup_file`: Path absolut berkas artefak cadangan.
- `artifact_size_bytes`: Ukuran artefak dalam bytes.
- `sha256`: Checksum SHA-256 64-karakter hex digest.
- `duration_ms`: Durasi eksekusi backup dalam milidetik.
- `tables_count`: Jumlah baris per tabel pada saat pencadangan.
- `created_at`: Stempel waktu ISO-8601 UTC.

---

## 2. Cara Penggunaan & Konfigurasi CLI

### Subcommand `backup`

Membuat berkas cadangan dari basis data sumber:

```sh
# Backup default SQLite (membaca MARKETSTUDIO_DB_PATH atau default app)
python3 scripts/backup_restore.py backup --output backups/marketstudio.backup

# Backup eksplisit dengan metadata JSON sidecar
python3 scripts/backup_restore.py backup \
  --source data/marketstudio.db \
  --output backups/marketstudio_20261128.backup \
  --metadata backups/marketstudio_20261128.json

# Format output JSON terstruktur untuk otomasi CI/CD
python3 scripts/backup_restore.py backup -s data/marketstudio.db -o backups/prod.backup --json
```

### Subcommand `restore`

Memulihkan basis data ke berkas/target baru yang terpisah:

```sh
# Restore standar dengan verifikasi integritas otomatis
python3 scripts/backup_restore.py restore \
  --backup-file backups/marketstudio.backup \
  --target data/restored_target.db

# Restore dengan validasi checksum SHA-256 ketat
python3 scripts/backup_restore.py restore \
  --backup-file backups/marketstudio.backup \
  --target data/restored_target.db \
  --checksum 3cfbd7bb511aa9bd38dc7287dfe93ed9827927403cb2ce9f3e5e22138505916b
```

### Subcommand `verify`

Memverifikasi kecocokan antara basis data sumber dan basis data pulihan:

```sh
python3 scripts/backup_restore.py verify \
  --source-db data/marketstudio.db \
  --restored-db data/restored_target.db
```

### Subcommand `drill`

Menjalankan simulasi penuh end-to-end pada dataset sintetis terisolasi:

```sh
# Menjalankan drill sintetis lengkap (buat data -> backup -> restore -> 4 level verifikasi)
python3 scripts/backup_restore.py drill

# Menjalankan drill dengan output JSON
python3 scripts/backup_restore.py drill --json
```

---

## 3. Tabel Kode Keluar (Exit Codes) & Penanganan Error

| Kode Keluar | Status | Deskripsi |
|---|---|---|
| `0` | **PASS** | Operasi backup, restore, verifikasi, atau drill selesai dengan sukses 100%. |
| `1` | **FAIL** | Kegagalan integritas data: checksum mismatch, berkas backup korup/terpotong, perbedaan jumlah baris tabel, atau ketidakcocokan angka laporan keuangan. |
| `2` | **ERROR** | Kesalahan konfigurasi atau argumen CLI: argumen wajib tidak diisi, berkas sumber tidak ditemukan, atau path target tidak valid/berupa direktori. |

---

## 4. Penanganan Skenario Kegagalan (Robust Error Handling)

Alat menangani kegagalan sistem secara defensif tanpa meninggalkan state parsial atau merusak target:

1. **Berkas Backup Terpotong atau Kosong (Truncated / Empty)**:
   - Pemeriksaan ukuran minimum berkas (< 100 bytes) dan magic header bytes (`SQLite format 3\x00`).
   - Berkas rusak langsung ditolak dengan pesan `BackupCorruptError` dan exit code `1`.
2. **Checksum Mismatch (SHA-256)**:
   - Bila opsi `--checksum` disertakan atau manifest dibaca, SHA-256 aktual dihitung sebelum menyentuh berkas target.
   - Bila hash tidak cocok, proses langsung dihentikan (`ChecksumMismatchError`, exit code `1`) tanpa memodifikasi target.
3. **Kerusakan Internal Halaman Basis Data (Corrupted Database Pages)**:
   - Sebelum restore dipublikasikan, `PRAGMA integrity_check` dijalankan.
   - Jika b-tree page atau pointer sel korup, proses dibatalkan dan file sementara dihapus.
4. **Path Target Invalid atau Berupa Direktori**:
   - Jika path target merupakan direktori atau direktori induk tidak dapat dibuat, dilemparkan `TargetPathInvalidError` informatif dengan exit code `2`.
5. **Basis Data Sumber Tidak Ditemukan**:
   - Jika path basis data sumber tidak ada, dilemparkan `SourceDatabaseNotFoundError` informatif dengan exit code `2`.

---

## 5. Bukti Hasil Verifikasi (Test Evidence on Synthetic Data)

Berikut adalah bukti nyata eksekusi end-to-end drill menggunakan dataset sintetis multi-tenant (`python3 scripts/backup_restore.py drill --json`):

### A. Metrik Waktu, Ukuran Artefak, & Checksum

- **Durasi Backup**: `0.31 ms` (atomic page copy)
- **Ukuran Artefak Backup**: `180.224 bytes` (176 KB)
- **Checksum SHA-256**: `3cfbd7bb511aa9bd38dc7287dfe93ed9827927403cb2ce9f3e5e22138505916b`
- **Durasi Restore**: `0.31 ms`
- **Status Integritas Restore**: `ok` (SHA-256 verified, PRAGMA integrity_check passed)

### B. Verifikasi Kuantitatif Baris Tabel (17/17 Tabel Cocok 100%)

Total baris sumber: **32 baris** | Total baris pulihan: **32 baris**

| Nama Tabel | Baris Sumber | Baris Dipulihkan | Status |
|---|---|---|---|
| `audit_events` | 9 | 9 | **MATCH** |
| `cash_movements` | 3 | 3 | **MATCH** |
| `catalog_versions` | 0 | 0 | **MATCH** |
| `creative_assets` | 0 | 0 | **MATCH** |
| `creative_image_attempts` | 0 | 0 | **MATCH** |
| `idempotency_keys` | 0 | 0 | **MATCH** |
| `inventory_batches` | 2 | 2 | **MATCH** |
| `inventory_pools` | 2 | 2 | **MATCH** |
| `offerings` | 4 | 4 | **MATCH** |
| `poster_drafts` | 0 | 0 | **MATCH** |
| `purchases` | 2 | 2 | **MATCH** |
| `sale_lines` | 1 | 1 | **MATCH** |
| `sales` | 1 | 1 | **MATCH** |
| `sessions` | 0 | 0 | **MATCH** |
| `stock_movements` | 3 | 3 | **MATCH** |
| `workspace_memberships` | 3 | 3 | **MATCH** |
| `workspaces` | 2 | 2 | **MATCH** |

### C. Verifikasi Laporan Bisnis & Keuangan (100% Cocok)

Perbandingan angka laporan harian (`GET /v1/workspaces/{id}/reports/daily`) pada workspace utama:

| Indikator Finansial / Stok | Nilai Sumber | Nilai Dipulihkan | Selisih | Status |
|---|---|---|---|---|
| **Pendapatan (Revenue)** | Rp60.000 | Rp60.000 | Rp0 | **MATCH** |
| **Harga Pokok Penjualan (HPP / COGS)** | Rp36.000 | Rp36.000 | Rp0 | **MATCH** |
| **Laba Kotor (Gross Profit)** | Rp24.000 | Rp24.000 | Rp0 | **MATCH** |
| **Arus Kas Masuk (Cash In)** | Rp60.000 | Rp60.000 | Rp0 | **MATCH** |
| **Arus Kas Keluar (Cash Out)** | Rp210.000 | Rp210.000 | Rp0 | **MATCH** |
| **Arus Kas Bersih (Net Cash Flow)** | -Rp150.000 | -Rp150.000 | Rp0 | **MATCH** |
| **Valuasi Persediaan Akhir (WA Valuation)** | Rp174.000 | Rp174.000 | Rp0 | **MATCH** |
| **Saldo Stok: Bakso Urat** | 6 pcs (Rp54.000) | 6 pcs (Rp54.000) | 0 | **MATCH** |
| **Saldo Stok: Beras Medium** | 10 kg (Rp120.000) | 10 kg (Rp120.000) | 0 | **MATCH** |

### D. Verifikasi Keamanan & Isolasi Tenant

- **Akses Pemilik Sah**: Pemilik aktif (`usr_demo_owner`) berhasil mengakses data penawaran (`offerings`) dan laporan workspace.
- **Isolasi Lintas Tenant**: Aktor asing / penyusup acak (`usr_attacker_*`) ditolak dengan DomainError HTTP `403/404`.
- **Penolakan Tanpa Otentikasi**: Permintaan tanpa aktor (token tidak valid/kosong) ditolak dengan HTTP `401`.
- **Preservasi Hak Akses Dicabut (Revoked)**: Anggota yang dicabut hak aksesnya (`usr_revoked_staff`) tetap ditolak pada basis data hasil restore.

### E. Verifikasi Operasional Server Baru (`/health`)

- Instance HTTP server baru dijalankan mengarah langsung ke berkas basis data target hasil restore (`synthetic_restored.db`).
- Request `GET /health`:
  - HTTP Status: `200 OK`
  - Respons JSON: `{"status": "ok", "service": "marketstudio-baseline", "db_backend": "sqlite"}`
  - Waktu respons: `5.48 ms`

---

## 6. Verifikasi Repositori & Test Suite

Seluruh pengujian unit dan verifikasi repositori dijalankan dengan opsi strict `ResourceWarning` bebas peringatan:

```sh
# Verifikasi aturan dokumen repositori, credential pattern, dan skill metadata
python3 scripts/check_repository.py
# Hasil: PASS required documents, skill metadata, ignored paths and credential patterns

# Verifikasi seluruh 86 automated test cases
python3 -W error::ResourceWarning -m unittest discover -s tests -v
# Hasil: Ran 86 tests in 26.881s -> OK (skipped=8)

# Verifikasi whitespace git diff
git diff --check
# Hasil: Bersih (clean)
```
