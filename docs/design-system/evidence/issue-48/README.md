# Verifikasi Issue #48

Di Creative Studio, pemilik memilih produk atau jasa dan satu gambar berizin opsional. Pratinjau menyimpan salinan nama usaha, nama dan jenis offering, satuan, harga jual, piksel gambar serta atribusinya. Teks dirender dengan escaping, gambar disandikan ulang tanpa metadata berkas, dan preview memakai iframe sandbox. Draft poster, caption dan informasi biaya tetap di area pemilik.

Penerbitan eksplisit mengaktifkan snapshot yang sudah dipratinjau dan membuat URL baru. Satu versi aktif per workspace. Tautan sebelumnya dicabut dalam transaksi yang sama. Perubahan produk atau pratinjau berikutnya tidak mengubah versi aktif. Tautan aktif bisa dibuka siapa pun yang memilikinya. Setelah ditarik, GET dan HEAD menerima 404; respons publik memakai `Cache-Control: no-store, no-cache, must-revalidate`. Salinan yang sudah dibuat oleh pengunjung berada di luar kendali server.

Caption promosi memakai draft contoh manual Creative Studio. Pratinjau dan ekspor SVG/PNG memakai kontrak versi dan SHA-256 Issue #42. Issue #16 tetap menjadi dependensi generasi copy AI dan verifikasi provider. Alur ini berjalan pada SQLite lokal dengan fixture sintetis. Ketersediaan PostgreSQL mengikuti batas penyimpanan Creative Studio. Rilis eksternal tetap bergantung pada persetujuan rilis.

## Bukti

| Pemeriksaan | Hasil |
|---|---|
| `python3 -W error::ResourceWarning -m unittest discover -s tests -v` | Exit 0. 49 tes, 41 lulus dan 8 integrasi dilewati karena URL PostgreSQL tidak dikonfigurasi. |
| `python3 scripts/check_repository.py` | Exit 0. Dokumen, metadata skill, path dan pola kredensial lolos. |
| `git diff --check` | Exit 0. |
| `node scripts/check_public_catalog.cjs http://127.0.0.1:8148 390 docs/design-system/evidence/issue-48` | Exit 0. Chromium headless, viewport 390 × 844. |
| `node scripts/check_public_catalog.cjs http://127.0.0.1:8149 1440 docs/design-system/evidence/issue-48` | Exit 0. Chromium headless, viewport 1440 × 1000. |

Jalankan server dengan `MARKETSTUDIO_DB_PATH` menunjuk ke basis data sementara yang baru untuk setiap ukuran dan `MARKETSTUDIO_PORT` sesuai URL. Skrip browser memakai Playwright dari `NODE_PATH` dan Chromium dari `CHROMIUM_PATH`. Skrip memeriksa isi pratinjau, pengunjung tanpa sesi, clipboard, kecocokan byte kedua format unduhan, isolasi versi, penarikan, overflow, serta ukuran kontrol sentuh. Tes HTTP juga mencakup pemilik lintas workspace, anggota tanpa peran pemilik, pratinjau kedaluwarsa, percobaan ulang publikasi, URL baru, dan escaping nama offering.

- 390 px. [Pratinjau pemilik](preview-390.png) · [Katalog publik](public-390.png)
- 1440 px. [Pratinjau pemilik](preview-1440.png) · [Katalog publik](public-1440.png)

## Penyimpanan dan rollback lokal

Startup SQLite menambahkan tabel `catalog_versions` beserta indeks versi aktif dan draft. Schema lawas tidak perlu dikonversi atau dihapus. Jika aplikasi dikembalikan ke revisi sebelumnya, tabel bisa tetap disimpan dan rute katalog publik berhenti tersedia.
