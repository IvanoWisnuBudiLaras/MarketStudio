# Intelligence Studio — Product Requirements Document
Status PROPOSED; parent BR-04, BR-05. Tidak menjadi izin implementasi sampai ticket approved.

## Tujuan dan pengguna
Owner memahami apa yang terjadi, mengapa dan opsi berikutnya. Owner adalah decision maker; operator/collaborator hanya sesuai permission. UI harus menjelaskan outcome dan data source, bukan memaksa istilah teknis. Scope awal adalah vertical slice berikut; setiap requirement dapat diprioritaskan ulang oleh Atlas dan owner.

## Functional requirements
| ID | Feature | Requirement | Acceptance ref |
|---|---|---|---|
| FR-INT-01 | Metric snapshot | Ambil periode dan metric deterministic dari Business Studio. | TEST-INT-01 |
| FR-INT-02 | AI review | Buat review dengan input snapshot, source metric IDs dan limitations. | TEST-INT-02 |
| FR-INT-03 | Forecast | Hitung moving average atau weighted MA dari histori yang memenuhi syarat. | TEST-INT-03 |
| FR-INT-04 | Recommendation | Tampilkan opsi produksi atau restock dengan asumsi dan uncertainty. | TEST-INT-04 |

## User journey
User masuk workspace, memilih studio, melihat empty state yang menjelaskan langkah pertama, mengisi input yang relevan, melihat preview/validation, menyimpan atau meminta approval, lalu melihat hasil dan audit/status. Jika error, input yang aman dipertahankan dan recovery action ditampilkan. Jangan menampilkan success sebelum server/provider mengonfirmasi. Untuk operasi eksternal, mode demo dan live harus jelas.

## Non-functional requirements
Tenant isolation, keyboard accessibility, responsive layout, explicit loading/empty/error state, auditable write, deterministic calculation jika relevan, dan no secret leakage. Performance target belum disepakati; ukur pada perangkat dan server aktual. Data pelanggan tidak boleh dikirim ke AI tanpa policy. Gunakan shared design system; jangan membuat tema per studio.

## Future / non-scope
Health score, growth planner, opportunity discovery, AI chat tools dan model forecasting lebih lanjut. Tidak ada janji delivery date. Semua integrasi tergantung izin dan compatibility. Acceptance detail ada di ACCEPTANCE_CRITERIA.md; technical candidate di TSD.md. Ukur keberhasilan melalui task completion dan error rate; baseline belum tersedia.
