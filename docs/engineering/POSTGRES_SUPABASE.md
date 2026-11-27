# Integrasi PostgreSQL & Migrasi Versioned Supabase

Dokumen ini menjelaskan jalur PostgreSQL opsional untuk MarketStudio (Issue #54) tanpa mengubah profil default **SQLite** yang dipakai Docker preview (`127.0.0.1:8765`) dan unit/integration test standar.

## 1. Profil Backend Database

- **Default (`MARKETSTUDIO_DB_BACKEND=sqlite`, atau tidak disetel):**
  Menggunakan `sqlite3` dari Python stdlib (`MARKETSTUDIO_DB_PATH`, default `data/marketstudio.db`), nol dependency eksternal.
- **PostgreSQL (`MARKETSTUDIO_DB_BACKEND=postgres`):**
  Membutuhkan optional dependency `psycopg[pool]` (`pip install -e ".[postgres]"` atau `".[postgres-binary]"`) serta `DATABASE_URL` (atau `MARKETSTUDIO_DATABASE_URL`) dengan skema `postgres://` atau `postgresql://`.
  Jika `MARKETSTUDIO_DB_BACKEND=postgres` aktif tanpa `DATABASE_URL` yang valid, aplikasi **gagal eksplisit** (`ValueError`) dan tidak diam-diam fallback ke SQLite.

## 2. Environment Variables

Lihat template aman tanpa secret di [.env.example](../../.env.example):

| Variable | Default | Keterangan |
|---|---|---|
| `MARKETSTUDIO_DB_BACKEND` | `sqlite` | `sqlite` atau `postgres` |
| `MARKETSTUDIO_DB_PATH` | `data/marketstudio.db` | Lokasi file SQLite saat backend `sqlite` |
| `DATABASE_URL` | — | DSN PostgreSQL runtime/pool (dibaca saat backend `postgres`) |
| `DIRECT_DATABASE_URL` / `MIGRATION_DATABASE_URL` | fallback ke `DATABASE_URL` | DSN direct/owner untuk CLI `python3 -m app.migrations` |
| `MARKETSTUDIO_PG_SSLMODE` | otomatis (`require` untuk host non-lokal) | Override `sslmode` jika belum ada di DSN |
| `MARKETSTUDIO_AUTO_MIGRATE` | `1` (dev), `0` (`MARKETSTUDIO_ENV=production`) | Apakah `init_db()` otomatis menerapkan migrasi pending |
| `MARKETSTUDIO_DB_POOL_MIN` / `_MAX` | `1` / `10` | Ukuran connection pool `psycopg_pool` |
| `MARKETSTUDIO_DB_CONNECT_TIMEOUT` | `10` | Timeout koneksi (detik) |
| `MARKETSTUDIO_PG_PREPARE_THRESHOLD` | kosong (`None`) | Nonaktifkan prepared statement server-side agar aman pada Supavisor / PgBouncer transaction mode |
| `MARKETSTUDIO_DB_STATEMENT_TIMEOUT_MS` | kosong | Jika diisi (> 0), diset per transaksi via `set_config('statement_timeout', ..., true)` |

Catatan keamanan: `app.db.redact_dsn()` selalu menyamarkan username/password sebelum logging atau output CLI.

## 3. Migrasi Versioned (`migrations/postgres/`)

Setiap migrasi memakai pasangan `.up.sql` dan `.down.sql` bernomor urut serta tercatat pada tabel `schema_migrations` (menyimpan `version`, `name`, `checksum` SHA-256, `applied_at`):

1. `0001_initial_schema`: membuat 13 tabel domain (`sessions`, `workspaces`, `workspace_memberships`, `offerings`, `purchases`, `inventory_batches`, `inventory_pools`, `stock_movements`, `sales`, `sale_lines`, `cash_movements`, `idempotency_keys`, `audit_events`) dengan `BIGINT` + guard `<= 10^15` untuk nilai IDR, `NUMERIC` untuk kuantitas/biaya unit tanpa drift float, `TIMESTAMPTZ`, dan `BOOLEAN`.
2. `0002_rls_and_service_privileges`: mengaktifkan Row Level Security (default-deny) pada seluruh tabel, mencabut akses `PUBLIC`/`anon`/`authenticated` bila role ada, dan memberi hak DML-only (`SELECT, INSERT, UPDATE, DELETE`) kepada `service_role` pada tabel domain serta `SELECT` pada `schema_migrations`.
3. `0003_offering_description`: menambahkan deskripsi opsional pada offering dengan nilai kosong untuk data lama. Pilih versi aplikasi yang sesuai saat rollback. Migrasi turun menghapus kolom beserta deskripsi di dalamnya.

### Perintah CLI Migrasi

```sh
# Cek status migrasi (read-only, aman bagi service role)
python3 -m app.migrations status

# Terapkan seluruh migrasi pending secara atomik (dilindungi advisory lock)
python3 -m app.migrations up

# Rollback 1 langkah terakhir atau hingga versi tertentu (0000 = bersih total)
python3 -m app.migrations down --steps 1
python3 -m app.migrations down --to 0000
```

## 4. Konkurensi & Konsistensi dengan SQLite

- Seluruh query tetap strictly parameterized (translator `?` → `%s` hanya di luar string literal/komentar, tanpa interpolasi nilai SQL).
- Transaksi write di `BaselineService` memakai `acquire_write_lock(...)` yang memanggil `pg_advisory_xact_lock(hashtextextended(...))` di dalam transaksi `READ COMMITTED`, menyamai serialisasi `BEGIN IMMEDIATE` pada SQLite sekaligus tetap kompatibel dengan transaction pooling Supavisor.
- Jika PostgreSQL menolak koneksi/pool saat runtime, error dipetakan menjadi HTTP `503` (`database_unavailable`) tanpa membocorkan DSN.

## 5. Pengujian Lokal Terisolasi (PostgreSQL 17)

Uji lokal menggunakan container ephemeral `postgres:17` tanpa menyentuh `marketstudio-preview` (`127.0.0.1:8765`) maupun remote Supabase:

```sh
docker run -d --rm --name marketstudio-pg17-test \
  -e POSTGRES_USER=marketstudio_admin \
  -e POSTGRES_PASSWORD=local_test_only_pw \
  -e POSTGRES_DB=marketstudio_test \
  -p 127.0.0.1:55432:5432 postgres:17

uv venv .venv
uv pip install --python .venv/bin/python -e ".[postgres]"

MARKETSTUDIO_TEST_POSTGRES_URL="postgresql://marketstudio_admin:local_test_only_pw@127.0.0.1:55432/marketstudio_test" \
  .venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -v

docker stop marketstudio-pg17-test
rm -rf .venv
```

**Batas scope Issue #54:** Jangan menerapkan migrasi ke proyek Supabase remote sebelum review Nexus, crosscheck Atlas, dan persetujuan smoke test pada schema kosong.
