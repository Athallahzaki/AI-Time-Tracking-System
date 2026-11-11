# Serah Terima

Terakhir: 11 November 2026, paket be-r8 + fe-r5 (uji penerimaan klien), di atas `6751ae2`, tanpa GPU.
Pilot tetap di `c990bc4`; paket 2–11 Nov belum diuji di 4060/5090. Temuan dan urutan kerja lengkap:
**`docs/ANALISIS-KETAHANAN.md`** (uji penerimaan: §7a).

## Selesai (backend 148 lulus, build frontend lulus; engine dan kontrak tidak disentuh)

- 11 Nov (be-r8/fe-r5): JAT-02 `counts_free_time` per kamera, JAT-12 jatah per karyawan, JAT-07 pengecualian
  karyawan per lokasi, JAT-05 notifikasi peringatan dini sekali per hari, JAT-14 nama di notifikasi/email.
- 11 Nov: analisis ketahanan (dokumen saja).
- 10 Nov (`6751ae2`): `corrected_by` dari sesi admin, CI backend + frontend, temuan audit 1–4.

## Saklar / konfigurasi baru (default = perilaku lama)

`counts_free_time: false` per kamera di `cameras.yaml`; jatah per karyawan dan pengecualian lewat form karyawan.
Migrasi DB otomatis saat backend start (kolom `employees.allowance_minutes`, tabel `free_time_exemptions`).

## Belum

- **[insiden]** `cam01b` 404 sejak ±04:00 11 Nov: hop yang putus belum dikonfirmasi (ANALISIS §1).
- **[uji penerimaan, bukan kode]** MON-04 config, MON-07 kacamata/IR, JAT-04 tafsir, JAT-10 risiko `visit_id` (§7a).
- **[data, PERTAMA]** tabel waktu tempuh kosong + default 30 dtk = pindah ruangan < 30 dtk selalu ANON baru.
- Paket A–H (ANALISIS §7), sesudah uji penerimaan beres.

## Keputusan yang perlu disetujui

- Tafsir JAT-04 (20 dtk pertama gratis); ekspektasi MON-07 kacamata; klien diberi tahu waktu ANON tidak ditagih.
- Peringatan dini tidak di-email (hanya lonceng). Ubah bila klien menginginkan email.
- Engine menolak start tanpa `ENGINE_SHARED_KEY` di alamat non-loopback; autentikasi MediaMTX; kontrak `debug.*`.
- Dari 3–10 Nov: kontrak `set_tuning`; ea-r17/ea-r21; kuota login per (username, IP).
- Batas dari Zena: Traefik, Cloudflare, ACL NetBird tidak diubah.

## Uji manual (urut)

1. JAT-02: tambah `counts_free_time: false` pada kamera lobby/luar, restart backend; kunjungan di sana tampil
   tetapi pemakaian tidak bertambah.
2. JAT-12: dua karyawan jatah 30 dan 60 menit di form karyawan; 35 menit di lokasi → hanya yang pertama melanggar.
3. JAT-07: catat pemakaian, tambah pengecualian di form karyawan, kunjungan berikutnya tidak menambah pemakaian;
   kunjungan sebelum pengecualian tetap ditagih.
4. JAT-05/14: satu notifikasi "Jatah waktu hampir habis" di lonceng; email pelanggaran menyebut nama karyawan.
5. MON-04: isi `boxes.maxAgeMs` di tab Kalibrasi dulu.
6. Insiden dan MediaMTX: langkah `curl` di ANALISIS §1 dan §2.1.
7. Redeploy: backend dulu, lalu frontend; `ENGINE_SHARED_KEY` kosong sampai engine ikut; GitOps Portainer mati.
