# Konteks MarketStudio
Product Owner ingin proyek ambisius tetapi development praktis, minim copy-paste dan pekerjaan berulang. MarketStudio berasal dari riset Bakso Business Assistant, berkembang menjadi platform UMKM barang, jasa, digital, rental, produksi dan hybrid. Bukan enam aplikasi terpisah.

Visi disetujui: C (AI Business Operating System) sebagai fondasi + D (AI Entrepreneurship Platform) sebagai arah jangka panjang. Mendampingi calon pengusaha hingga usaha berkembang. Tagline: One Studio. Every Market. Siklus: Understand → Discover → Plan → Manage → Create → Distribute → Evaluate → Improve. Tahap pengguna: Discover, Start, Operate, Grow, Scale. Tahapan dan siklus adalah rancangan, bukan scope wajib.

Enam studio: Business, Intelligence, Spreadsheet, Creative, Commerce, Social. Shared Core bukan produk ketujuh. Satu AI Business Partner lintas studio adalah ide yang menarik tetapi belum disetujui sebagai scope; implementasi awal cukup satu LLM dengan structured context dan tools. Business DNA, habit intelligence, health score, growth planner, opportunity discovery, daily briefing dan campaign orchestration adalah usulan, bukan kewajiban MVP.

Arah UX: Modern Minimalist × Enterprise Commerce (A+B), satu accent biru #2563EB, navy, putih, coffee dark, tema customizable. Logo kucing 2D tiga perempat menghadap kanan atas, detail sedang, di rounded square biru solid. Logo yang disetujui tersedia di assets/branding/logo-reference.png (raster, bukan SVG master).

Stack kandidat: Next.js/React/TypeScript, Astryx (repo meta/astryx), Univer (dream-num/univer), FastAPI, Supabase, Vercel, Tencent Lighthouse 2 vCPU/2 GB RAM. Fabric.js untuk editor bila perlu. Jangan memaksakan dependency tanpa compatibility/license check. Tidak ada model lokal berat. Product Owner ingin Gemini untuk development dan Codex untuk dokumentasi, skills, MCP dan harness.

Target lomba TECHCOMFEST 2027, deadline 18 Desember 2026 23:59 WIB berdasarkan rulebook yang disertakan. Scope harus dibatasi. Integrasi Shopee, Tokopedia, Instagram, TikTok, Facebook adalah visi one-click, bukan klaim koneksi aktif.

Sumber: percakapan MarketStudio dan lima dokumen Bakso asli. Shared chat https://chatgpt.com/share/6b080826-6e94-83ec-9685-5ceca1c8c614 belum dibaca lengkap; jangan mengklaim hasil riset dari isi yang tidak tersedia. Habit di luar Bakso masih hipotesis. DESIGN.md lama dan tickets asli tidak tersedia.

## Sejarah dan rationale
Awalnya owner mencari stack web AI yang mudah: Node.js frontend di Vercel, PHP server, Python AI. Diskusi berkembang dari aplikasi Flutter offline-first untuk usaha bakso keluarga menjadi web platform. Perubahan ini adalah perubahan produk yang disengaja, bukan migrasi otomatis semua requirement Flutter. Bakso tetap menjadi reference case untuk financial integrity dan habit operasional. Harga Rp5.000 adalah harga jual mangkuk jadi, bukan biaya bahan. Jangan mengubah makna tersebut.

Owner memilih satu bisnis dengan enam produk agar BRD dan GOALS global, sementara PRD/TSD domain dapat berevolusi. Visi C+D disetujui: Business OS sebagai fondasi, entrepreneurship platform sebagai arah jangka panjang. Owner secara eksplisit menekankan jasa dan variasi UMKM; jangan memaksa semua bisnis memiliki resep, stok atau produksi. Arah UI A+B dipilih karena tampilan hybrid warna-warni dianggap kurang elegan; satu accent biru dan coffee dark dipilih. Logo mengalami beberapa iterasi; hanya referensi raster terakhir menjadi acuan, bukan logo hoodie atau wajah terlalu sederhana.

Owner ingin development minim kerja manual, menggunakan Gemini untuk implementasi dan Codex untuk strategi, skill, harness dan MCP. Tiga teammate final dalam diskusi: Atlas (strategist), Forge (builder), Nexus (guardian/enabler). Usulan 15 teammate ditolak secara praktis; spesialisasi menjadi skill, bukan identitas baru. Orca-first adalah arah eksplorasi, belum bukti integrasi. Model ID dan reasoning effort harus diperiksa pada instalasi aktual. AI boleh berinisiatif dan memberi ide tidak biasa, tetapi pelaksanaan harus jelas dan tidak mengarang bukti.

V1 dinilai terlalu ringkas oleh owner. V2 mengutamakan rationale, contoh, kontrak, edge case, traceability dan batas scope. Target kata yang pernah diusulkan bukan acceptance criterion; kualitas dan kejelasan lebih penting. Tidak ada transkrip lengkap shared chat Bakso; sumber asli yang tersedia disimpan tanpa perubahan. Riset habit di luar sumber tersebut adalah hipotesis.
