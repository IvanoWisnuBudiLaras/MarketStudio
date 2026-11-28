# Spike lembar kerja Univer V3

Ruang kerja yang baru dibuat membuka lembar kosong. Pemilik dapat menyimpan nilai dan rumus pada satu lembar 100 × 26, lalu membuka kembali isinya. Anggota aktif lain dapat membaca. Omzet untuk tanggal laporan yang dipilih tampil di atas editor dan berasal dari endpoint laporan harian ruang kerja aktif. Editor menyimpan dokumen per ruang kerja di tabel SQLite `v3_worksheets`. Laporan, stok, kas, dan penjualan tetap dihitung dari transaksi.

`GET` dan `PUT /v1/workspaces/{workspace_id}/worksheet` memakai autentikasi lokal V3 dan memeriksa keanggotaan di server. Tulis mensyaratkan role owner. Isi sel divalidasi di server, body dibatasi 1 MiB, dan revisi menolak penimpaan isi yang lebih baru. Pengiriman ulang isi yang sudah tersimpan mengembalikan revisi saat ini. Startup membuat tabel kosong secara idempoten pada SQLite V3 yang dikonfigurasi. Rollback cukup kembalikan versi aplikasi V3 sebelumnya, yang mengabaikan tabel dokumen. Pertahankan tabel jika isi lembar masih diperlukan.

## Paket dan kompatibilitas

| Komponen | Versi yang dipasang |
| --- | --- |
| `@univerjs/presets`, `@univerjs/preset-sheets-core` | 1.6.2, Apache-2.0 |
| React dan React DOM | 19.3.1 |
| Next.js App Router dan Turbopack | 16.4.6 |
| RxJS, peer yang diselesaikan npm | 7.8.2 |
| Node.js dan npm lokal | 26.12.0 dan 11.19.0 |

Manifest preset mengizinkan React/React DOM 19 dan RxJS 7 ke atas. Panduan resmi Univer mendukung React 18/19 dan menempatkan instance di effect browser. Next.js mendokumentasikan `dynamic(..., { ssr: false })` untuk komponen klien. Spike menguji kombinasi versi di tabel melalui instalasi dari lockfile, build Turbopack, typecheck, dan Chromium. [Lisensi dan cakupan Web SDK](https://github.com/dream-num/univer/blob/dev/README.md) · [Integrasi React Univer](https://docs.univer.ai/guides/sheets/getting-started/integrations/react) · [Lazy loading Next.js](https://nextjs.org/docs/app/guides/lazy-loading)

Bukti terbatas pada preset desktop inti. Dokumen menyimpan nilai dan rumus sel, sementara format, tata letak, rich text, dan metadata workbook berada di luar cakupan. Kolaborasi, impor/ekspor XLSX, server SDK, paket Pro, dukungan editor mobile, dan sambungan Supabase berada di luar spike. [Batas preset dan pemetaan plugin mobile](https://docs.univer.ai/guides/sheets/getting-started/installation)

## Reproduksi

- API: `uv sync --locked --extra v3` lalu `uv run --locked --extra v3 python -W error::ResourceWarning -m unittest discover -s tests -p test_v3_transport.py -v`.
- Web dari `web/`: `npm ci`, `npm run build`, `npm run typecheck`, `npx playwright install chromium`, lalu `npx playwright test`.
- Playwright membuat SQLite sementara dari skema dan memasukkan transaksi melalui UI. Bukti worksheet berisi edit yang dibaca ulang dengan clipboard browser serta omzet Rp29.000 dari laporan. Tangkapan layar `univer-worksheet.png` berada di `web/test-results/` dan diunggah melalui job V3 sebagai artefak `marketstudio-v3-browser-evidence`.
- Repositori: `python scripts/check_repository.py` dan `git diff --check`.
