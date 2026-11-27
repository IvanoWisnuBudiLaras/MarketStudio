# MarketStudio — Master Documentation V2

**Status:** working knowledge base; bukan release aplikasi. **Bahasa:** Indonesia dengan English technical terminology. **Entry point:** START_CODEX.md.

MarketStudio adalah satu platform AI Business Operating System dengan arah jangka panjang AI Entrepreneurship Platform. Enam studio berbagi workspace dan data, bukan enam aplikasi independen. Tujuannya membantu usaha barang, jasa dan hybrid memahami kondisi usaha, mengelola operasi, merencanakan pertumbuhan dan menjangkau pasar.

## Peta baca
- AGENTS.md: aturan eksekusi dan prioritas sumber.
- PROJECT_CONTEXT.md: sejarah, alasan dan batas pengetahuan.
- BRD.md / GOALS.md: business intent dan outcome.
- TSD.md: rancangan teknis global; keputusan teknis belum otomatis approved.
- docs/DECISIONS.md: status keputusan; docs/history/v1 hanya arsip.
- docs/products/*: PRD, TSD dan skenario per studio.
- docs/platform: kontrak lintas domain; docs/discovery: riset dan hipotesis.
- docs/design-system: identitas dan UX; docs/engineering: agent infrastructure.
- .teammates: Atlas, Forge, Nexus; konfigurasi konseptual, bukan native Orca.
- docs/competition: rulebook asli dan compliance; docs/exploration: ide non-binding.

Jangan menjalankan semua roadmap sekaligus. Baca ticket yang disetujui dan dependency relevan. Jangan menimpa repo lokal tanpa diff.

## Runnable Baseline (Issue #5 + #12/#10/#32/#11/#36/#38/#39/#20)

- **Stack:** Python 3 standard library (`http.server`, `sqlite3`, `unittest`) modular monolith (`app/`), single browser entry point (`GET /` -> `app/web/index.html`), dan local SQLite storage (`data/marketstudio.db`). Tanpa dependency eksternal sehingga langsung berjalan dari clean clone.
- **Auth & Tenant Isolation:** Server-verified session tokens (`POST /v1/sessions` memverifikasi `actor_id` + `passcode` terhadap principal sintetis lokal) + `workspace_memberships` dengan anti-enumeration (`404` untuk workspace tidak dikenal maupun non-member).
- **Compatibility limits:** Default profile memakai local SQLite (`data/marketstudio.db`) untuk data sintetis; menggunakan principal sintetis lokal (belum memakai OAuth/Supabase Auth). Jalur opsional PostgreSQL/Supabase (`MARKETSTUDIO_DB_BACKEND=postgres`, `DATABASE_URL`) dan migrasi versioned tersedia tanpa mengubah default SQLite; lihat [docs/engineering/POSTGRES_SUPABASE.md](docs/engineering/POSTGRES_SUPABASE.md) dan [.env.example](.env.example).
- **Install / Build:** Tidak ada langkah install/build eksternal (cukup Python 3).
- **Run:**
  ```sh
  python3 -m app.server
  ```
  Buka `http://127.0.0.1:8000` di browser.
- **Test:**
  ```sh
  python3 -W error::ResourceWarning -m unittest discover -s tests -v
  python3 scripts/check_repository.py
  ```
