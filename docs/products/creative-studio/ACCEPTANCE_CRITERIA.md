# Creative Studio — Acceptance criteria kandidat

### TEST-CRE-01 — Asset upload
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi asset upload, then File unsupported ditolak; asset private tenant tidak bocor.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.

### TEST-CRE-02 — Draft editor
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi draft editor, then Reload mempertahankan draft; undo tidak mengubah source asset.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.

### TEST-CRE-03 — AI copy
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi ai copy, then Tidak mengarang diskon, klaim kesehatan atau harga; user dapat edit.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.

### TEST-CRE-04 — Export review
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi export review, then Asset output sesuai version yang direview; export tidak publish.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.
