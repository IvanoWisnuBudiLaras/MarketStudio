# Business Studio — Acceptance criteria kandidat

### TEST-BUS-01 — Offering
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi offering, then Nama kosong ditolak; jasa tanpa recipe diterima; perubahan harga tidak mengubah sale lama.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.

### TEST-BUS-02 — Purchase
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi purchase, then Purchase 500 unit Rp200000 menambah stok 500 dan unit cost 400; COGS tetap nol.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.

### TEST-BUS-03 — Production
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi production, then Stok bahan tidak cukup menolak seluruh transaksi; output menyimpan cost snapshot.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.

### TEST-BUS-04 — Sale
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi sale, then Replay idempotency tidak menggandakan sale; jasa tidak memerlukan stock issue.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.

### TEST-BUS-05 — Waste
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi waste, then Waste 10 unit @450 menghasilkan cost 4500 dan audit; stok tidak negatif.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.

### TEST-BUS-06 — Daily review
Given workspace yang valid dan fixture sesuai requirement, when user menjalankan operasi daily review, then 63*5000=315000; HPP 174500 dan expense 38000 menghasilkan profit 102500; kas terpisah.
Negative path: unauthenticated, wrong tenant, invalid input dan dependency failure tidak boleh menghasilkan perubahan domain tanpa izin. Untuk write, periksa audit dan idempotency; untuk read, periksa permission dan tidak ada side effect.
