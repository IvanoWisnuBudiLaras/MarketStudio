# Business Studio — Product Requirements Document
Status PROPOSED; parent BR-02, BR-03, BR-08. Tidak menjadi izin implementasi sampai ticket approved.

## Tujuan dan pengguna
Owner/operator mencatat operasi dan memahami hasil ekonomi. Owner adalah decision maker; operator/collaborator hanya sesuai permission. UI harus menjelaskan outcome dan data source, bukan memaksa istilah teknis. Scope awal adalah vertical slice berikut; setiap requirement dapat diprioritaskan ulang oleh Atlas dan owner.

## Functional requirements
| ID | Feature | Requirement | Acceptance ref |
|---|---|---|---|
| FR-BUS-01 | Offering | Buat barang atau jasa dengan nama, unit dan harga; capability menentukan field tambahan. | TEST-BUS-01 |
| FR-BUS-02 | Purchase | Catat pembelian batch dengan quantity, total cost dan tanggal; expiry opsional. | TEST-BUS-02 |
| FR-BUS-03 | Production | Pilih recipe version, jumlah output dan batch input; preview cost sebelum commit. | TEST-BUS-03 |
| FR-BUS-04 | Sale | Catat barang/jasa, quantity, harga aktual, discount dan payment status. | TEST-BUS-04 |
| FR-BUS-05 | Waste | Catat batch, quantity dan alasan waste. | TEST-BUS-05 |
| FR-BUS-06 | Daily review | Tampilkan revenue, HPP, expense, profit, cash flow dan ending stock dengan drill-down. | TEST-BUS-06 |

## User journey
User masuk workspace, memilih studio, melihat empty state yang menjelaskan langkah pertama, mengisi input yang relevan, melihat preview/validation, menyimpan atau meminta approval, lalu melihat hasil dan audit/status. Jika error, input yang aman dipertahankan dan recovery action ditampilkan. Jangan menampilkan success sebelum server/provider mengonfirmasi. Untuk operasi eksternal, mode demo dan live harus jelas.

## Non-functional requirements
Tenant isolation, keyboard accessibility, responsive layout, explicit loading/empty/error state, auditable write, deterministic calculation jika relevan, dan no secret leakage. Performance target belum disepakati; ukur pada perangkat dan server aktual. Data pelanggan tidak boleh dikirim ke AI tanpa policy. Gunakan shared design system; jangan membuat tema per studio.

## Future / non-scope
Booking, project costing, rental, subscription, return kompleks dan multi-location setelah policy disepakati. Tidak ada janji delivery date. Semua integrasi tergantung izin dan compatibility. Acceptance detail ada di ACCEPTANCE_CRITERIA.md; technical candidate di TSD.md. Ukur keberhasilan melalui task completion dan error rate; baseline belum tersedia.
