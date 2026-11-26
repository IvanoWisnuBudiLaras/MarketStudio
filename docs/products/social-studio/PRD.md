# Social Studio — Product Requirements Document
Status PROPOSED; parent BR-06, BR-07. Tidak menjadi izin implementasi sampai ticket approved.

## Tujuan dan pengguna
Owner menyiapkan campaign dan distribusi konten lintas sosial. Owner adalah decision maker; operator/collaborator hanya sesuai permission. UI harus menjelaskan outcome dan data source, bukan memaksa istilah teknis. Scope awal adalah vertical slice berikut; setiap requirement dapat diprioritaskan ulang oleh Atlas dan owner.

## Functional requirements
| ID | Feature | Requirement | Acceptance ref |
|---|---|---|---|
| FR-SOC-01 | Campaign draft | Pilih tujuan, offering, asset dan kanal; simpan draft. | TEST-SOC-01 |
| FR-SOC-02 | Channel adaptation | Sesuaikan caption, aspect ratio dan media requirement per kanal. | TEST-SOC-02 |
| FR-SOC-03 | Review approval | Preview konten final dan akun tujuan; approve version. | TEST-SOC-03 |
| FR-SOC-04 | Distribution | Enqueue publish hanya jika izin dan approval valid; tampilkan status. | TEST-SOC-04 |

## User journey
User masuk workspace, memilih studio, melihat empty state yang menjelaskan langkah pertama, mengisi input yang relevan, melihat preview/validation, menyimpan atau meminta approval, lalu melihat hasil dan audit/status. Jika error, input yang aman dipertahankan dan recovery action ditampilkan. Jangan menampilkan success sebelum server/provider mengonfirmasi. Untuk operasi eksternal, mode demo dan live harus jelas.

## Non-functional requirements
Tenant isolation, keyboard accessibility, responsive layout, explicit loading/empty/error state, auditable write, deterministic calculation jika relevan, dan no secret leakage. Performance target belum disepakati; ukur pada perangkat dan server aktual. Data pelanggan tidak boleh dikirim ke AI tanpa policy. Gunakan shared design system; jangan membuat tema per studio.

## Future / non-scope
Scheduling, analytics, engagement inbox dan campaign optimization setelah platform policy dan scope lomba jelas. Tidak ada janji delivery date. Semua integrasi tergantung izin dan compatibility. Acceptance detail ada di ACCEPTANCE_CRITERIA.md; technical candidate di TSD.md. Ukur keberhasilan melalui task completion dan error rate; baseline belum tersedia.
