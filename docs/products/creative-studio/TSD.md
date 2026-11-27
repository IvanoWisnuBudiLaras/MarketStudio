# Creative Studio — Technical Specification
Status PROPOSED. Mengikuti global TSD dan AGENTS; endpoint adalah candidate, bukan implementasi.

## Domain dan ownership
Entity kandidat: Asset, BrandKit, CreativeDraft, DraftVersion. Setiap entity scoped workspace, memiliki opaque ID dan timestamp; mutable draft memakai version untuk optimistic concurrency. Authoritative data lintas studio diakses melalui service contract, bukan copy ledger. Jangan membuat database per studio. Validate membership, permission dan input di server. Financial quantity/cost mengikuti docs/platform/BUSINESS_RULES.md.

## API mapping
| Technical ID | Method/path relatif workspace | Entity | Requirement |
|---|---|---|---|
| TS-CRE-01 | POST /assets | Asset | FR-CRE-01 |
| TS-CRE-02 | POST /creative-drafts | CreativeDraft | FR-CRE-02 |
| TS-CRE-03 | POST /creative-drafts/{id}/copy | DraftVersion | FR-CRE-03 |
| TS-CRE-04 | POST /creative-drafts/{id}/export | Asset | FR-CRE-04 |

## Transaction dan state
Write request membawa idempotency key jika operasi berisiko duplicate; server membandingkan payload hash dan menolak mismatch. Atomic commit untuk perubahan domain terkait. Draft: draft → reviewed/approved → queued (bila eksternal) → processing → succeeded/failed/unknown; tidak semua entity memerlukan seluruh state. Approval terikat version dan target. External success hanya berdasarkan provider evidence; timeout dengan unknown outcome membutuhkan reconciliation. Read-only metric/simulation tidak mengubah source.

## Failure dan security
422 invalid input; 403 permission; 409 version/idempotency conflict; 503 dependency unavailable. Jangan leak tenant existence atau secret. Retry bounded hanya pada operasi aman. Audit menyimpan actor, workspace, operation, entity, version, request ID dan outcome; redact payload sensitif. Upload menggunakan allowlist dan size limit yang ditetapkan sebelum implementasi. Test cross-tenant, duplicate, rollback dan failure injection.

## Implementation order
Contract tests dan schema migration terlebih dahulu, service logic, API, UI states, integration tests, independent review. Jangan menambah library tanpa spike. Acceptance criteria adalah test design, bukan hasil test. Open: exact schema, limits, retention, dependency versions dan provider access. Atlas harus menyelesaikan open question yang memblokir ticket sebelum Forge coding.

## Baseline lokal Issue #42

Di Creative Studio, pilih profil usaha, buat atau pilih draft contoh, pilih aset dan format, tampilkan pratinjau, lalu unduh. Aset contoh PNG memiliki atribusi, lisensi CC0-1.0, dan SHA-256 di registry lokal. Draft menyimpan referensi offering opsional, teks, dan provenance copy serta aset untuk integrasi #16 dan #47.

`POST /v1/workspaces/{workspace_id}/creative-drafts/{draft_id}/preview` mengembalikan gambar, versi, dan SHA-256 untuk format yang dipilih. Kirim kembali `format`, `expected_version`, dan `preview_sha256` ke `POST .../export` untuk mengunduh byte yang sama. Perubahan versi, format, atau hasil render memerlukan pratinjau ulang. Preview dan export tercatat di audit, dengan status poster tetap `draft` dan ledger tetap sama.

Inisialisasi SQLite membuat tabel `creative_assets` dan `poster_drafts` secara aditif. Pada konfigurasi PostgreSQL, endpoint poster memeriksa akses workspace dan mengembalikan `poster_backend_unavailable` kepada anggota. Untuk rollback lokal, jalankan kembali versi aplikasi sebelumnya dengan basis data yang sama. Kedua tabel dapat dipertahankan agar pekerjaan poster tersedia saat fitur dipulihkan.
