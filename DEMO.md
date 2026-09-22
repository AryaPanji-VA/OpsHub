# Panduan demo 3–5 menit

Jalankan `python -m opshub.cli` dari direktori utama proyek. Untuk demo dengan
model sungguhan, atur `.env` sesuai README.md dan gunakan
`LLM_PROVIDER=fallback`. Model dapat memilih urutan pemeriksaan baca-saja yang
berbeda, jadi alur di bawah adalah pola yang diharapkan, bukan skrip yang
urutan aksinya selalu sama. Tiket yang benar-benar disetujui di CLI ditulis ke
`data/tickets.json`; gunakan pengujian deterministik jika ingin demo tanpa
mengubah data runtime.

## A. Alur aman

Tempel notulensi berikut, lalu ketik `/run` pada baris baru:

```text
Grand Summit 2026 akan dilaksanakan pada 15 Oktober 2026 dengan 400 peserta.
Divisi Logistik harus menyiapkan catering untuk seluruh peserta pada tanggal itu.
Kebutuhan anggaran catering adalah Rp12.000.000.
Divisi Acara harus memastikan jadwal vendor sound system pada 15 Oktober 2026
tidak bentrok dengan acara lain.
PIC masing-masing tugas belum ditetapkan.
```

Pilih input anggaran manual (`2`) dan masukkan `15000000`. Jadwal lokal yang
kosong berarti tidak ada bentrok yang **diketahui**. Jika model mengekstrak
kedua tenggat dengan benar, task_1 memerlukan pemeriksaan anggaran dan jadwal,
sedangkan task_2 memerlukan pemeriksaan jadwal. Setelah pemeriksaan tiap tugas
jelas, agen mengusulkan tiket. Jawab `y` pada masing-masing pertanyaan
persetujuan tiket. Dua tiket yang disetujui dibuat, lalu `finish` dapat
menghasilkan `Next Action: completed`. Gunakan `/log` untuk menunjukkan hasil
pemeriksaan, persetujuan, tiket, dan penyelesaian.

## B. Anggaran kurang dan tinjauan manusia

Ketik `/new`, tempel notulensi yang sama, lalu jalankan lagi. Kali ini
masukkan `10000000` sebagai anggaran tersedia. Pemeriksaan catering senilai
Rp12.000.000 seharusnya gagal. Agen seharusnya menuju `wait_for_human` tanpa
membuat tiket tambahan secara diam-diam. Jangan setujui tiket dalam kasus
terblokir ini. Tampilkan `/log` untuk hasil pemeriksaan gagal dan peristiwa
tinjauan manusia.

Untuk mengulang kedua alur secara offline, bersama kasus bentrok jadwal dan
konteks anggaran yang hilang, jalankan:

```powershell
python -m pytest tests/test_phase5_scenarios.py -q
```

Pengujian terprogram menggunakan berkas sementara dan tidak mengubah `data/`.
