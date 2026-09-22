# OpsHub Agent

OpsHub Agent mengubah notulensi rapat mentah menjadi rencana operasional,
memeriksa anggaran dan jadwal, lalu mengusulkan tiket untuk disetujui manusia.
Proyek ini menangani koordinasi yang tersebar di chat, notulensi, dan spreadsheet:
penanggung jawab, batas anggaran, dan tenggat sering tidak sampai ke divisi yang
tepat.

Prototipe berbasis terminal ini menampilkan aksi yang diusulkan model, hasil
pemeriksaan Python, dan keputusan persetujuan selama demo lokal.

## Arsitektur dan batas kepercayaan

```text
Notulensi mentah -> ekstraksi terstruktur oleh LLM -> OperationalPlan dan tugas
                 -> pemilihan aksi ReAct-lite (maksimal 6 langkah per putaran)
                 -> ToolDispatcher Python dan pemeriksaan per tugas
                 -> kebijakan / persetujuan manusia -> tiket lokal -> selesai
```

Model memilih **aksi apa** yang diusulkan dengan skema tepat
`{action, task_id, reason}`. Python menentukan **cara menjalankannya** dan
**apakah aksi itu diizinkan**. Python memvalidasi ID tugas, menentukan
pemeriksaan yang diperlukan dari data tiap tugas, dan mengambil argumen tool
dari rencana serta konteks runtime yang tepercaya. Model tidak dapat mengirim
argumen tool sembarang atau menyetujui tiketnya sendiri.

| Tool | Fungsi | Batasan |
| --- | --- | --- |
| `check_budget` | Membandingkan kebutuhan tugas dengan anggaran tersedia | Hanya baca |
| `check_schedule` | Membandingkan tenggat tugas dengan entri jadwal yang diketahui | Hanya baca |
| `create_ticket` | Menulis tugas yang disetujui ke JSON lokal | Perlu persetujuan manusia untuk tugas tersebut |

`create_ticket` adalah operasi Python setelah persetujuan, bukan aksi bebas
yang dapat dijalankan LLM. Berkas JSON di `data/` menyimulasikan sumber data
operasional.

## Instalasi

