# Spreadsheet Studio — Product Requirements Document
Status PROPOSED; parent BR-05, BR-09. Tidak menjadi izin implementasi sampai ticket approved.

## Tujuan dan pengguna
Owner menganalisis dan menguji skenario tanpa merusak data aktual. Owner adalah decision maker; operator/collaborator hanya sesuai permission. UI harus menjelaskan outcome dan data source, bukan memaksa istilah teknis. Scope awal adalah vertical slice berikut; setiap requirement dapat diprioritaskan ulang oleh Atlas dan owner.

## Functional requirements
| ID | Feature | Requirement | Acceptance ref |
|---|---|---|---|
| FR-SHT-01 | Workbook | Buat workbook dari template analisis atau snapshot read-only. | TEST-SHT-01 |
| FR-SHT-02 | Scenario | Edit harga, volume dan biaya pada salinan skenario. | TEST-SHT-02 |
| FR-SHT-03 | Import preview | Validasi kolom, unit, duplicate dan error sebelum commit. | TEST-SHT-03 |
| FR-SHT-04 | Export | Ekspor data yang diizinkan dengan metadata periode dan actual/simulation. | TEST-SHT-04 |

## User journey
User masuk workspace, memilih studio, melihat empty state yang menjelaskan langkah pertama, mengisi input yang relevan, melihat preview/validation, menyimpan atau meminta approval, lalu melihat hasil dan audit/status. Jika error, input yang aman dipertahankan dan recovery action ditampilkan. Jangan menampilkan success sebelum server/provider mengonfirmasi. Untuk operasi eksternal, mode demo dan live harus jelas.

## Non-functional requirements
Tenant isolation, keyboard accessibility, responsive layout, explicit loading/empty/error state, auditable write, deterministic calculation jika relevan, dan no secret leakage. Performance target belum disepakati; ukur pada perangkat dan server aktual. Data pelanggan tidak boleh dikirim ke AI tanpa policy. Gunakan shared design system; jangan membuat tema per studio.

## Future / non-scope
Real-time collaboration, Office round-trip fidelity dan commercial Univer features setelah license check. Tidak ada janji delivery date. Semua integrasi tergantung izin dan compatibility. Acceptance detail ada di ACCEPTANCE_CRITERIA.md; technical candidate di TSD.md. Ukur keberhasilan melalui task completion dan error rate; baseline belum tersedia.
