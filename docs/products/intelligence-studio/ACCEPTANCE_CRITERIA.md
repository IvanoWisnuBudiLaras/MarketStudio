# Intelligence Studio — Acceptance criteria kandidat

### TEST-INT-01 — Metric snapshot
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi metric snapshot, then Data kosong menghasilkan insufficient_data, bukan angka nol palsu.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.

### TEST-INT-02 — AI review
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi ai review, then Angka yang tidak cocok snapshot ditolak/ditandai; output tidak menulis ledger.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.

### TEST-INT-03 — Forecast
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi forecast, then 50,60,70 menghasilkan 60; missing day dibedakan dari zero sales.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.

### TEST-INT-04 — Recommendation
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi recommendation, then User dapat menolak; rekomendasi tidak membuat purchase otomatis.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.
