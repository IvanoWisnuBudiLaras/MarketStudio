# Spreadsheet Studio — Acceptance criteria kandidat

### TEST-SHT-01 — Workbook
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi workbook, then Workspace lain tidak dapat membuka workbook; source period terlihat.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.

### TEST-SHT-02 — Scenario
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi scenario, then Perubahan harga simulasi tidak mengubah offering/sale aktual.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.

### TEST-SHT-03 — Import preview
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi import preview, then Baris invalid terlihat; tidak ada partial commit diam-diam.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.

### TEST-SHT-04 — Export
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi export, then Permission export diperiksa; formula injection dicegah.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.
