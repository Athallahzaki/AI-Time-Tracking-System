# Serah Terima

Ditulis ulang di akhir setiap sesi. Terakhir: 3 November 2026, sesi overhaul (lintas jalur, tanpa GPU).
Rencana: **`docs/RENCANA-OVERHAUL.md`**. Pilot tetap di `c990bc4`. Semua paket di bawah **belum diuji di 4060/5090**.

## Selesai (kode + tes CPU)

- ea-r16 P4 race `MatrixMatcher` · ea-r17 P2 kegagalan sistem bukan kegagalan wajah (`NOT_ATTEMPTED`).
- be-r2 P1 rate limit login; `AUTH_COOKIE_SECURE` kini benar-benar sampai ke container (`docker-compose.yml`).
- eb-r13 P3 NMS (`detector.nms_iou_threshold`, default mati) · eb-r14 P7(1) pangkas outbox per gugus.
- fe-r1 P5 batas umur kotak (`?boxage=`, default mati) · ea-r18 P6 alasan ReID tidak digabung (log).
- be-r3 P10 enrollment tolak `ANON-`; `onnx` di requirements-dev. Rincian: CHANGELOG 2–3 Nov.
- fe-r2 pengaturan tampilan di `display-config.json` (mount compose; edit + refresh, tanpa build).
- ea-r19 P8(1) klaim wajah lintas kamera (`recognition.cross_camera_claims`, default mati); keputusan tim 3 Nov.
- Dicek: backend memakai `identity_confidence` hanya untuk tampilan (P8 (2)(3) turun prioritas);
  `track.heartbeat` dipakai `free_time.py` untuk `last_seen` -> tetap durabel (pertanyaan terbuka P7 terjawab).

## Belum, dan alasannya

- **[data]** P1 allowlist Traefik VPS; P3 containment; P5 `liveSyncDuration`; P6 tabel waktu tempuh, kalibrasi
  `match_threshold`, penilaian ulang + gabung ANON<->ANON; P7(2) group commit (jenis disk); P8 (2)(3) kalibrasi.
- **[data]** P8: isi `overlapping_cameras` dari pengamatan di lokasi (kosong = tidak ada yang tumpang-tindih).
- **[desain]** Fusi wajah + tubuh + ruang-waktu (sekarang kaskade dengan veto) menunggu pasangan berlabel P6.
- **[keputusan]** P3: `track_threshold` < `confidence_threshold` disengaja atau tidak; delay WebRTC 5,0 vs 8,5.
- **[GPU]** P9 D-FINE ke ONNX. P10 profil YAML berwarisan (besar; kerjakan sebelum P9 menambah profil).
- 6 tes engine gagal sejak sebelum overhaul (profil berubah, tes belum): demo_1060 (2), demo_4060, preflight_demo,
  reid_bucket, reid_embedder. Putuskan profil atau tes yang benar sebelum mengukur apa pun.

## Keputusan yang perlu disetujui

- ea-r16 `MatrixMatcher.snapshot()` publik. ea-r17 default berubah tanpa flag; `recognitions_empty` lebih sempit.
- be-r2 batas 5/username, 20/IP per 5 menit (bisa mengunci akun karyawan 5 menit oleh penebak). eb-r13, fe-r1 default mati.

## Uji manual di 4060 (urut)

1. Baseline `c990bc4` vs paket ini, rekaman sama, 5 kamera: `identify_delays` median/p95, `unidentified_closed`,
   `metric_recognitions_not_attempted`, jumlah track per orang, ANON per jam; `py-spy` 5 menit.
2. Ulangi dengan `detector.nms_iou_threshold: 0.7`; bandingkan track per orang dan ANON per jam.
3. `display-config.json`: `boxes.maxAgeMs: 1000`, lalu `hls.liveSyncDurationSeconds` / `webrtc.playoutDelaySeconds`
   sedikit di atas lag engine; kotak tidak tertinggal. Semua kotak hilang -> cek `clock_drift_seconds`.
4. 6 login gagal ke satu akun -> 429; cookie bertanda Secure di HTTPS. Log `ReID tidak digabung` muncul.
5. `cross_camera_claims: true`, satu orang berjalan antar dua kamera tak tumpang-tindih: tidak ada nama ganda bersamaan.

## Langkah berikutnya

Isi pilot: `AUTH_COOKIE_SECURE=true` + allowlist Traefik -> data §3 -> uji di atas -> putuskan P8 (1) dan P3.
