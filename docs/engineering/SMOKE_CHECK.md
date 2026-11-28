# MarketStudio Web Release Smoke Check

Dokumentasi alat smoke check web rilis MarketStudio (Issue #43, Gate 3, Gate release).

Skrip `scripts/smoke_check.py` adalah alat verifikasi minimum berbasis **Python 3 standard library** (tanpa dependensi eksternal) untuk menguji kesiapan deployment web sebelum menerima lalu lintas pengguna atau proses rilis.

---

## 1. Spesifikasi Endpoint yang Diuji

| Endpoint | Metode | Kriteria Lulus | Penanganan Kegagalan |
|---|---|---|---|
| `/` | `GET` | HTTP 200 OK, Content-Type `text/html`, respons tidak kosong, memuat marker HTML atau MarketStudio | Non-2xx, respons kosong, atau tanpa marker HTML -> FAIL |
| `/health` | `GET` | HTTP 200 OK, format JSON valid berupa objek kamus (`dict`), field `status` bernilai `"ok"` | Non-2xx, non-JSON (HTML error page proxy), JSON corrupt, atau `status != "ok"` -> FAIL |

Kedua endpoint dipanggil menggunakan header `User-Agent: MarketStudio-SmokeCheck/1.0` serta header `Accept` yang sesuai (`text/html` untuk root, `application/json` untuk health).

---

## 2. Cara Penggunaan & Konfigurasi

### Perintah CLI

```sh
# Format umum
python3 scripts/smoke_check.py <BASE_URL> [--timeout DETIK] [--json] [--quiet]

# Contoh pengujian server lokal
python3 scripts/smoke_check.py http://127.0.0.1:8000 --timeout 5.0

# Opsi flag --base-url / -u
python3 scripts/smoke_check.py -u http://127.0.0.1:8000 -t 5.0

# Output format JSON terstruktur untuk otomasi/skrip
python3 scripts/smoke_check.py http://127.0.0.1:8000 --json

# Mode senyap (hanya mencetak ringkasan kelulusan)
python3 scripts/smoke_check.py http://127.0.0.1:8000 --quiet
```

### Konfigurasi Environment Variable

Bila argumen CLI tidak disertakan, skrip otomatis membaca variabel lingkungan berikut:

| Environment Variable | Keterangan | Default |
|---|---|---|
| `MARKETSTUDIO_BASE_URL` (atau `BASE_URL`) | URL dasar target (contoh: `http://127.0.0.1:8000`) | Wajib disediakan via argumen atau env |
| `MARKETSTUDIO_SMOKE_TIMEOUT` (atau `SMOKE_TIMEOUT`) | Batas waktu tunggu request HTTP dalam detik | `10.0` |

Contoh pemanggilan via environment variable:
```sh
export MARKETSTUDIO_BASE_URL="http://127.0.0.1:8000"
export MARKETSTUDIO_SMOKE_TIMEOUT="5.0"
python3 scripts/smoke_check.py
```

---

## 3. Tabel Kode Keluar (Exit Codes) & Penanganan Error

| Kode Keluar | Status | Deskripsi |
|---|---|---|
| `0` | **PASS** | Seluruh pemeriksaan (2/2) berhasil: HTTP 200 dengan konten valid pada `/` dan `/health`. |
| `1` | **FAIL** | Pemeriksaan gagal: HTTP non-2xx (404, 500, 503), respons invalid (bukan JSON di `/health`, status bukan `"ok"`), timeout, atau koneksi jaringan ditolak. |
| `2` | **ERROR** | Kesalahan konfigurasi atau argumen CLI: URL dasar tidak ditentukan, skema bukan `http`/`https`, atau format timeout tidak valid/non-positif. |

---

## 4. Bukti Hasil Pengujian (Test Evidence)

### A. Uji Sukses pada Server Lokal Dinamis Terisolasi

Perintah:
```sh
python3 scripts/smoke_check.py http://127.0.0.1:44609 --timeout 5
```
Hasil:
```text
Exit code: 0
STDOUT:
=== Menjalankan MarketStudio Smoke Check ===
Target Base URL : http://127.0.0.1:44609
Timeout         : 5.0s
---------------------------------------------
[PASS] ROOT (http://127.0.0.1:44609/) [7.5ms] -> HTTP 200 OK (HTML valid, 219352 bytes)
[PASS] HEALTH (http://127.0.0.1:44609/health) [0.7ms] -> HTTP 200 OK (status: ok, service: marketstudio-baseline, backend: sqlite)

PASS Smoke check berhasil: 2/2 endpoint sehat.
```

### B. Uji Skenario Kegagalan HTTP 503 (Service Unavailable)

Perintah:
```sh
python3 scripts/smoke_check.py http://127.0.0.1:37729
```
Hasil:
```text
Exit code: 1
STDOUT:
=== Menjalankan MarketStudio Smoke Check ===
Target Base URL : http://127.0.0.1:37729
Timeout         : 10.0s
---------------------------------------------
[PASS] ROOT (http://127.0.0.1:37729/) [6.8ms] -> HTTP 200 OK (HTML valid, 40 bytes)
[FAIL] HEALTH (http://127.0.0.1:37729/health) [0.6ms] -> HTTP 503 (Service Unavailable): Service Unavailable

STDERR:
FAIL Smoke check gagal: 1/2 endpoint bermasalah.
```

### C. Uji Skenario Kegagalan Respons Non-JSON pada `/health` (HTML Error Page)

Perintah:
```sh
python3 scripts/smoke_check.py http://127.0.0.1:42527
```
Hasil:
```text
Exit code: 1
STDOUT:
=== Menjalankan MarketStudio Smoke Check ===
Target Base URL : http://127.0.0.1:42527
Timeout         : 10.0s
---------------------------------------------
[PASS] ROOT (http://127.0.0.1:42527/) [5.7ms] -> HTTP 200 OK (HTML valid, 40 bytes)
[FAIL] HEALTH (http://127.0.0.1:42527/health) [0.4ms] -> Respons /health bukan format JSON valid: Expecting value: line 1 column 1 (char 0) (snippet: '<html>Bad Gateway Error</html>')

STDERR:
FAIL Smoke check gagal: 1/2 endpoint bermasalah.
```

### D. Uji Skenario Kegagalan Network Timeout

Perintah:
```sh
python3 scripts/smoke_check.py http://127.0.0.1:42529 --timeout 0.1
```
Hasil:
```text
Exit code: 1
STDOUT:
=== Menjalankan MarketStudio Smoke Check ===
Target Base URL : http://127.0.0.1:42529
Timeout         : 0.1s
---------------------------------------------
[FAIL] ROOT (http://127.0.0.1:42529/) [105.6ms] -> Permintaan melebihi batas waktu (timeout 0.1 detik)
[FAIL] HEALTH (http://127.0.0.1:42529/health) [100.8ms] -> Permintaan melebihi batas waktu (timeout 0.1 detik)

STDERR:
FAIL Smoke check gagal: 2/2 endpoint bermasalah.
```

### E. Uji Skenario Koneksi Ditolak (Server Tidak Aktif)

Perintah:
```sh
python3 scripts/smoke_check.py http://127.0.0.1:59991
```
Hasil:
```text
Exit code: 1
STDOUT:
=== Menjalankan MarketStudio Smoke Check ===
Target Base URL : http://127.0.0.1:59991
Timeout         : 10.0s
---------------------------------------------
[FAIL] ROOT (http://127.0.0.1:59991/) [5.2ms] -> Koneksi ditolak (Connection refused) - server web target tidak aktif atau port salah: [Errno 111] Connection refused
[FAIL] HEALTH (http://127.0.0.1:59991/health) [0.1ms] -> Koneksi ditolak (Connection refused) - server web target tidak aktif atau port salah: [Errno 111] Connection refused

STDERR:
FAIL Smoke check gagal: 2/2 endpoint bermasalah.
```

---

## 5. Verifikasi Otomatis

Seluruh logika smoke check diuji secara otomatis pada file `tests/test_smoke_check.py` yang mencakup 12 metode pengujian terisolasi (real server baseline, mock failure scenarios, parameter validation, JSON output, quiet mode, timeout, dan connection refused).

Jalankan test suite lengkap:
```sh
python3 -W error::ResourceWarning -m unittest discover -s tests -v
python3 scripts/check_repository.py
git diff --check
```
Hasil: **70/70 tests passed (8 skipped PostgreSQL dev-only)** tanpa kebocoran resource socket (`ResourceWarning`).
