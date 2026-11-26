---
name: marketstudio-issue
description: Mengaudit seluruh dokumentasi MarketStudio untuk menemukan pekerjaan yang belum selesai dan celah produk atau workflow, lalu menulis issue yang konkret dan enak dibaca. Gunakan untuk audit kelengkapan proyek, triase temuan, draft issue, atau pembuatan GitHub issue.
---

# Menulis issue MarketStudio

Jalankan skill ini atas permintaan langsung Product Owner atau dari automation yang ditetapkan Product Owner untuk audit proyek dan pencarian bug. Bot Orca AI Teammate yang bertugas meninjau PR menggunakan `marketstudio-pr-review`.

Anggap setiap temuan sebagai pertanyaan yang bisa diperiksa. Mulai dari hal yang biasa dilakukan orang: menekan Simpan dua kali, kembali setelah koneksi putus, mengoreksi transaksi kemarin, atau membaca angka tanpa tahu periodenya. Cari kapan situasi itu bisa terjadi, siapa yang terdampak, dan keputusan apa yang tersendat. Pakai skenario yang sesuai dengan alur yang sedang diperiksa.

## Audit kelengkapan proyek

1. Inventarisasi dan baca semua dokumen proyek yang tersedia. Ikuti urutan `AGENTS.md`, lalu lanjutkan ke dokumen lain dalam repo, termasuk README, workflow, dokumen lintas studio, referensi discovery, ticket, dan lampiran sumber seperti rulebook. Catat dokumen yang tidak tersedia atau tidak terbaca. Dalam agent loop, hasil baca sebelumnya boleh dipakai untuk dokumen yang isinya sama. Baca dokumen baru dan perubahan sebelum memperbarui kesimpulan.
2. Petakan komitmen, milestone, kriteria penerimaan, dependensi, dan keputusan terbuka ke bukti terkini seperti kode, hasil test, artefak demo, atau issue. Periksa pekerjaan yang belum dimulai, baru sebagian, menunggu dependensi atau keputusan, dan sudah dikerjakan tetapi belum bisa diverifikasi. Tandai klaim yang bertentangan beserta sumbernya. Jika hanya bukti penyelesaiannya yang kurang, nyatakan kondisi itu secara spesifik.
3. Sajikan ringkasan dengan status **Selesai terverifikasi**, **Belum selesai**, **Terblokir**, **Belum terverifikasi**, atau **Usulan**. Untuk tiap pekerjaan yang masih terbuka, sebutkan sumber, bagian yang tersisa, dan dampaknya terhadap milestone. Pertahankan status usulan sampai ada persetujuan. Gunakan milestone dan acceptance criteria yang disetujui untuk menyimpulkan apakah proyek siap dinyatakan selesai.
4. Teruskan pekerjaan yang konkret ke triase issue. Cari issue yang sudah melacaknya. Untuk pekerjaan yang baru separuh selesai, fokuskan draft pada bagian yang masih kurang. Jika dokumennya masih menyisakan keputusan, tulis pertanyaan yang perlu dijawab Product Owner.

## Triase

1. Baca keputusan terbaru di `docs/DECISIONS.md`, aturan yang relevan, serta kode, dokumen, atau test yang mendukung temuan. Cantumkan sumber ekspektasi. Jika aturannya masih draft atau bertentangan, rumuskan keputusan yang dibutuhkan dari Product Owner.
2. Catat kondisi dan hasil yang benar-benar terlihat. Beri status **Terverifikasi** jika bukti menunjukkan perilaku itu, **Perlu verifikasi** jika masih berupa skenario yang masuk akal, atau **Perlu keputusan** jika ekspektasinya belum disepakati. Sebutkan batas bukti. Rekonsiliasi gagal, risiko lintas tenant, dan status publish yang menyesatkan perlu ditangani sesuai dampaknya.
3. Cari issue terbuka dan tertutup dengan kata berbeda untuk gejala dan penyebabnya jika akses tersedia. Tautkan issue yang sudah mencakup temuan. Jika pencarian gagal, sebutkan bahwa duplikasi belum diperiksa. Gabungkan gejala yang punya penyebab dan kriteria selesai yang sama. Pisahkan temuan yang bisa diputuskan atau diperbaiki secara mandiri.
4. Catat temuan kecil dalam ringkasan triase jika dampaknya belum layak menjadi issue sendiri. Simpan hipotesis untuk pemeriksaan berikutnya dengan satu cara verifikasi yang spesifik. Jika input dan bukti sama seperti iterasi sebelumnya, gunakan hasil triase sebelumnya. Akhiri iterasi setelah semua temuan dalam scope ditangani.

