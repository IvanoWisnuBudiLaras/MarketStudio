# Verifikasi Issue #62

Pembanding memakai `origin/main` pada `e3f35e9` setelah Creative Studio digabungkan. Chromium headless mengakses aplikasi melalui HTTP lokal dengan SQLite sementara. Setiap pengujian versi baru memakai database kosong tersendiri. Screenshot demo diambil sebelum penjualan tambahan, memakai tanggal yang dikembalikan saat fixture dimuat.

| Keadaan | 390 px | 1440 px |
|---|---|---|
| Belum ada profil usaha | [Sebelum](before-empty-390.png) · [Sesudah](after-empty-390.png) | [Sebelum](before-empty-1440.png) · [Sesudah](after-empty-1440.png) |
| Beranda dengan demo | [Sebelum](before-demo-390.png) · [Sesudah](after-demo-390.png) | [Sebelum](before-demo-1440.png) · [Sesudah](after-demo-1440.png) |
| Validasi jumlah melebihi stok | [Ponsel](after-validation-390.png) | [Desktop](after-validation-1440.png) |
| Beranda setelah penjualan | [Ponsel](after-result-390.png) | [Desktop](after-result-1440.png) |
| Panel Atur ringkasan | [Ponsel](after-drawer-390.png) | [Desktop](after-drawer-1440.png) |

## Hasil

- Playwright lulus pada kedua lebar. Uji mencakup CTA sesuai state, logo lokal, ukuran kontrol ponsel, fokus keyboard, menu dan tab, identitas demo, replay idempoten, error stok dan isian yang tetap, serta penjualan dan pembaruan laporan. Uji juga membuka Katalog, Analisis dan input survei manual, membuat draft poster, membuka pratinjau, mengunduh SVG dari Creative Studio, dan beralih kembali ke usaha tanpa transaksi.
- Fixture menunjukkan arus kas bersih −Rp150.000, laba kotor Rp24.000, dan stok akhir Rp174.000. Penjualan barang Rp15.000 muncul pertama di transaksi terbaru dan mengubah arus kas bersih menjadi −Rp135.000.
- Kedua lebar lulus pengujian panel Atur ringkasan. Enter membuka dialog, Escape menutupnya dan mengembalikan fokus, dan panel dapat digulir pada viewport ponsel yang dipendekkan. Pilihan demo bertahan setelah muat ulang, tampilan usaha pemilik memiliki pilihan sendiri, dan pemulihan tampilan demo hanya mengatur ulang preferensi demo. Barang baru yang jumlahnya nol tampil sebagai “Stok habis saat ini”.
- `python3 -W error::ResourceWarning -m unittest discover -s tests -v` selesai dengan exit 0. Ada 47 kasus, dengan 8 kasus PostgreSQL dilewati karena URL pengujian PostgreSQL belum dikonfigurasi.
- `python3 scripts/check_repository.py` dan `git diff --check` selesai dengan exit 0.

## Ulangi uji browser

Siapkan Playwright yang dapat diimpor oleh Node.js. Jalankan perintah server dari root repo untuk setiap lebar dengan path database sementara berbeda. Gunakan executable Chromium dari Playwright atau atur `CHROMIUM_PATH` ke executable lokal.

```sh
python3 -c 'from app.server import create_server; create_server(port=8262, db_path="/tmp/marketstudio-ux-390.sqlite", backend="sqlite").serve_forever()'
node scripts/check_core_workflows.cjs http://127.0.0.1:8262 390 /tmp/marketstudio-ux-evidence
```

Ulangi dengan database kosong baru dan argumen `1440`.
