# Business Requirement Document — MarketStudio
Status: draft untuk review Product Owner. Keputusan visi mengikuti D01–D05; requirement rinci berikut PROPOSED kecuali dinyatakan lain.

## Masalah dan peluang
UMKM sering mengelola usaha melalui catatan manual, chat, spreadsheet dan aplikasi kanal terpisah. Ini adalah hipotesis umum yang perlu diuji, bukan hasil survei MarketStudio. Reference case Bakso membuktikan kebutuhan yang lebih spesifik dalam konteks proyek: pemilik perlu membedakan uang diterima, biaya bahan yang benar-benar digunakan, persediaan tersisa dan laba. Perluasan ke jasa menuntut pemahaman kapasitas, durasi, biaya tenaga dan jadwal, bukan sekadar stok. MarketStudio tidak boleh menjadi aplikasi akuntansi enterprise yang memaksa pengguna belajar terminologi kompleks sebelum mencatat transaksi.

## Visi dan nilai
Satu workspace untuk memahami, menjalankan dan mengembangkan usaha. Business OS membantu operasi sehari-hari; entrepreneurship platform memperluas ke discovery, planning, opportunity dan growth. Nilai utama bukan jumlah fitur, tetapi hubungan data operasi dengan keputusan dan distribusi. Tagline kandidat One Studio. Every Market. Pengguna dapat masuk pada tahap Discover, Start, Operate, Grow atau Scale; tahap ini bukan state wajib yang menghalangi fitur.

## Stakeholder
Owner UMKM mengatur harga, keputusan dan akses. Operator mencatat penjualan/layanan dengan permission terbatas. Calon pengusaha mengeksplorasi asumsi tanpa mencampur data simulasi dengan aktual. Collaborator marketing menyiapkan konten tanpa akses otomatis ke data sensitif. Product Owner MarketStudio memutuskan scope dan kebijakan; AI teammate bukan stakeholder bisnis yang berwenang mengubah aturan.

## Business requirements
| ID | Kebutuhan | Bukti outcome |
|---|---|---|
| BR-01 | Satu workspace lintas enam studio | Offering yang sama dapat dirujuk tanpa duplikasi identitas |
| BR-02 | Operasi barang dan jasa | Contoh penjualan barang dan layanan dapat dicatat tanpa field domain yang tidak relevan |
| BR-03 | Financial integrity | Revenue, HPP, profit dan cash flow terpisah dan dapat ditelusuri |
| BR-04 | Intelligence berbasis bukti | Review AI menunjuk periode, sumber metric dan keterbatasan |
| BR-05 | Planning dan simulation | Skenario tidak mengubah transaksi aktual |
| BR-06 | Creative workflow | Asset, copy dan draft dapat direview sebelum distribusi |
| BR-07 | Omnichannel distribution | Status per kanal, approval dan error terlihat; live hanya bila API tersedia |
| BR-08 | Adaptive experience | Capability relevan dapat diaktifkan tanpa mengubah histori |
| BR-09 | Trust dan portability | Data tenant terisolasi, export dan audit tersedia sesuai scope |
| BR-10 | Sustainable engineering | Tim kecil dapat memelihara sistem tanpa microservice berlebihan |

## Portfolio dan dependency
Business Studio menjadi authoritative operational record. Intelligence membaca metric terverifikasi, bukan menulis ulang transaksi. Spreadsheet menyediakan analisis dan simulasi dengan import/export tervalidasi. Creative mengelola draft dan asset. Commerce memetakan offering ke marketplace; Social memetakan campaign ke kanal sosial. Shared Core mengelola workspace, identity, permission, catalog identity, asset reference, job dan audit; bukan produk ketujuh. Hubungan antarstudio tidak berarti setiap pengguna harus memakai semua studio.

## Scope dan batas
P0 kandidat: Core, Business, Intelligence. P1 Spreadsheet dan Creative dalam vertical slice. P2 Commerce/Social tergantung izin API dan aturan lomba. Full marketplace sync, statutory accounting, payroll, taxation, real-time collaboration, native app, custom LLM dan autonomous agent bukan scope awal. Monetisasi, target segmen pertama, offline policy dan multiuser depth masih OPEN. Tidak menjanjikan peningkatan laba atau penjualan tanpa evaluasi empiris.

## Ukuran keberhasilan
Usulan evaluasi: waktu mencatat transaksi, tingkat keberhasilan task, kesalahan input, kemampuan pengguna menjelaskan perbedaan laba dan kas, ketepatan rekonsiliasi, waktu membuat draft dan jumlah langkah distribusi. Ukur baseline melalui usability test; jangan mengarang target atau hasil. Competition demo harus menunjukkan workflow nyata, bukan hanya dashboard berisi angka statis.