Gunakan Python 3.11 atau lebih baru. Jalankan dari direktori utama proyek di
PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
opshub
```

Untuk menjalankan pengujian, pasang juga dependensi pengembangan dengan
`python -m pip install -e ".[dev]"`.

## Menjalankan aplikasi dan memilih model

Jalankan `opshub` atau `python -m opshub`. CLI lama tetap tersedia melalui
`python -m opshub.cli`. Secara bawaan, `LLM_PROVIDER=mock` bersifat
deterministik dan tidak memerlukan API key. Pada antarmuka baru, tempel
notulensi dan tekan Enter pada **baris kosong** untuk membuat rencana. Setelah
prompt `opshub>` muncul, gunakan perintah berikut:

| Perintah | Hasil |
| --- | --- |
| `summary`, `tasks` | Ringkasan program dan daftar tugas |
| `check all`, `budget`, `schedule` | Pemeriksaan baca-saja yang sesuai |
| `tickets`, `create tickets` | Tiket sesi ini dan alur usulan dengan persetujuan manusia |
| `new plan`, `new program`, `ganti plan` | Masukkan notulensi baru dalam beberapa baris; baris kosong mengakhiri masukan |
| `status`, `help`, `exit` | Status, bantuan, dan keluar |

Alias sederhana juga tersedia, misalnya `show tasks`, `recap`, `cek budget`,
`cek jadwal`, `buat ticket`, dan `keluar`. Narasi rapat atau program dapat
dimasukkan langsung di `opshub>`. Jika sudah ada rencana, OpsHub meminta
konfirmasi sebelum menggantinya. Rencana baru memakai alur ekstraksi yang sama;
anggaran, jadwal, hasil pemeriksaan, dan persetujuan sesi lama direset. Perintah
di luar koordinasi operasional ditolak tanpa dikirim ke model. Antarmuka ini
bukan chatbot umum.
CLI lama masih menerima `/run`, `/log`, `/new`, `/plan`, dan `/exit`.

Pilihan provider adalah `mock`, `qwen` (Qwen melalui Groq), `nex` (Nex melalui
OpenRouter), dan `fallback` (Qwen/Groq utama, Nex/OpenRouter cadangan). Salin
`.env.example` menjadi `.env`, lalu isi `GROQ_API_KEY` dan/atau
`OPENROUTER_API_KEY` milik Anda. Gunakan `LLM_PROVIDER=fallback` untuk
peralihan otomatis. `MODEL_NAME` dan `OPENROUTER_MODEL` dapat mengganti nama
model bawaan. Git mengabaikan `.env`.

Tool Python lokal dan endpoint model yang kompatibel dengan paket gratis
memungkinkan prototipe berjalan tanpa layanan berbayar. Ketersediaan dan batas
paket gratis tetap bergantung pada provider. Kegagalan provider yang dapat
ditangani akan menghentikan alur dengan aman.

## Demo dan pengujian

Lihat [DEMO.md](DEMO.md) untuk demo Grand Summit selama 3–5 menit: kebutuhan
catering Rp12.000.000, tanggal 15 Oktober 2026, pemeriksaan jadwal sound system,
dan anggaran tersedia Rp15.000.000. Model dapat memilih urutan pemeriksaan
baca-saja yang berbeda. Notulensi di `samples/grand_summit.txt` adalah contoh
konferensi lain dengan nominal dolar; gunakan notulensi di DEMO.md untuk contoh
rupiah.

Jalankan seluruh pengujian atau ulangi empat skenario deterministik Tahap 5:

```powershell
python -m pytest -q
python -m pytest tests/test_phase5_scenarios.py -q
```

| Skenario | Masukan deterministik | Hasil yang diharapkan |
| --- | --- | --- |
| Alur aman | Anggaran Rp15.000.000; jadwal kosong; setujui dua usulan | Dua tiket dibuat, lalu `finish` |
| Anggaran kurang | Anggaran Rp10.000.000 | Pemeriksaan gagal, tinjauan manusia, tanpa tiket baru |
| Jadwal bentrok | Ada acara lain pada 2026-12-01 | Pemeriksaan gagal, tinjauan manusia, tanpa tiket baru |
| Konteks penting hilang | Tidak ada nilai anggaran atau berkas anggaran | Observasi `missing_context`, tinjauan manusia, tanpa tiket baru |

Skenario otomatis memakai berkas sementara dan tidak mengubah `data/`.

Contoh singkat setelah rencana terbentuk:

```text
opshub> summary
opshub> tasks
opshub> check all
opshub> status
opshub> create tickets
Create ticket for task_1? [y/N]
opshub> tickets
opshub> exit
```

## Keamanan dan keterbatasan

Pydantic menolak aksi yang tidak dikenal serta field yang kurang atau
berlebihan. Tiket memerlukan persetujuan manusia terpisah untuk tiap tugas.
`finish` hanya diterima setelah semua pemeriksaan yang diperlukan jelas dan
semua tugas yang perlu ditangani sudah memiliki tiket. Pengulangan `finish`
yang tidak valid dihentikan lebih awal; alur lain yang belum selesai mencapai
batas `MAX_AGENT_STEPS=6` sebelum meminta tinjauan manusia. Memasukkan angka
anggaran bukan persetujuan tiket.

Perintah `check all` menampilkan hasil pemeriksaan baca-saja; `create tickets`
menjalankan putaran ReAct-lite yang sudah ada sehingga pemeriksaan tersebut
dapat dijalankan kembali sebelum usulan tiket. Perintah `tickets` menampilkan
tiket yang dibuat pada sesi ini. REPL baru belum menyediakan `/log`; audit
lengkap masih dapat dilihat melalui `/log` di CLI lama.

Jadwal kosong berarti **tidak ada bentrok yang diketahui**, bukan bukti
kalender lengkap. Sistem keuangan dan kalender masih berupa simulasi atau
masukan runtime. Audit `/log` hanya ada di memori proses dan hilang saat
aplikasi ditutup. Berkas tiket lokal belum melindungi penulisan bersamaan dan
rollback transaksi otomatis belum tersedia. Prototipe ini tidak memiliki
frontend, database, autentikasi, integrasi sistem organisasi, eksekusi
pembayaran, pembatalan vendor, atau penandatanganan kontrak.

## Struktur proyek

```text
opshub/
  cli.py             Interaksi terminal
  repl.py            Perutean perintah interaktif terbatas
  __main__.py        Titik masuk python -m opshub
  agent.py           Putaran ReAct-lite, dispatch, persetujuan, audit
  models.py          Model rencana, tugas, aksi, dan observasi tervalidasi
  checks.py          Kebutuhan dan status pemeriksaan per tugas
  policy.py          Pembantu kebijakan
  llm/               Provider Qwen, Nex, mock, dan fallback
  tools/             Fungsi anggaran, jadwal, dan tiket lokal
tests/               Pengujian unit, regresi, dan skenario Tahap 5
samples/             Contoh notulensi
data/                JSON runtime simulasi yang dikendalikan pengguna
```

Lihat [ANALYSIS.md](ANALYSIS.md) untuk alasan desain, asumsi, serta batas
pelacakan dan rollback.
