# Verifikasi Issue #7: Status Penyimpanan Transaksi

Verifikasi ini membuktikan implementasi umpan balik status penyimpanan (sedang menyimpan, berhasil, gagal), pencegahan submit ganda saat respons lambat, retensi input form saat koneksi putus, dan mekanisme coba lagi (retry) dengan Idempotency-Key yang konsisten pada form penjualan dan pembelian MarketStudio.

## Screenshot Bukti (390 px & 1440 px)

| Keadaan | 390 px (Ponsel) | 1440 px (Desktop) |
|---|---|---|
| Sedang menyimpan (in-flight, submit disabled) | [Ponsel](tx-status-inflight-390.png) | [Desktop](tx-status-inflight-1440.png) |
| Jaringan terganggu (error, input retained, tombol 'Coba Lagi') | [Ponsel](tx-status-error-retry-390.png) | [Desktop](tx-status-error-retry-1440.png) |
| Transaksi pertama berhasil tersimpan | [Ponsel](tx-status-success-initial-390.png) | [Desktop](tx-status-success-initial-1440.png) |
| Skenario akhir (retry konsisten & keyboard interaction) | [Ponsel](tx-status-final-390.png) | [Desktop](tx-status-final-1440.png) |

## Hasil Pengujian

1. **Status In-Flight & Pencegahan Submit Ganda**:
   - Status visual & live region (`aria-live="polite"`, class `status info`) menampilkan `"Sedang menyimpan penjualan..."` / `"Sedang menyimpan pembelian..."`.
   - Tombol submit beralih ke state `disabled` dengan atribut `aria-busy="true"` dan teks `"Sedang menyimpan..."`. Form memiliki `aria-busy="true"`.
   - Klik berulang kali yang cepat selama respons lambat (simulasi delay 600ms) diabaikan oleh kontrol, mencegah duplikasi request ke backend.

2. **Penanganan Kegagalan Jaringan & Retensi Input**:
   - Saat simulasi request abort / network offline, seluruh isian form pengguna (`offering`, `qty`, `price`/`cost`) dipertahankan secara utuh tanpa reset.
   - Live region menampilkan pesan error yang ramah dan jelas (`role="alert"`, class `status err`): `"Koneksi terganggu. Isian formulir tetap tersimpan. Periksa jaringan Anda lalu klik Coba Lagi untuk mencoba lagi."`.
   - Tombol tindakan `'Coba Lagi'` (`#saleRetryBtn` dan `#purRetryBtn`) ditampilkan di dalam area status dengan touch target minimal 44 × 44 piksel pada mobile (bebas undersized controls).

3. **Invariansi Idempotensi pada Percobaan Ulang (Retry)**:
   - Request pertama dan request retry mengirim nilai header `Idempotency-Key` yang identik selama isian formulir tidak diubah.
   - Pada skenario response lost (transaksi berhasil commit di backend tetapi respons terputus sebelum sampai ke browser), retry dengan key yang sama mengembalikan transaksi yang telah tersimpan (HTTP 201) tanpa menimbulkan mutasi ganda pada tabel `sales`, `stock_movements`, atau `cash_movements`.

4. **Status Sukses & Interaksi Keyboard**:
   - Menampilkan status keberhasilan yang jelas dengan nomor referensi transaksi, pembaruan tabel riwayat transaksi (`#txRecentBody`), serta ringkasan kas dan laba kotor di Beranda.
   - Tombol submit kembali aktif dan token idempotensi lama dibersihkan (`localStorage` pending key dihapus), sehingga transaksi berikutnya akan menghasilkan Idempotency-Key baru yang unik.
   - Form mendukung navigasi keyboard dan pengiriman instan menggunakan tombol Enter dari kolom input.

5. **Responsif & Aksesibilitas**:
   - Bebas horizontal overflow pada 390px dan 1440px (`scrollWidth <= window.innerWidth`).
   - Seluruh kontrol interaktif memenuhi ukuran touch target >= 44x44px pada layar ponsel.
   - Tidak ada emoji/pictographic yang tidak sesuai standar desain.

## Perintah Pengujian Ulang

```sh
# 1. Jalankan unit & contract tests Python
python3 -W error::ResourceWarning -m unittest discover -s tests -v

# 2. Periksa repositori
python3 scripts/check_repository.py && git diff --check

# 3. Jalankan Playwright E2E verification
python3 -c 'from app.server import create_server; create_server(port=8268, db_path="/tmp/tx-status-e2e.sqlite", backend="sqlite").serve_forever()' &
SERVER_PID=$!
sleep 1
CHROMIUM_PATH=/usr/bin/chromium NODE_PATH=/home/ivano/.local/share/mise/installs/playwright/latest/node_modules node scripts/check_transaction_status.cjs http://127.0.0.1:8268 390 docs/design-system/evidence/issue-7
CHROMIUM_PATH=/usr/bin/chromium NODE_PATH=/home/ivano/.local/share/mise/installs/playwright/latest/node_modules node scripts/check_transaction_status.cjs http://127.0.0.1:8268 1440 docs/design-system/evidence/issue-7
kill $SERVER_PID
rm -f /tmp/tx-status-e2e.sqlite
```
