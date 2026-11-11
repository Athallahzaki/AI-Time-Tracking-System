# Serah Terima

Terakhir: 11 November 2026, Paket D + E (ea-r27, deploy-r1), di atas `2bda2d9`, tanpa GPU.
Pilot tetap di `c990bc4`; paket 2–11 Nov belum diuji di 4060/5090. Temuan dan urutan kerja lengkap:
**`docs/ANALISIS-KETAHANAN.md`** (urutan: §7; uji penerimaan: §7a).

## Selesai (engine 851 dgn 8 dilewati, backend 159, kontrak 151; tanpa perubahan kontrak)

- 11 Nov Paket D: biaya sapuan ReID per wajah 101 ms → 1 ms pada 3.200 track; keputusan identik.
- 11 Nov Paket E: `deploy/engine/run-with-watchdog.sh` (engine macet dimatikan supaya Docker menyalakan ulang).
- 11 Nov Paket A/B/C (`2bda2d9`): batas baris kanal; sesi dan akses; matriks akses semua rute.
- 11 Nov (`d8d796c`): uji penerimaan JAT-02/05/07/12/14. 10 Nov (`6751ae2`): audit koreksi, CI.

## Belum

- **[pasang Paket E]** watchdog belum dipakai: compose engine server 5090 tidak ada di repo. Ganti `command`
  engine menjadi `["sh", "deploy/engine/run-with-watchdog.sh", <argumen engine>]` + `restart: unless-stopped`.
- **[insiden]** `cam01b` 404 sejak ±04:00 11 Nov: hop yang putus belum dikonfirmasi (ANALISIS §1).
- **[data, PERTAMA]** tabel waktu tempuh kosong + default 30 dtk = pindah ruangan < 30 dtk selalu ANON baru.
- **[uji penerimaan, bukan kode]** MON-04 config, MON-07 kacamata/IR, JAT-04 tafsir, JAT-10 risiko `visit_id`.
- Paket F (debug Fase 1), G (kondisi gambar), H (debug Fase 2, kontrak).
- Temuan 3 (token di `localStorage`), 4 (kunci kanal), 8 (timing login); autentikasi MediaMTX; `pip-audit`/`npm audit`.

## Perubahan perilaku saat deploy (dari Paket B)

`BACKEND_API_KEY` yang sudah terisi kini benar-benar diperiksa di `/api/*`; ganti/reset password mencabut sesi
lain; akun berpassword sementara mendapat 403 sampai password diganti.

## Keputusan yang perlu disetujui

- Engine menolak start tanpa `ENGINE_SHARED_KEY` di alamat non-loopback; autentikasi MediaMTX; kontrak `debug.*`.
- Tafsir JAT-04; ekspektasi MON-07 kacamata; klien diberi tahu waktu ANON tidak ditagih.
- Dari 3–10 Nov: kontrak `set_tuning`; ea-r17/ea-r21; kuota login per (username, IP).
- Batas dari Zena: Traefik, Cloudflare, ACL NetBird tidak diubah.

## Uji manual (urut)

1. **ReID di GPU (Paket D):** jalankan rekaman yang sama sebelum dan sesudah; jumlah ANON, `cocok galeri`, dan
   `selesai` di log engine harus sama. Keputusan tidak boleh berubah, hanya lebih cepat.
2. **Watchdog di Docker (Paket E):** pasang di compose, lalu `docker pause` TIDAK menguji ini (seluruh container
   beku); uji dengan `docker exec <engine> kill -STOP <pid python>` → container restart dalam ±65 dtk.
3. nginx setelah redeploy frontend: video WHEP/HLS tampil; `/docs` menampilkan dashboard, bukan Swagger.
4. Akun baru: login → dipaksa ganti password → dashboard terbuka tanpa login ulang; ganti password di satu
   browser melempar browser lain ke halaman login.
5. Uji penerimaan JAT, insiden, MediaMTX: CHANGELOG 11 Nov dan ANALISIS §1, §2.1, §7a.
6. Redeploy: backend dulu, lalu frontend; `ENGINE_SHARED_KEY` kosong sampai engine ikut; GitOps Portainer mati.
