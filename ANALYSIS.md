# Analisis OpsHub Agent

## 1. Masalah Utama

Koordinasi operasional sering dimulai dari notulensi rapat yang berbentuk
narasi, lalu tersebar ke chat dan spreadsheet. Informasi penting—tugas, PIC,
divisi, tenggat, kebutuhan anggaran, dan jadwal—mudah terlewat atau tidak sampai
ke pihak yang tepat. Akibatnya, pekerjaan dapat berjalan tanpa pemeriksaan
anggaran/jadwal, kepemilikan tugas menjadi kabur, dan keputusan sulit ditelusuri.

OpsHub ditujukan untuk memperkecil celah tersebut: mengubah narasi menjadi
`OperationalPlan`, menjalankan pemeriksaan operasional yang relevan, dan
membuat handoff berupa tiket. Masalah ini tidak cukup diselesaikan dengan LLM
yang bebas bertindak karena hasil model tetap dapat salah, konteks runtime dapat
tidak lengkap, dan pembuatan tiket merupakan perubahan state. Karena itu,
sistem harus transparan, dibatasi, dan tetap menempatkan manusia sebagai
pengambil keputusan untuk aksi berisiko.

## 2. Keputusan Solusi

OpsHub dibangun sebagai **terminal-native bounded operational AI agent**.
Textual TUI menjadi antarmuka utama dengan branding OpsHub, input notulensi,
pilihan sumber anggaran, approval modal, serta view `PLAN`, `TASKS`, `ACTIVITY`,
dan `TICKETS` yang dapat di-scroll. REPL dan CLI lama dipertahankan sebagai
fallback agar alur tetap dapat digunakan pada terminal sederhana.

Alur inti memakai ReAct-lite. LLM mengekstraksi plan dan memilih aksi
terstruktur (`action`, `task_id`, `reason`), sedangkan Python memvalidasi ID
tugas, menentukan check yang diperlukan, mengambil argumen tepercaya, dan
menjalankan tool `check_budget`, `check_schedule`, atau `create_ticket`.
Pemisahan ini mencegah model mengirim argumen tool bebas atau menyetujui
tiketnya sendiri. Qwen/Groq menjadi provider utama dan Nex/OpenRouter menjadi
fallback; provider mock mendukung demo/test deterministik.

`RuntimeContext` menyimpan anggaran tersedia, entri jadwal, dan sumber masing-
masing data. Di TUI, anggaran dapat dipilih dari data runtime atau dimasukkan
manual. Input tersebut adalah konteks operasional, bukan persetujuan. Jika
jadwal runtime kosong, pengguna dapat menambah booking sesi atau menyatakan
bahwa tidak ada entri lain yang diketahui. Hasilnya tetap hanya merepresentasikan
data yang tersedia, bukan kalender organisasi yang lengkap.

Human-in-the-loop diterapkan pada pembuatan tiket dan keputusan berisiko. Tiap
proposal tiket memerlukan approval per tugas; penolakan tidak membuat tiket.
Pemeriksaan gagal atau konteks penting yang hilang mengalihkan alur ke tinjauan
manusia. `finish` hanya sah ketika checks yang dibutuhkan jelas dan seluruh
tugas actionable sudah ditangani.

Otonomi dibatasi `MAX_AGENT_STEPS=6` per run. Ketika batas tercapai, workflow
menjadi pause, bukan selesai: plan, observasi, hasil check, approval, dan tiket
dipertahankan. `continue`, `resume`, atau `lanjut` memberi maksimal enam langkah
baru pada state yang sama dan tidak melewati aturan approval. Audit sesi mencatat
pemilihan aksi, hasil tool, approval/penolakan, pembuatan tiket, step limit,
pause, resume, kegagalan, dan status akhir yang terkontrol.

## 3. Asumsi & Celah Brief

- Notulensi diasumsikan cukup untuk mengekstraksi sebagian besar struktur
  program, tetapi field yang tidak diketahui seharusnya tetap kosong dan tidak
  dikarang model.
- Data anggaran dan jadwal diasumsikan berasal dari file runtime atau input
  manusia yang dipercaya untuk sesi tersebut. Otoritas, kesegaran, dan
  kelengkapannya belum dapat diverifikasi oleh aplikasi.
- Jadwal kosong berarti tidak ada bentrok yang diketahui; itu bukan bukti
  ketersediaan pada kalender nyata.
- JSON lokal dianggap cukup untuk mendemonstrasikan ticket creation setelah
  approval, tetapi bukan shared state yang aman untuk banyak pengguna.
- Audit di memori cukup untuk transparansi demo, tetapi belum memenuhi kebutuhan
  retensi, kepatuhan, atau investigasi setelah proses berhenti.
- Brief tidak menetapkan identitas pengguna, role, sumber data organisasi,
  aturan eskalasi, SLA, atau definisi aksi berisiko selain ticket creation.
  Implementasi memilih batas konservatif: ketidakjelasan atau check gagal
  berhenti pada human review.
- Pause/resume mempertahankan state hanya selama proses berjalan. Restart
  aplikasi membuat sesi baru karena session persistence belum tersedia.

## 4. Batasan yang Ditetapkan

MVP sengaja dibatasi pada antarmuka terminal, ekstraksi plan, tiga tool lokal,
ReAct-lite, approval manusia, dan audit sesi. Sistem tidak mengklaim memiliki
integrasi kalender nyata, data keuangan langsung, frontend web, autentikasi,
database, atau koneksi ke sistem eksternal/organisasi.

Rollback dan transaksi otomatis tidak diimplementasikan. Berkas tiket lokal
juga belum memiliki locking atau proteksi concurrent writer, sehingga tidak
aman dijadikan penyimpanan produksi. Audit hanya berada di memori, dan state
sesi—plan, konteks runtime, observasi, approval, tiket sesi, serta posisi
workflow—tidak dipersistenkan untuk dipulihkan setelah restart.

OpsHub tidak mengeksekusi pembayaran, membatalkan vendor, menandatangani
kontrak, atau melakukan aksi bisnis berisiko lain. Untuk penggunaan produksi
diperlukan minimal autentikasi dan otorisasi, database/transaksi yang aman,
audit persisten, idempotensi, kontrol konkurensi, integrasi sumber data resmi,
serta strategi kompensasi atau rollback yang eksplisit.
