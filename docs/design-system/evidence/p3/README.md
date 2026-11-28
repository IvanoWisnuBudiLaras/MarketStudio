# Bukti Penerimaan Visual P3 · Intelligence Studio & Spreadsheet Studio

Dokumen ini memuat bukti penerimaan visual aktual untuk penerapan Issue #78 (P3 Intelligence Studio dan Spreadsheet Studio terintegrasi). Seluruh pengujian dijalankan menggunakan Playwright Chromium headless terhadap server HTTP lokal dengan basis data SQLite sementara terisolasi per pengujian.

## Ringkasan Matriks Pengujian Visual

| Viewport | Lebar × Tinggi | Intelligence Studio (Kosong) | Intelligence Studio (Terisi) | Intelligence Studio (Fallback) | Spreadsheet Studio (Kosong) | Spreadsheet Studio (Terisi) |
|---|---|---|---|---|---|---|
| Desktop 1440 | 1440 × 1000 px | [intel-empty-1440.png](intel-empty-1440.png) | [intel-populated-1440.png](intel-populated-1440.png) | [intel-fallback-1440.png](intel-fallback-1440.png) | [sheet-empty-1440.png](sheet-empty-1440.png) | [sheet-populated-1440.png](sheet-populated-1440.png) |
| Desktop 1280 | 1280 × 900 px | [intel-empty-1280.png](intel-empty-1280.png) | [intel-populated-1280.png](intel-populated-1280.png) | [intel-fallback-1280.png](intel-fallback-1280.png) | [sheet-empty-1280.png](sheet-empty-1280.png) | [sheet-populated-1280.png](sheet-populated-1280.png) |
| Tablet 768 | 768 × 1024 px | [intel-empty-768.png](intel-empty-768.png) | [intel-populated-768.png](intel-populated-768.png) | [intel-fallback-768.png](intel-fallback-768.png) | [sheet-empty-768.png](sheet-empty-768.png) | [sheet-populated-768.png](sheet-populated-768.png) |
| Mobile 390 | 390 × 844 px | [intel-empty-390.png](intel-empty-390.png) | [intel-populated-390.png](intel-populated-390.png) | [intel-fallback-390.png](intel-fallback-390.png) | [sheet-empty-390.png](sheet-empty-390.png) | [sheet-populated-390.png](sheet-populated-390.png) |

---

## Kriteria Penerimaan yang Terverifikasi

### 1. Intelligence Studio (Editorial Report & Actionable Insights)
- **Layout Editorial Report Nyaman Dibaca**:
  - Mengadopsi struktur laporan bertingkat dengan tipografi dan spasi berjenjang (bukan kumpulan kartu bento kecil yang padat).
  - Mengedepankan ruang baca eksekutif yang tenang dan profesional (Modern Minimalist × Enterprise Commerce).
- **Header Konteks Informatif**:
  - Menampilkan periode laporan terverifikasi (`2026-11-28 Asia/Jakarta`), tanggal audit WIB, cakupan transaksi harian, dan sumber data (`Server MetricSnapshot`).
  - Dilengkapi indikator mode read-only dan badge status provider AI secara jujur.
- **Kartu Ringkasan AI Business Review & 4 Metrik Riil**:
  - Banner hero modern dengan gradasi tenang `#EFF6FF` → `#DBEAFE`.
  - Grid 4 metrik terverifikasi langsung dari `MetricSnapshot`: Omzet (Rp 60.000 · 1 transaksi), Laba Kotor (Rp 24.000 · status HPP assessed), Arus Kas Bersih (−Rp 150.000 · Masuk Rp 60.000, Keluar Rp 210.000), dan Nilai Persediaan (Rp 174.000).
  - Dilarang dan terbukti tanpa health score fiktif, proyeksi palsu, atau klaim angka tanpa sitasi audit.
- **Temuan Kunci & Bukti Audit (Provenance)**:
  - Ringkasan eksekutif naratif, daftar poin sorotan analisis (highlights) dengan ikon check, dan kotak audit sitasi yang memuat `Snapshot ID`, periode tanggal, dan jumlah `source_ids` terverifikasi.
  - Peringatan transparan untuk data belum lengkap (`missing_data`), misalnya status pajak belum dinilai (`not_assessed`).
- **Daftar Rekomendasi Strategis Terarah (Actionable Recommendations)**:
  - Tiga kartu rekomendasi konkret (Optimasi Harga & Margin, Struktur Costing HPP, Daya Saing Pasar Bapanas).
  - Dilengkapi tombol tautan langsung menuju lembar kerja atau simulator di Spreadsheet Studio (`#analisis` / `#studio-spreadsheet`).
- **Modul Benchmark Harga Pasar Terintegrasi**:
  - Tabel komoditas resmi Bapanas (snapshot Maret 2026 Rp 13.378/kg) dan demo Kramat Jati (Rp 13.500/kg).
  - Formulir perbandingan interaktif dengan produk katalog dan opsi survei manual berbukti (`manual_fallback`).
  - Tombol uji harga hasil benchmark langsung ke Spreadsheet Studio.
- **Penanganan State**:
  - State kosong: Pesan panduan ramah jika belum ada profil usaha atau transaksi tercatat.
  - State fallback: Saat provider offline/timeout, menampilkan banner fallback deterministik yang transparan tanpa merusak UI.

---

