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

Jangan menjalankan semua roadmap sekaligus. Baca ticket yang disetujui dan dependency relevan. Jangan menimpa repo lokal tanpa diff. Tidak ada source aplikasi, API key atau instalasi MCP di paket ini.

## Runnable Baseline (Issue #5)

- **Stack:** Python 3 standard library (`http.server`, `sqlite3`, `unittest`) modular monolith (`app/`), single browser entry point (`GET /` -> `app/web/index.html`), dan local SQLite storage (`data/marketstudio.db`). Tanpa dependency eksternal sehingga langsung berjalan dari clean clone.
- **Compatibility limits:** Single-node local SQLite untuk data sintetis; otorisasi lintas-tenant menggunakan header `X-Workspace-Id` (belum memakai OAuth/Supabase Auth); siap dimigrasi ke FastAPI + PostgreSQL pada milestone berikutnya.
- **Install / Build:** Tidak ada langkah install/build eksternal (cukup Python 3).
- **Run:**
  ```sh
  python3 -m app.server
  ```
  Buka `http://127.0.0.1:8000` di browser.
- **Test:**
  ```sh
  python3 -m unittest discover -s tests -v
  python3 scripts/check_repository.py
  ```
