# Serah Terima

Terakhir: 11 November 2026, Paket A + B + C (ea-r26, be-r9..r11), di atas `d8d796c`, tanpa GPU.
Pilot tetap di `c990bc4`; paket 2–11 Nov belum diuji di 4060/5090. Temuan dan urutan kerja lengkap:
**`docs/ANALISIS-KETAHANAN.md`** (urutan: §7; uji penerimaan: §7a).

## Selesai (engine 849 dgn 8 dilewati, backend 159, kontrak 151; tanpa perubahan kontrak)

- 11 Nov Paket A: batas ukuran baris di kanal engine↔backend; pesan cacat tidak lagi mematikan thread pembaca.
- 11 Nov Paket B: `must_change_password` ditegakkan server; ganti/reset password mencabut sesi lama; viewer tidak
  melihat `source_uri` dan status email; `/docs` tidak diteruskan nginx; `BACKEND_API_KEY` benar-benar diperiksa.
- 11 Nov Paket C: `test_matriks_akses.py` (semua rute, otomatis dari OpenAPI).
- 11 Nov (`d8d796c`): uji penerimaan JAT-02/05/07/12/14. 10 Nov (`6751ae2`): audit koreksi, CI backend + frontend.

## Perubahan perilaku yang perlu diketahui saat deploy

- Bila `BACKEND_API_KEY` sudah diisi di `stack.env`: `/api/*` kini menolak request tanpa `X-API-Key` (nginx dan
  proxy Vite mengirimnya; skrip langsung ke port 8000 harus ikut). Kosong = seperti sebelumnya.
- Ganti/reset password mengeluarkan pengguna itu dari perangkat lain.
- Akun berpassword sementara mendapat 403 di semua API sampai password diganti.

## Belum

- **[insiden]** `cam01b` 404 sejak ±04:00 11 Nov: hop yang putus belum dikonfirmasi (ANALISIS §1).
- **[data, PERTAMA]** tabel waktu tempuh kosong + default 30 dtk = pindah ruangan < 30 dtk selalu ANON baru.
- **[uji penerimaan, bukan kode]** MON-04 config, MON-07 kacamata/IR, JAT-04 tafsir, JAT-10 risiko `visit_id`.
- Paket D (biaya `_sweep_groups`), E (watchdog Docker), F (debug Fase 1), G (kondisi gambar), H (debug Fase 2).
- Temuan 3 (token di `localStorage`), 4 (kunci kanal), 8 (timing login); autentikasi MediaMTX; `pip-audit`/`npm audit`.

## Keputusan yang perlu disetujui

- Engine menolak start tanpa `ENGINE_SHARED_KEY` di alamat non-loopback; autentikasi MediaMTX; kontrak `debug.*`.
- Tafsir JAT-04; ekspektasi MON-07 kacamata; klien diberi tahu waktu ANON tidak ditagih.
- Dari 3–10 Nov: kontrak `set_tuning`; ea-r17/ea-r21; kuota login per (username, IP).
- Batas dari Zena: Traefik, Cloudflare, ACL NetBird tidak diubah.

## Uji manual (urut)

1. **nginx (belum teruji di cloud):** setelah redeploy frontend, video WHEP/HLS masih tampil (subrequest
   `/_video_auth` kini membawa `X-API-Key`); `https://<dashboard>/docs` menampilkan dashboard, bukan Swagger.
2. Akun baru dari "Buat akun": login → dipaksa ganti password → setelah ganti, dashboard terbuka tanpa login ulang.
3. Login di dua browser, ganti password di satu → browser lain terlempar ke halaman login.
4. Viewer: dashboard kamera tetap tampil (tanpa `source_uri`); admin: ganti sumber kamera masih bisa.
5. Uji penerimaan JAT dan langkah insiden/MediaMTX: lihat CHANGELOG 11 Nov dan ANALISIS §1, §2.1, §7a.
6. Redeploy: backend dulu, lalu frontend; `ENGINE_SHARED_KEY` kosong sampai engine ikut; GitOps Portainer mati.
