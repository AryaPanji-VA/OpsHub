# Analisis Pengumpulan: OpsHub Agent

## 1. Masalah utama dan akar penyebab

Rencana operasional sering bermula dari cerita dalam rapat, lalu tersebar ke
chat, notulensi, dan spreadsheet. Sebuah tugas bisa tidak memiliki penanggung
jawab yang jelas. Batas anggaran dapat tertahan di divisi Keuangan, sedangkan
tenggat tidak sampai ke divisi yang menghubungi vendor. Informasi yang tidak
tersampaikan antardivisi menyebabkan pekerjaan ganda, kepemilikan tugas yang
kabur, dan keputusan operasional sebelum anggaran atau jadwal diperiksa. Akar
masalahnya adalah koordinasi yang terpecah dan sulit ditelusuri.

OpsHub Agent adalah prototipe magang yang membuat tugas dan batasan tersebut
lebih eksplisit, memeriksanya dengan data yang tersedia, lalu meminta keputusan
manusia sebelum membuat tiket. Ini bukan sistem operasional perusahaan yang
siap dipakai untuk produksi.

## 2. Keputusan solusi dan alasan arsitektur

Antarmuka terminal dipilih agar aksi, hasil, dan persetujuan mudah diamati serta
cepat dijalankan secara lokal. Putaran ReAct-lite memberi ruang bagi model
untuk memilih urutan aksi tanpa memerlukan framework agen yang berat. Keluaran
terstruktur dan validasi Pydantic membatasi bentuk data dari model. Python
menjalankan tool secara deterministik: model mengusulkan **apa** yang dilakukan,
sedangkan Python menentukan **bagaimana** dan **apakah** aksi boleh dilakukan.

`LLMProvider` mengekstrak `OperationalPlan` dari notulensi dan memilih
`AgentActionModel` yang hanya berisi `action`, `task_id`, dan `reason`. Model
tidak dapat memberikan argumen tool bebas atau menulis tiket. Python memeriksa
ID tugas, menentukan kebutuhan pemeriksaan dari data tugas tersebut, lalu
menjalankan pemeriksaan anggaran dan jadwal dengan konteks runtime yang
tepercaya. Usulan pembuatan tiket saja tidak menulis apa pun: tiap tiket
memerlukan persetujuan manusia yang terpisah. `finish` hanya diterima ketika
pemeriksaan yang diperlukan jelas dan semua tugas yang perlu ditangani sudah
memiliki tiket.

Setiap pemanggilan putaran agen dibatasi enam langkah agar aksi keliru tidak
terus menghabiskan token. Jika tidak selesai, status menjadi `wait_for_human`;
pengulangan `finish` yang tidak valid dapat dihentikan lebih awal. Konteks
ringkas per tugas menunjukkan pemeriksaan yang sudah jelas dan yang masih
kurang sehingga model tidak perlu mengulang pemeriksaan yang sama.

Qwen melalui Groq adalah provider utama dan Nex melalui OpenRouter menjadi
cadangan saat terjadi kegagalan provider yang dapat ditangani. Kegagalan saat
ekstraksi rencana atau pemilihan aksi tidak mengizinkan pembuatan tiket.
Provider mock dan skenario terprogram membuat alur inti dapat diuji tanpa
jaringan. Arsitektur ini tidak mewajibkan layanan berbayar, tetapi ketersediaan
dan batas paket gratis berada di luar kendali proyek.

Anggaran dan jadwal dapat berasal dari berkas JSON simulasi atau masukan
eksplisit selama sesi. Konteks operasional ini dipisahkan dari isi notulensi
dan dari persetujuan: memasukkan anggaran bukan izin membuat tiket. Jadwal
kosong menghasilkan kesimpulan tidak ada bentrok yang **diketahui**, bukan
bukti bahwa seluruh kalender sudah lengkap.

## 3. Asumsi dan celah dalam brief

- Sumber keuangan dan kalender masih disimulasikan atau diberikan saat
  aplikasi berjalan; otoritas serta kesegaran datanya belum dijamin.
- Divisi, PIC, anggaran, atau tenggat bisa tidak disebut dalam notulensi.
  Nilai yang tidak diketahui dibiarkan kosong, bukan dikarang model.
- Konteks penting yang hilang mengarah ke tinjauan manusia. Pada CLI,
  pengguna diminta memasukkan anggaran jika dibutuhkan.
- Rencana dan aksi dari model divalidasi sebelum Python menjalankan tool.
  Skema yang valid saja tidak berarti sebuah tiket boleh dibuat.
- JSON lokal cukup untuk menunjukkan penulisan setelah persetujuan, tetapi
  belum menyediakan state bersama atau perlindungan penulis bersamaan.

## 4. Lingkup yang sengaja tidak dibuat

Prototipe ini tidak mengeksekusi pembayaran, membatalkan vendor,
menandatangani kontrak, mengintegrasikan kalender penuh atau sistem akuntansi,
menyediakan frontend, menyimpan audit perusahaan secara persisten, ataupun
menjalankan rollback otomatis. Autentikasi dan database juga berada di luar
lingkup MVP. Tindakan berisiko dan keputusan atas sistem organisasi tetap
dikendalikan manusia; proyek ini tidak mengklaim akses ke sistem tersebut.

## 5. Keterlacakan dan rollback

Selama proses berjalan, audit di memori mencatat pemilihan aksi model,
observasi dan hasil tool, aksi tidak valid, permintaan tinjauan manusia,
keputusan persetujuan, pembuatan tiket, serta status akhir yang terkontrol.
Perintah `/log` pada CLI lama menampilkannya; REPL baru menampilkan ringkasan
melalui `status` dan `tickets`. Pengujian skenario memverifikasi bahwa alur
aman membuat dua tiket yang disetujui, sedangkan alur yang terblokir tidak
membuat tiket baru. Audit hilang saat CLI ditutup; ini belum menjadi catatan
kepatuhan yang tahan lama.

Rollback transaksi otomatis **belum diimplementasikan**. Berkas tiket lokal
juga belum aman untuk beberapa penulis bersamaan. Untuk pemulihan manual saat
demo, manusia dapat memeriksa audit dan memulihkan salinan berkas tiket yang
diketahui baik setelah memastikan tidak ada penulis lain yang mengubahnya.
Pengembangan untuk produksi membutuhkan audit persisten, penulisan idempoten,
kontrol akses, serta prosedur kompensasi atau rollback yang jelas.
