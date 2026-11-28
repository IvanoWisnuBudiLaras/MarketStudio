# Development workflow
Idea → discovery → decision → ticket → implementation → test → independent review → owner acceptance → release → maintenance. Atlas mengelola scope, Forge implement, Nexus review. Ticket wajib memuat ID, parent BR/FR/TS/TEST, rationale, scope/non-scope, dependencies, assumptions, acceptance, migration/rollback, risk dan owner approval. Example candidate: BUS-001 purchase batch, FR-BUS-02, TS-BUS-02, TEST-BUS-02; jangan mulai sebelum valuation policy approved. Definition of Done: criteria pass, test evidence, no critical security issue, migration verified, docs updated, review recorded. Jika test tidak dapat dijalankan, status blocked atau partial, bukan done. Release memerlukan smoke, backup/restore plan, access check dan explicit permission. Maintenance mencatat incident, root cause dan regression test.

## Pemeriksaan setiap commit dan pull request

Jalankan `python3 scripts/check_repository.py` untuk memeriksa dokumen inti, metadata skill, file terlarang yang dilacak Git, dan pola kredensial umum. Aktifkan hook sekali per clone dengan `git config --local core.hooksPath .githooks`. Hook memeriksa snapshot staging sebelum commit.

GitHub Actions menjalankan workflow CI (`.github/workflows/ci.yml`) pada PR dan push ke `main` dengan dua job terpisah:
1. `repository-checks`: memeriksa dokumen inti, metadata skill, file terlarang, dan pola kredensial melalui `scripts/check_repository.py`.
2. `build`: membangun paket aplikasi dari clone bersih (`pip wheel` / `pip install`), memverifikasi startup dan impor paket (`app`, `app.server`, `app.service`), serta menjalankan test suite (`unittest discover -s tests`) menggunakan profil default SQLite (live PostgreSQL dilewati di CI tanpa runner eksternal).
