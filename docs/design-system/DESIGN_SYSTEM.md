# MarketStudio Design System
Direction approved: Modern Minimalist × Enterprise Commerce (A+B), satu accent #2563EB, navy, putih dan coffee dark, customizable. Token berikut selain accent adalah proposal. Logo raster terakhir di assets/branding/logo-reference.png; jangan mengklaim SVG master.

## Brand dan tokens
| Token | Light candidate | Dark candidate |
|---|---|---|
| accent | #2563EB | #2563EB (uji contrast) |
| brand navy | #142B52 | #142B52 |
| canvas | #F7F8FA | #141210 |
| surface | #FFFFFF | #1C1917 |
| surface elevated | #EFF6FF | #292524 |
| text | #172033 | #F5F5F4 |
| border | #E2E6EC | perlu contrast test |

Primitive → semantic → component tokens. Semantic success/warning/error tidak berubah mengikuti accent. Theme system/light/coffee dark; custom accent divalidasi contrast dan fallback. Preferensi lokal untuk fast startup, sync server opsional. Geist Sans/Mono kandidat; base 14, section 18, heading 24, display 32, tabular nums. Spacing 4px grid; radius 8px; desktop button 36px, touch target 44px kandidat. Jangan menyatakan WCAG compliant tanpa audit.

## Layout dan interaction
Desktop rail 64, sidebar 240, header 56, AI panel 360, content padding 24 kandidat. Mobile gunakan responsive navigation dan panel yang tidak menutup task utama. Studio dibedakan icon/nama, bukan warna berbeda. Empty state memberi next action; loading skeleton tidak menyatakan data aktual; error menampilkan recovery; destructive action confirmation; save state jelas. Financial card membedakan actual/estimate/simulation, period, unit dan drill-down. Chart tidak hanya mengandalkan warna; table punya header dan keyboard navigation. Form memiliki label, inline validation, focus visible dan error summary bila perlu.

## Component contract
Button: default/hover/focus/disabled/loading; loading mencegah duplicate submit. Input: label, helper, error, required, keyboard. Table: sort/filter/pagination, empty/error, accessible row action. Dialog: focus trap, escape, return focus; destructive confirmation. Toast bukan satu-satunya bukti transaksi. AI panel: source, limitations, regenerate, copy, approve; tidak mengubah data tanpa action eksplisit. Publish status per channel, demo badge jelas.

## Pola alur inti

- **Satu tindakan utama per state.** Gunakan tombol utama untuk langkah berikutnya. Di Beranda, urutannya mengikuti kesiapan usaha: buat profil, tambah produk atau jasa pertama, lalu catat transaksi. Tautan terkait, pilihan demo, contoh isian, dan pemuatan ulang laporan memakai gaya sekunder. Letakkan panduan panjang di bagian yang bisa dibuka saat dibutuhkan. Ini menerapkan Hick’s Law dan Selective Attention.
- **Kelompokkan berdasarkan keputusan pengguna.** Tempatkan arus kas bersih beserta kas masuk dan keluar dalam satu area. Letakkan laba kotor beserta omzet dan harga pokok penjualan (HPP) di sebelahnya atau langsung di bawahnya pada layar sempit. Beri satu periode laporan yang jelas, lalu tampilkan stok akhir dan transaksi terbaru sebagai konteks. Pertahankan urutan baca yang sama di HTML dan mobile. Gunakan nilai, periode, dan status penilaian dari laporan. Jika suatu nilai belum dinilai, tampilkan status tersebut. Ini menerapkan Law of Proximity, Law of Common Region, dan Chunking.
- **Pertahankan posisi dan perilaku kontrol.** Sidebar tetap memuat seluruh Studio, termasuk Creative Studio. Navigasi cepat di ponsel menandai halaman aktif dan drawer mengembalikan fokus saat ditutup dengan Escape. Tab memakai tombol panah serta Home/End. Kontrol sentuh berukuran minimal 44 × 44 piksel, dengan fokus keyboard terlihat. Ikon garis memakai SVG inline 24 × 24 dan warna teks. Ikon dekoratif memakai `aria-hidden`, aksi utama memakai label teks, dan tombol ikon saja memiliki nama aksesibel. Gunakan lockup MarketStudio di sidebar dan potongan mark dari PNG yang sama di header ringkas dan favicon. Ini menerapkan Jakob’s Law dan Fitts’s Law.
- **Minta isian saat konteksnya tersedia.** Pilih produk atau jasa sebelum menampilkan kuantitas dan nominal transaksi. Di Analisis, tampilkan kolom survei manual saat sumber itu dipilih. Kaitkan error ke field dengan `aria-describedby` dan `aria-invalid`, jelaskan cara memperbaikinya, pertahankan input, lalu fokuskan field pertama yang perlu diperbaiki. Beri status saat menyimpan dan hasil yang dapat diperiksa pada riwayat atau laporan di tanggal transaksi.
- **Tunjukkan konteks data pada titik keputusan.** Tandai demo pada workspace dan halaman, serta tampilkan sumber dan periode data historis di hasil analisis. Gunakan narasi singkat untuk menjelaskan perbedaan makna angka. Tempatkan jejak audit, status pajak, dan mutasi stok pada rincian laporan.
- **Pisahkan pengaturan dari pekerjaan utama.** Aksi sekunder “Atur ringkasan” membuka dialog samping dengan pilihan modul dan “Pulihkan tampilan”. Terapkan pilihan segera dan simpan daftar modul tersembunyi di browser per `workspace_id`. Pertahankan modul kas dan laba sebagai bagian tetap. Dialog menahan fokus selama terbuka, dapat ditutup dengan Escape, mengembalikan fokus ke pemicu, dan dapat digulir pada layar pendek. Untuk stok habis, tampilkan barang dengan jumlah nol dari katalog saat ini. Nilai stok akhir tetap mengikuti tanggal laporan.

Rujukan prinsip ada di [Laws of UX](https://lawsofux.com/). Bukti penerapan pada 390 dan 1440 piksel tersedia di [verifikasi Issue #62](evidence/issue-62/README.md) dan [verifikasi status transaksi Issue #7](evidence/issue-7/README.md).

## Integration
Astryx meta/astryx dan Univer dream-num/univer adalah pilihan arah; verify React compatibility, actual token API, license dan commercial boundaries. Jangan mengarang import atau CLI command. Spike satu button, form, table, theme toggle dan workbook; uji build dan keyboard. Fabric.js kandidat editor, bukan mandatory. QA: contrast WCAG 2.2 AA target, keyboard, focus, screen reader, zoom, mobile, dark/custom theme, loading/error/empty. Catat hasil aktual dan screenshot jika tersedia.
