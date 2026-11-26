# Development workflow
Idea → discovery → decision → ticket → implementation → test → independent review → owner acceptance → release → maintenance. Atlas mengelola scope, Forge implement, Nexus review. Ticket wajib memuat ID, parent BR/FR/TS/TEST, rationale, scope/non-scope, dependencies, assumptions, acceptance, migration/rollback, risk dan owner approval. Example candidate: BUS-001 purchase batch, FR-BUS-02, TS-BUS-02, TEST-BUS-02; jangan mulai sebelum valuation policy approved. Definition of Done: criteria pass, test evidence, no critical security issue, migration verified, docs updated, review recorded. Jika test tidak dapat dijalankan, status blocked atau partial, bukan done. Release memerlukan smoke, backup/restore plan, access check dan explicit permission. Maintenance mencatat incident, root cause dan regression test.

## Pemeriksaan setiap commit dan pull request

Jalankan `python3 scripts/check_repository.py` untuk memeriksa dokumen inti, metadata skill, file terlarang yang dilacak Git, dan pola kredensial umum. Aktifkan hook sekali per clone dengan `git config --local core.hooksPath .githooks`. Hook memeriksa snapshot staging sebelum commit.

GitHub Actions menjalankan pemeriksaan yang sama pada PR dan push ke `main`. Setelah aplikasi tersedia, hubungkan test runner dan build aplikasi sesuai scope ticket. Pemeriksaan repository dan bukti test aplikasi dicatat terpisah.
