# Commerce Studio — Acceptance criteria kandidat

### TEST-COM-01 — Channel connect
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi channel connect, then Token tidak muncul di browser/log; expired token meminta reconnect.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.

### TEST-COM-02 — Listing mapping
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi listing mapping, then Missing field menghalangi publish; jasa unsupported diberi alasan.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.

### TEST-COM-03 — Approval
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi approval, then Edit setelah approval membatalkan approval lama.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.

### TEST-COM-04 — Publish status
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi publish status, then Satu channel gagal tidak menyatakan semua sukses; demo tidak berlabel live.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.
