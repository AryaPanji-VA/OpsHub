# OpsHub Agent

OpsHub Agent adalah agen AI operasional berbasis terminal dengan otonomi
terbatas. Sistem mengubah notulensi atau deskripsi program menjadi rencana dan
tugas terstruktur, memeriksa anggaran serta jadwal, lalu mengusulkan pembuatan
tiket yang tetap memerlukan persetujuan manusia.

Antarmuka utama adalah TUI berbasis Textual dengan branding OpsHub. REPL/CLI
tetap tersedia sebagai fallback. Proyek ini merupakan prototipe lokal, bukan
sistem operasional produksi atau chatbot umum.

## Arsitektur

```text
Notulensi/deskripsi program
  -> LLM menghasilkan OperationalPlan tervalidasi
  -> putaran ReAct-lite memilih aksi terstruktur
  -> Python memvalidasi kebijakan dan menjalankan tool
  -> human-in-the-loop menyetujui/menolak aksi berisiko
  -> tiket lokal + audit sesi
```

Model hanya memilih aksi terstruktur (`action`, `task_id`, `reason`). Python
menentukan argumen, memvalidasi ID tugas, menjalankan tool, dan menegakkan
kebijakan. `RuntimeContext` memisahkan data operasional tepercaya—anggaran dan
entri jadwal—dari isi notulensi dan keputusan model.

Tool yang tersedia:

| Tool | Fungsi | Batas kepercayaan |
| --- | --- | --- |
| `check_budget` | Membandingkan kebutuhan tugas dengan anggaran tersedia | Baca saja; memakai `RuntimeContext` |
| `check_schedule` | Memeriksa tenggat terhadap entri jadwal yang diketahui | Baca saja; bukan kalender lengkap |
| `create_ticket` | Menulis tiket ke JSON lokal | Memerlukan persetujuan manusia per tugas |

Qwen melalui Groq adalah provider utama. Mode `fallback` beralih ke Nex melalui
OpenRouter ketika kegagalan provider dapat ditangani. Provider `mock` tersedia
untuk penggunaan dan pengujian deterministik tanpa jaringan.

Setiap putaran ReAct-lite dibatasi `MAX_AGENT_STEPS=6`. Jika batas tercapai,
hasil pemeriksaan, observasi, approval, dan tiket yang sudah ada dipertahankan.
Perintah `continue`, `resume`, atau `lanjut` memberi maksimal enam langkah baru;
resume tidak menyetujui tiket dan tidak melewati aturan human-in-the-loop.

## Setup

Memerlukan Python 3.11 atau lebih baru.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Untuk dependensi pengembangan dan test:

```powershell
python -m pip install -e ".[dev]"
```

Saat pertama menjalankan `opshub`, layar setup meminta Groq API Key dan secara
opsional OpenRouter API Key. Pilih **Save & Continue**. Tidak perlu membuat
`.env`. Key disimpan di `%APPDATA%\OpsHub\config.env` pada Windows, atau
`$XDG_CONFIG_HOME/OpsHub/config.env` (default `~/.config/OpsHub/config.env`)
pada sistem lain; file ini berada di luar repositori. Jalankan `opshub --setup`
untuk mengganti key yang tersimpan.

Urutan prioritas konfigurasi: variabel lingkungan yang sudah ada, `.env` di
direktori proyek untuk pengembangan, lalu config pengguna. OpenRouter hanya
diaktifkan sebagai fallback bila key-nya tersedia. Untuk pengembangan offline,
salin `.env.example` menjadi `.env` dan gunakan `LLM_PROVIDER=mock`; jangan
commit API key. Variabel lingkungan atau `.env` yang aktif memiliki prioritas
lebih tinggi daripada key yang disimpan melalui `--setup`.

Jika punya akses ke repositori GitHub, alternatif instalasi adalah:

```powershell
python -m pip install git+https://github.com/AryaPanji-VA/OpsHub.git
opshub
```

| Variabel | Keterangan |
| --- | --- |
| `LLM_PROVIDER` | `mock`, `qwen`, `nex`, atau `fallback` |
| `OPSHUB_GATEWAY_URL` | Origin HTTPS gateway reviewer, misalnya `https://contoh.vercel.app`; opsional |
| `GROQ_API_KEY` | API key Groq untuk Qwen |
| `MODEL_NAME` | Nama model Qwen/Groq; opsional untuk override default |
| `OPENROUTER_API_KEY` | API key OpenRouter untuk Nex |
| `OPENROUTER_MODEL` | Nama model Nex/OpenRouter; opsional untuk override default |

## Menjalankan

### Reviewer demo gateway

Reviewer dapat menjalankan OpsHub tanpa memasukkan API key dengan mengatur
`OPSHUB_GATEWAY_URL=https://<gateway-domain>` pada lingkungan lokal mereka.
OpsHub mengirim hanya permintaan `plan` atau `action` ke `POST /api/llm` di
gateway. Gateway memakai model Qwen tetap `qwen/qwen3.8-27b` melalui Groq;
`GROQ_API_KEY` hanya berada di lingkungan server gateway, **bukan** di aplikasi
reviewer. Jika gateway gagal atau mengembalikan respons tidak valid, OpsHub
mencoba provider langsung yang sudah dikonfigurasi. Tanpa key lokal, jalankan
`opshub --setup` untuk memakai layar first-run yang sudah ada. Setup biasa tetap
berlaku bila `OPSHUB_GATEWAY_URL` tidak diisi.