## Issue yang bisa dikerjakan agent

Tulis issue untuk backlog AI hanya jika agent dapat menghasilkan artefak atau perubahan yang bisa diperiksa dengan akses dan tool yang tersedia atau setelah dependensi teknis yang disebutkan terpenuhi. Sebutkan output dan cara memverifikasinya. Untuk persetujuan produk, jawaban pihak luar, wawancara lapangan, rekaman video, atau pengumpulan lomba, catat sebagai dependensi manusia. Buat issue tersendiri hanya jika ada pekerjaan persiapan yang konkret untuk agent, seperti matriks keputusan, fixture, prototipe, atau pemeriksaan rilis.

## Tulis untuk orang yang akan membacanya

Gunakan satu issue per hasil kerja yang bisa diterima secara mandiri. Jika satu fitur membutuhkan beberapa hasil seperti verifikasi aturan, pencatatan, dan penayangan laporan, buat issue terpisah dan tautkan urutannya. Pertahankan alur normal dan kasus tepinya di issue yang sama jika keduanya menguji hasil yang sama. Tulis judul pendek, hasil yang diminta, kriteria selesai, batas pekerjaan, dan dokumen atau bagian yang perlu dibaca. Nyatakan dependensi atau keputusan yang harus tersedia sebelum agent mulai.

- Judul menyebut gejala atau keputusan dengan istilah yang dipakai pengguna. Contoh judul: **Satu penjualan bisa tercatat dua kali jika kasir menekan Simpan ulang**.
- Paragraf pertama menjelaskan siapa yang sedang melakukan apa, apa yang terjadi, dan mengapa itu mengganggu pekerjaannya. Gunakan bahasa Indonesia alami dan pertahankan identifier serta istilah teknis Inggris yang membantu.
- Sertakan bukti secukupnya: file dan baris, langkah pemeriksaan biasa, atau hasil test yang benar-benar dijalankan. Gunakan data sintetis bila contoh butuh angka atau identitas.
- Untuk bug, tulis hasil yang diharapkan dan satu kondisi selesai yang bisa diuji. Untuk celah aturan, tulis pertanyaan keputusan dan dampak dari pilihan yang relevan. Tambahkan heading hanya jika membantu pembaca memindai issue.
- Biarkan keputusan prioritas dan implementasi mengikuti otoritas proyek. Untuk mengubah issue menjadi ticket implementasi, gunakan workflow `marketstudio-ticket` dan tautkan issue asal.

## Publikasi dalam agent loop

Saat tugasnya mencari bug atau mengaudit kelengkapan MarketStudio, buat issue yang layak ditindaklanjuti langsung di `IvanoWisnuBudiLaras/MarketStudio`. Instruksi Product Owner untuk peran ini memberi izin publikasi issue tanpa konfirmasi per temuan. Jika tugas secara eksplisit meminta draft, berhenti pada draft.

Sebelum publikasi, pastikan temuan punya sumber, dampak, dan tindakan atau keputusan yang jelas. Periksa duplikasi, termasuk issue yang sudah ditutup. Jika pemeriksaan gagal atau bukti temuan perlu diverifikasi, simpan draft beserta alasannya. Setelah publikasi, verifikasi nomor dan URL issue. Jika hasil create ambigu, cari dulu sebelum mengulang. Izin ini terbatas pada pembuatan issue di repo tersebut.

Untuk dugaan kebocoran secret, PII, atau temuan keamanan sensitif, simpan ringkasan yang sudah disunting di kanal privat dan minta arahan mengenai jalur pelaporan. Jaga detail yang dapat memperluas dampak tetap privat.
