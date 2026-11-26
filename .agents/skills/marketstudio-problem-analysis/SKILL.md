---
name: marketstudio-problem-analysis
description: Memahami akar masalah MarketStudio, menguji asumsi dan kasus tepi, serta mencari solusi yang tetap benar pada skenario terkait. Gunakan saat menelaah issue, merancang perubahan perilaku, atau memilih solusi untuk masalah yang terlihat sederhana tetapi punya konsekuensi lintas alur.
---

# Memahami masalah sebelum memilih solusi

1. Rekonstruksi alur nyata. Sebutkan pelaku, tujuan, kondisi awal, tindakan, hasil aktual, dan perubahan data yang seharusnya terjadi. Telusuri titik tempat aturan ditegakkan dan pihak yang mengandalkannya. Gunakan issue, dokumentasi, kode, dan bukti yang tersedia. Tandai asumsi dan konflik aturan yang dapat mengubah solusi.
2. Rumuskan kondisi yang harus selalu benar dalam satu kalimat yang dapat diuji. Lalu ubah asumsi satu per satu. Mulai dari perubahan paling kecil yang masuk akal, misalnya aksi diulang, respons datang terlambat, urutan berubah, satu field kosong, atau nilai tepat di ambang pembulatan. Untuk setiap variasi yang relevan, jelaskan kondisi yang berubah, akibatnya, dan bukti atau pemeriksaan yang dapat membedakan dugaan dari masalah nyata.
3. Cari alur lain yang memakai aturan atau sumber data yang sama. Lihat apakah solusi untuk issue ini juga bisa menjaga aturan pada alur tersebut. Bentuk lebih dari satu kandidat jika ada pilihan material, misalnya memperbaiki feedback di UI atau menegakkan aturan pada operasi penyimpanan. Bandingkan berdasarkan kasus yang ditangani, biaya perubahan, dan kemungkinan solusi meleset. Pilih perubahan terkecil yang menutup akar masalah. Pakai mekanisme bersama jika pemakai kedua sudah nyata dan semantiknya sama.
4. Tutup dengan akar masalah, aturan yang harus dijaga, pilihan solusi dan alasannya, serta pemeriksaan untuk alur normal dan satu kondisi yang paling mudah terlewat. Jika ada manfaat di luar issue, sebutkan alur terkait, apa yang bisa dipakai ulang, dan mana yang perlu keputusan scope tersendiri.

Contoh: Kasir menekan Simpan lagi karena layar menunggu respons. Periksa juga kemungkinan transaksi sudah tersimpan tetapi responsnya hilang, sehingga retry terjadi setelah halaman dibuka ulang. Aturan yang perlu dijaga adalah satu upaya pencatatan menghasilkan satu transaksi dan satu pengurangan stok. Cari apakah alur lain memakai operasi pencatatan yang sama sebelum menilai manfaat reuse. Pada pekerjaan review PR, pakai analisis ini untuk menguji klaim perbaikan dalam scope PR dan issue terkait.

Untuk perubahan kecil, cukup beberapa kalimat dan satu pemeriksaan yang bisa membantah asumsi utama. Jika aturan bisnis belum diputuskan dan pilihan itu mengubah hasil pengguna, ajukan keputusan yang spesifik sebelum mengunci desain.