### 2. Spreadsheet Studio (Document-Oriented Planning Workspace)
- **Layout Berorientasi Lembar Kerja (Worksheet Document)**:
  - Mengadopsi tata letak dokumen lembar kerja (bukan dashboard kartu bento), terinspirasi dari acuan visual `MarketStudio Spreadsheet Pricing Dashboard.png`.
  - Judul workbook, pemilihan produk katalog, dan badge status dokumen: `Simulasi Perencanaan Harga & Diskon (Draf)`.
  - Batasan implementasi dinyatakan secara jujur di header: tahap awal simulator perencanaan, bukan authoritative financial ledger.
- **Spreadsheet Toolbar & Formula Bar**:
  - Toolbar interaktif: tombol undo/redo, pemilihan font, ukuran teks, pemformatan tebal/miring/garis bawah, perataan teks, border, dan format angka (`%`, `Rp`, `.0`, `.00`, `fx`).
  - Formula bar aktif menampilkan kotak sel aktif (misal `E7`, `E2`) dan formula kalkulasi terkait (misal `=C7*D7`, `=SUM(E2:E6)`).
- **Tabel Lembar Kerja Costing Terstruktur**:
  - Header kolom abjad (A, B, C, D, E, F) dan nomor baris (1..9).
  - Komponen biaya: Bahan Baku Utama, Bahan Penolong/Sortir, Bahan Pelengkap, Kemasan & Label, Biaya Langsung Tenaga, Alokasi Overhead Operasional (10%), dan Total HPP.
  - Interaksi klik sel: memperbarui highlight sel aktif (`.sheet-cell-active`), kotak sel formula bar, dan nilai formula.
- **Strip Ringkasan Metrik di Bawah Grid**:
  - 4 metrik bersih: HPP per Unit (Rp 10.727), Harga Jual Saat Ini (Rp 15.000), Laba Kotor per Unit (Rp 4.273), dan Margin Kontribusi (28,49%).
- **Tab Lembar Kerja & Kontrol Tampilan**:
  - Tab di bagian bawah: `+`, `Costing Produk`, `Simulasi Harga & Diskon`, `Break Even`, serta indikator zoom 100%.
- **Panel Skenario Simulasi Harga & Diskon (Inspector)**:
  - Preset skenario cepat: Skenario A (Kompetitif), Skenario B (Promo Diskon 10%), Skenario C (Premium +20%).
  - Input what-if assumptions: referensi produk katalog, harga jual baru, estimasi biaya pokok unit, dan persentase diskon.
  - Kalkulasi seketika: Harga Nett, Laba per Unit, Margin Kontribusi (%), dan Markup (%).
  - Tabel perbandingan skenario yang memperbandingkan harga jual, laba/unit, dan margin ketiga skenario secara sejajar.
  - Kotak edukasi dan rekomendasi analitis berdasarkan margin kontribusi yang dihasilkan.
  - Penegasan zero-mutation: perubahan simulasi terisolasi murni dan tidak memutasi transaksi atau buku besar kas.
- **Ekspor Dokumen**:
  - Tombol `Ekspor CSV` mengunduh lembar kerja costing dan ringkasan skenario dalam format CSV standar tanpa dependensi luar.

---

### 3. Integritas Navigasi & Shared Shell P1–P2
- **Deep Linking Hash Multistudio**:
  - `#studio-intelligence` membuka Intelligence Studio.
  - `#studio-spreadsheet`, `#spreadsheet`, `#analisis`, dan `#analisis-simulasi` membuka Spreadsheet Studio.
  - `#analisis-benchmark` membuka dan memfokuskan modul Benchmark Pasar di Intelligence Studio.
  - State reload pada setiap studio mempertahankan view yang aktif tanpa kehilangan data sesi.
- **Responsivitas & Aksesibilitas**:
  - Lolos uji tanpa horizontal overflow (`scrollWidth <= window.innerWidth`) pada seluruh viewport (1440px, 1280px, 768px, 390px).
  - Bebas dari emoji antarmuka (menggunakan SVG native icons).
  - Pada viewport mobile 390px, 100% kontrol interaktif (`button`, `.btn`, `.mobile-nav-btn`, `.nav-link`) memenuhi target sentuh minimum ≥ 44×44px.
  - Kontras teks badge/pill di seluruh area putih (`main`) telah dioptimasi memenuhi standar keterbacaan WCAG AA.

---

## Cara Menjalankan Ulang Pengujian Visual

```sh
# 1. Jalankan server lokal sementara
python3 -c 'from app.server import create_server; create_server(port=8560, db_path="/tmp/p3_test.sqlite", backend="sqlite", quiet_logs=True).serve_forever()' &
SERVER_PID=$!

# 2. Tangkap bukti visual untuk setiap viewport
CHROMIUM_PATH=/usr/bin/chromium NODE_PATH=/home/ivano/.npm/_npx/e41f203b7505f1fb/node_modules node scripts/capture_p3_evidence.cjs http://127.0.0.1:8560 1440 docs/design-system/evidence/p3
CHROMIUM_PATH=/usr/bin/chromium NODE_PATH=/home/ivano/.npm/_npx/e41f203b7505f1fb/node_modules node scripts/capture_p3_evidence.cjs http://127.0.0.1:8560 1280 docs/design-system/evidence/p3
CHROMIUM_PATH=/usr/bin/chromium NODE_PATH=/home/ivano/.npm/_npx/e41f203b7505f1fb/node_modules node scripts/capture_p3_evidence.cjs http://127.0.0.1:8560 768 docs/design-system/evidence/p3
CHROMIUM_PATH=/usr/bin/chromium NODE_PATH=/home/ivano/.npm/_npx/e41f203b7505f1fb/node_modules node scripts/capture_p3_evidence.cjs http://127.0.0.1:8560 390 docs/design-system/evidence/p3

# 3. Hentikan server lokal
kill $SERVER_PID
```
