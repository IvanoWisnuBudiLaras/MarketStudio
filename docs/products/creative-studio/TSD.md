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

## Draft caption Issue #16

Di Creative Studio, pilih produk atau jasa, gaya bahasa, serta aset berizin untuk draft baru. **Buat draft dengan AI** menyimpan draft awal dan membuka editor. **Tulis manual** membuka draft kosong untuk caption. Perubahan copy singkat dan caption dapat langsung dilihat di pratinjau teks. **Simpan draft** menyimpan versi baru. **Salin caption** menyalin teks yang terlihat pada editor.

`POST /v1/workspaces/{workspace_id}/creative-drafts/caption` menerima `offering_id`, `asset_id`, `tone` (`friendly` atau `direct`), dan `mode` (`ai` atau `manual`). Klien mengirim `Idempotency-Key` saat membuat draft. Nama, kategori offering, deskripsi opsional, satuan dan harga jual diambil dari katalog workspace. Provider Gemini memakai konfigurasi dan transport JSON Business Review. Permintaan provider hanya membawa kategori, gaya bahasa, dan pilihan ID pola kalimat. Aplikasi menyisipkan fakta katalog secara lokal setelah memvalidasi ID tersebut. Jika provider gagal atau mengirim keluaran di luar pilihan, pembuatan draft AI tidak mengubah data dan editor tetap tersedia.

Provenance draft menyimpan fakta sumber, versi prompt, gaya bahasa, waktu pembuatan, mode provider, dan versi edit terakhir. Gunakan `PATCH /creative-drafts/{draft_id}` relatif terhadap workspace dengan `expected_version` untuk menyimpan perubahan. Draft menggunakan versi dan ekspor poster #42. Pratinjau katalog #48 dapat menerima `copy_draft: {draft_id, version}` untuk salah satu offering terpilih. Snapshot katalog memuat caption yang dipilih dan masih memerlukan tindakan terbit terpisah oleh pemilik.

SQLite menambahkan kolom `offerings.description` saat startup. Offering lama tetap dapat menghasilkan caption dengan deskripsi kosong. PostgreSQL menambahkan kolom kompatibel lewat migrasi `0003`. Alur Creative Studio mengikuti ketersediaan SQLite dari #42/#48. Rollback aplikasi lokal dapat mempertahankan kolom dan semua draft.

Jalankan `CHROMIUM_PATH=/usr/bin/chromium node scripts/check_ai_copy.cjs /tmp/marketstudio-copy-evidence` dengan Playwright yang tersedia di jalur modul Node. Skrip memakai data sintetis SQLite, membuka Chromium headless pada 390 dan 1440 px, serta menguji mode `stub_valid`, timeout, dan kegagalan provider.
