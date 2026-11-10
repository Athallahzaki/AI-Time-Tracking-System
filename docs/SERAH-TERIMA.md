# Serah Terima

Terakhir: 10 November 2026, sesi audit robustness + perbaikan temuan 1–4 (paket be-r6 + ea-r24), tanpa GPU.
Pilot tetap di `c990bc4`. **Paket 2–10 Nov belum diuji di 4060/5090.** Rincian: CHANGELOG 2–10 Nov.

## Selesai (kode + tes CPU; backend 138, engine 847 / 8 dilewati, kontrak 151, semua lulus)

- 10 Nov: atribusi satu transaksi dengan event + galat DB sesaat diputar ulang (1), handshake HMAC backend +
  ACK dipotong ke kursor (2), resolve lewat indeks `person_id` (3), kuota login per (username, IP) (4).
- 2–3 Nov: P1–P8 overhaul, pemicu perubahan kotak, penilaian ulang + gabung ANON, kalibrasi realtime (`set_tuning`).

## Saklar (default mati / perilaku lama)

`detector.nms_iou_threshold`, `analysis_trigger.enabled`, `reid.reevaluate`, `recognition.cross_camera_claims`,
`boxes.maxAgeMs` (tab Kalibrasi). Baru: `ENGINE_SHARED_KEY` (env, kosong = tanpa auth), isi SAMA di kedua mesin.

## Belum, dan alasannya

- **[data]** kalibrasi `reid.match_threshold` sebelum `reevaluate`; tabel waktu tempuh; `overlapping_cameras`.
- **[kontrak]** pesan ANON->ANON. **[desain]** fusi wajah+tubuh+ruang-waktu. **[GPU]** P9 ONNX.
- **[audit, tidak dibaca dalam]** logika ReID (`identity/reid/pending.py`, `merge.py`, klaim lintas kamera).
- **[deploy]** IP klien di belakang Cloudflare: uvicorn mengambil IP paling kanan yang tidak dipercaya di
  X-Forwarded-For, kemungkinan IP edge Cloudflare, bukan IP karyawan. Bila benar, batas per IP dan (username, IP)
  berlaku per edge, bukan per orang. Perbaikan: Traefik `forwardedHeaders.trustedIPs` = rentang Cloudflare, atau
  baca `CF-Connecting-IP`. Konfigurasi Traefik tidak ada di repo; cek dulu (uji manual 2).
- Efek samping SETELAH commit event (`mark_report_dirty`, ledger memori) masih bisa terlewat bila gagal; ledger
  dibangun ulang dari DB saat restart, flag laporan tidak.

## Keputusan yang perlu disetujui

- **Temuan 4 mengubah keputusan P1:** password benar dari IP lain tidak lagi ditolak setelah 5 gagal dari IP
  penyerang. Tebakan terdistribusi ke satu akun kini hanya ditahan batas per IP + panjang password + allowlist.
- EA: `sqlite3.OperationalError` saat ingest = putus + replay (dulu dead letter). DB rusak permanen = backend
  menyambung ulang terus tanpa maju (sengaja: tidak ada yang di-ACK sebelum tersimpan).
- Masih terbuka dari 3 Nov: kontrak `set_tuning`; ea-r17/ea-r21.

## Uji manual (urut)

1. Kunci: buat `python -c "import secrets; print(secrets.token_hex(32))"`, isi di stack backend dan di mesin
   engine. Log engine tanpa peringatan "TANPA autentikasi"; dashboard menerima event. Kosongkan salah satu ->
   log backend menyebut sisi mana yang kurang. Kunci beda -> `auth_failed`.
2. IP klien: login gagal sekali dari HP (data seluler) dan laptop; log backend/uvicorn harus menunjukkan dua IP
   berbeda, bukan IP Cloudflare/VPS. Bila sama -> lihat [deploy] di atas sebelum mengandalkan temuan 4.
3. Kunci DB 15 dtk saat engine mengirim: `docker exec <backend> python -c "import sqlite3,time;
   c=sqlite3.connect('/data/backend.db');c.execute('BEGIN EXCLUSIVE');time.sleep(15)"` -> log "menyambung
   ulang", tidak ada dead letter baru, event setelahnya tetap masuk.
4. Lanjutan dari 3 Nov: baseline `c990bc4` vs paket, Kalibrasi, `reid.reevaluate`, NMS/klaim/boxAge (CHANGELOG).
