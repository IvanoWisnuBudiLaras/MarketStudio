# Creative Studio — Product Requirements Document
Status PROPOSED; parent BR-06. Tidak menjadi izin implementasi sampai ticket approved.

## Tujuan dan pengguna
Owner membuat draft visual/copy konsisten dengan brand dan offering. Owner adalah decision maker; operator/collaborator hanya sesuai permission. UI harus menjelaskan outcome dan data source, bukan memaksa istilah teknis. Scope awal adalah vertical slice berikut; setiap requirement dapat diprioritaskan ulang oleh Atlas dan owner.

## Functional requirements
| ID | Feature | Requirement | Acceptance ref |
|---|---|---|---|
| FR-CRE-01 | Asset upload | Unggah gambar dengan MIME, size dan permission validation. | TEST-CRE-01 |
| FR-CRE-02 | Draft editor | Edit layer, teks, gambar dan ukuran canvas; simpan version. | TEST-CRE-02 |
| FR-CRE-03 | AI copy | Generate caption dari fakta offering dan tone yang dipilih. | TEST-CRE-03 |
| FR-CRE-04 | Export review | Preview hasil dan ekspor format yang didukung. | TEST-CRE-04 |

## User journey
User masuk workspace, memilih studio, melihat empty state yang menjelaskan langkah pertama, mengisi input yang relevan, melihat preview/validation, menyimpan atau meminta approval, lalu melihat hasil dan audit/status. Jika error, input yang aman dipertahankan dan recovery action ditampilkan. Jangan menampilkan success sebelum server/provider mengonfirmasi. Untuk operasi eksternal, mode demo dan live harus jelas.

## Non-functional requirements
Tenant isolation, keyboard accessibility, responsive layout, explicit loading/empty/error state, auditable write, deterministic calculation jika relevan, dan no secret leakage. Performance target belum disepakati; ukur pada perangkat dan server aktual. Data pelanggan tidak boleh dikirim ke AI tanpa policy. Gunakan shared design system; jangan membuat tema per studio.

## Future / non-scope
Video editor, background removal, image generation dan advanced brand kit setelah biaya/license diperiksa. Tidak ada janji delivery date. Semua integrasi tergantung izin dan compatibility. Acceptance detail ada di ACCEPTANCE_CRITERIA.md; technical candidate di TSD.md. Ukur keberhasilan melalui task completion dan error rate; baseline belum tersedia.
