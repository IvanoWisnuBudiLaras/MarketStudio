# Social Studio — Acceptance criteria kandidat

### TEST-SOC-01 — Campaign draft
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi campaign draft, then Draft tidak mengirim konten; source asset version tercatat.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.

### TEST-SOC-02 — Channel adaptation
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi channel adaptation, then Unsupported media diberi validation error; user dapat edit.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.

### TEST-SOC-03 — Review approval
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi review approval, then Perubahan caption/asset/target membatalkan approval.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.

### TEST-SOC-04 — Distribution
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi distribution, then Unknown outcome tidak retry buta; partial failure dapat ditangani per kanal.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.
