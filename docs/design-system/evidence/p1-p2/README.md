# Bukti Penerimaan Visual P1–P2 · Shared Shell & Business Studio Overview

Dokumen ini memuat bukti penerimaan visual aktual untuk penerapan Issue #76 (P1 Shared Shell dan P2 Business Studio Overview). Pengujian dijalankan menggunakan Playwright Chromium headless terhadap server HTTP lokal dengan basis data SQLite sementara terisolasi per pengujian.

## Ringkasan Matriks Pengujian

| Viewport | Lebar x Tinggi | State Kosong | State Terisi (Demo) | Collapsed Rail (~64px) |
|---|---|---|---|---|
| Desktop 1440 | 1440 × 1000 px | [empty-1440.png](empty-1440.png) | [populated-1440.png](populated-1440.png) | [collapsed-1440.png](collapsed-1440.png) |
| Desktop 1280 | 1280 × 900 px | [empty-1280.png](empty-1280.png) | [populated-1280.png](populated-1280.png) | [collapsed-1280.png](collapsed-1280.png) |
| Tablet 768 | 768 × 1024 px | [empty-768.png](empty-768.png) | [populated-768.png](populated-768.png) | Sesuai drawer / responsive |
| Mobile 390 | 390 × 844 px | [empty-390.png](empty-390.png) | [populated-390.png](populated-390.png) | Sesuai bottom nav & drawer |

## Kriteria Penerimaan yang Terverifikasi

1. **P1 — Shared Application Shell (Satu Shell Bersama)**:
   - Sidebar navy enterprise (`#142B52`) dengan teks terang (`#E2E8F0`, muted `#8A9BB5`), hover halus (`rgba(255,255,255,0.08)`), dan status aktif konsisten (`#2563EB`, bayangan `0 2px 8px rgba(37,99,235,0.35)`).
   - Sidebar collapsible (~240px terbuka dan ~64px ringkas icon rail) dengan tombol toggle `#sidebarCollapseBtn` yang memiliki accessible name dan target sentuh >= 44×44px. Dilarang dan terbukti tidak menampilkan sidebar penuh dan icon rail secara bersamaan.
   - Logo kucing resmi dari `assets/branding/logo-reference.png` (`/brand/lockup.png` saat terbuka dan `/brand/mark.png` saat ringkas/ponsel). Tanpa emoji, tanpa huruf M, tanpa robot generik.
   - Navigasi 6 studio dalam satu ekosistem tersusun berurutan sesuai arahan PO:
     1. Business Studio (`#ringkasan`) dengan sub-nav Transaksi (`#transaksi`) dan Katalog & Stok (`#katalog`)
     2. Intelligence Studio (`#studio-intelligence`, label Preview)
     3. Spreadsheet Studio (`#analisis`, label Aktif)
     4. Creative Studio (`#studio-creative`, label Aktif)
     5. Commerce Studio (`#studio-commerce`, label Roadmap)
     6. Social Studio (`#studio-social`, label Roadmap)
     serta Profil & Pengaturan (`#profil`) dan Workspace Selector terpadu.
   - Topbar bersama (~60px) dengan konteks studio (`Business Studio`), judul halaman (`Beranda`), status workspace, tombol utama aksi `Catat transaksi`, dan pemicu dialog pengaturan `Atur ringkasan`.
   - Responsif tanpa overflow horizontal (`scrollWidth <= window.innerWidth`) di seluruh viewport 1440px, 1280px, 768px, dan 390px. Di mobile 390px seluruh tombol sentuh memenuhi minimum 44×44px.

2. **P2 — Business Studio Overview & Resolusi HOLD Atlas**:
   - **Eliminasi Duplikasi 4 KPI**: Headline 4 KPI (Arus kas bersih, Laba kotor, Omzet, Nilai persediaan) hanya muncul SATU KALI sebagai headline cards utama (toggled terpadu via `#quickMetrics` di preferensi ringkasan). Duplikasi kartu ringkasan kecil di dalam modul kas telah dihapus total.
   - **Rekonstruksi Modul Arus Kas**: Modul kas (`#dailyReport`) didedikasikan secara terfokus pada pergerakan kas riil: Kas Masuk (Inflow), Kas Keluar (Outflow), Arus Kas Bersih (Net), serta kotak edukasi finansial terstruktur (`.cash-education-box`) yang menjelaskan perbedaan esensial antara laba kotor operasional vs uang kas riil di tangan.
   - **Penyederhanaan Entry Point AI Review**: Menghilangkan panel promosi AI statis di kolom kanan desktop yang memakan ruang dan memiliki CTA kedua redundan. Menyisakan SATU entry point AI Business Review yang ringkas, elegan, dan fungsional pada greeting banner (`#heroAiReviewBtn`).
   - **Penataan Kolom Desktop yang Seimbang**: Di desktop (1440px / 1280px), kolom kiri memuat Ringkasan Arus Kas dan kolom kanan memuat Transaksi Terbaru dengan tinggi yang proporsional dan sejajar, diikuti Ringkasan Persediaan (stok akhir, alert stok habis, tabel produk) di bawahnya, dan rincian audit di bawah lipatan.
   - **Optimasi Mobile (390px Above-The-Fold)**:
     - Ketinggian header, date controls, dan greeting banner diringkas.
     - 4 KPI headline cards disusun dalam format **grid 2x2** pada viewport 390px sehingga seluruh nominal angka terbaca jelas dengan tabular figures dan langsung tampak di atas lipatan layar (**above the fold**) tanpa perlu scroll.
     - Touch target kontrol interaktif tetap memenuhi standar minimum 44×44px.
   - Penanganan state kosong yang jujur (formulir pembuatan profil usaha onboarding) dan state terisi tanpa mengarang data atau proyeksi palsu.

## Cara Mengulang Pengujian Visual

Pastikan Chromium terpasang (`/usr/bin/chromium`) dan modul Playwright tersedia di `NODE_PATH`.

```sh
# Menjalankan server lokal disposable
python3 -c 'from app.server import create_server; create_server(port=8555, db_path="/tmp/test_p1_p2.sqlite", backend="sqlite").serve_forever()'

# Mengambil bukti visual untuk setiap viewport
CHROMIUM_PATH=/usr/bin/chromium node scripts/capture_p1_p2_evidence.cjs http://127.0.0.1:8555 1440 docs/design-system/evidence/p1-p2
CHROMIUM_PATH=/usr/bin/chromium node scripts/capture_p1_p2_evidence.cjs http://127.0.0.1:8555 1280 docs/design-system/evidence/p1-p2
CHROMIUM_PATH=/usr/bin/chromium node scripts/capture_p1_p2_evidence.cjs http://127.0.0.1:8555 768 docs/design-system/evidence/p1-p2
CHROMIUM_PATH=/usr/bin/chromium node scripts/capture_p1_p2_evidence.cjs http://127.0.0.1:8555 390 docs/design-system/evidence/p1-p2
```