Deploy gateway terpisah di Vercel: buat project dengan **Root Directory**
`gateway`, framework **Other**, lalu set `GROQ_API_KEY` sebagai environment
variable server-side di project gateway. Deploy dan ambil URL deployment
sebagai nilai `OPSHUB_GATEWAY_URL` di mesin reviewer. Jangan masukkan key ke
konfigurasi reviewer atau repository. Endpoint ini publik bagi siapa pun yang
mengetahui URL, jadi batasi kuota Groq dan matikan deployment seusai review;
ini bukan gateway produksi dengan autentikasi atau rate limit per pengguna.


```powershell
opshub                 # TUI utama
opshub --setup         # Atur/ganti API key lokal
python -m opshub       # TUI utama
opshub-cli             # REPL/CLI fallback
python -m opshub.cli   # CLI lama dengan perintah slash
```

## TUI: perintah dan shortcut

Masukkan notulensi/deskripsi program pada input utama. Setelah plan terbentuk,
perintah berikut tersedia:

| Perintah | Fungsi |
| --- | --- |
| `run all` / `semua` | Overview, checks, approval tiket, dan recap |
| `summary` | Ringkasan program |
| `tasks` | Daftar tugas |
| `check all` | Semua pemeriksaan yang relevan |
| `budget` | Pemeriksaan anggaran |
| `schedule` | Pemeriksaan jadwal |
| `schedule add` | Tambah booking sesi dengan format `YYYY-MM-DD \| nama` |
| `tickets` | Tiket yang dibuat pada sesi ini |
| `create tickets` | Jalankan alur agen dan approval tiket |
| `continue` / `resume` / `lanjut` | Lanjutkan workflow yang pause karena step limit |
| `status` | Sisa pemeriksaan, tugas unresolved, tiket, dan next action |
| `new plan` | Mulai input plan baru |
| `help`, `exit` | Bantuan atau keluar |

Saat pemeriksaan anggaran diperlukan, TUI meminta pilihan **runtime data** atau
**manual input**. Jika jadwal runtime kosong, pengguna dapat memasukkan booking
sesi atau mengonfirmasi bahwa tidak ada entri lain yang diketahui.

View `PLAN`, `TASKS`, `ACTIVITY`, dan `TICKETS` dapat di-scroll. Shortcut utama:

| Shortcut | Fungsi |
| --- | --- |
| `Tab` | Buka TASKS |
| `Ctrl+V` | Siklus PLAN/TASKS/ACTIVITY/TICKETS |
| `Ctrl+O` | Fokus output untuk scroll panah/PageUp/PageDown |
| `Ctrl+P` | Tampilkan daftar perintah |
| `Ctrl+L` | Buka ACTIVITY/audit |
| `?` | Bantuan |
| `Esc` | Bersihkan input atau batalkan modal |
| `Ctrl+Q` | Keluar |

CLI lama memakai `/run`, `/plan`, `/log`, `/new`, dan `/exit`.

## Alur demo singkat

1. Jalankan `opshub`, lalu masukkan notulensi yang berisi program, tugas,
   tenggat, PIC/divisi, dan kebutuhan anggaran.
2. Jalankan `run all` atau periksa bertahap dengan `tasks`, `budget`, dan
   `schedule`.
3. Pilih data anggaran runtime atau masukkan nilai manual. Masukkan booking
   jadwal bila diminta.
4. Jalankan `create tickets`; tinjau setiap proposal dan tekan `y` atau `n`.
5. Gunakan `status`, view ACTIVITY, dan `tickets` untuk memeriksa hasil. Jika
   enam langkah habis, gunakan `continue` untuk melanjutkan state yang sama.

Contoh yang lebih lengkap tersedia di [DEMO.md](DEMO.md).

## Pengujian

```powershell
python -m pytest -q
python -m pytest tests/test_phase5_scenarios.py -q
python -m pytest tests/test_resume.py -q
python -m pytest tests/test_tui.py -q
```

Test memakai provider/data sementara untuk menjaga `data/` proyek tidak berubah.

## Audit dan batasan

Audit sesi mencatat antara lain pemilihan aksi, hasil tool, approval, penolakan,
pembuatan tiket, step limit, pause, dan resume. ACTIVITY menampilkan event terbaru
di TUI; `/log` tersedia di CLI lama. Audit hanya disimpan di memori proses.

Batasan saat ini:

- Data anggaran/jadwal masih disimulasikan atau diisi saat runtime dan dapat
  tidak lengkap. Jadwal kosong hanya berarti tidak ada bentrok yang diketahui.
- Tidak ada integrasi kalender nyata, sistem keuangan, atau layanan eksternal.
- Tidak ada rollback atau transaksi otomatis.
- Berkas tiket lokal tidak memiliki proteksi concurrent writer.
- Tidak ada autentikasi, database, frontend web, atau integrasi organisasi.
- State sesi, termasuk plan, observasi, approval, dan audit, tidak bertahan
  setelah aplikasi dimulai ulang.

Lihat [ANALYSIS.md](ANALYSIS.md) untuk ringkasan keputusan desain dan batas MVP.
