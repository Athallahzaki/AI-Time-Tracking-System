# Serah Terima

Terakhir: 3 November 2026 (siang), sesi overhaul lintas jalur, tanpa GPU. Rencana: `docs/RENCANA-OVERHAUL.md`.
Pilot tetap di `c990bc4`. **Semua paket belum diuji di 4060/5090.** Rincian: CHANGELOG 2–3 Nov.

## Selesai (kode + tes CPU; engine 834 lulus / 0 gagal, kontrak 151, backend 128)

- P1 rate limit login, `AUTH_COOKIE_SECURE` sampai ke container, X-Forwarded-For hanya dari proxy (be-r2, be-r4).
- P2 kegagalan sistem bukan kegagalan wajah (ea-r17) · P4 race matcher (ea-r16) · P8(1) klaim lintas kamera (ea-r19).
- P3 NMS (eb-r13) · P5 umur kotak + `display-config.json` (fe-r1/r2) · P6 alasan ReID (ea-r18) · P7(1) outbox (eb-r14).
- Metrik identitas di `engine.health` (ea-r20) · 6 tes merah diselaraskan dengan profil lapangan (ea-r21).
- Pemicu analisis berbasis perubahan kotak (eb-r15) · penilaian ulang + gabung ANON (ea-r22).
- Kalibrasi realtime tanpa restart: kontrak `set_tuning`, engine, backend, tab Kalibrasi (ea-r23, be-r5, fe-r3).

## Saklar (semua default mati / perilaku lama)

`detector.nms_iou_threshold`, `analysis_trigger.enabled`, `reid.reevaluate`, `recognition.cross_camera_claims`,
`boxes.maxAgeMs`. Semuanya kini bisa dinyalakan dari tab Kalibrasi tanpa restart.

## Belum, dan alasannya

- **[data]** kalibrasi `reid.match_threshold` (eval_reid.py) SEBELUM `reevaluate` dinyalakan; tabel waktu tempuh;
  `overlapping_cameras`; containment P3; `liveSyncDuration`; jenis disk (P7 group commit); py-spy 5 kamera (GIL).
- **[kontrak]** pesan ANON->ANON: tanpa itu laporan menampilkan dua ANON sampai wajah menyelesaikannya.
- **[desain]** fusi wajah+tubuh+ruang-waktu (menunggu pasangan berlabel). **[GPU]** P9 ONNX.
- `track_threshold` dan tracker lain: butuh restart (ByteTrack LibreYOLO tidak diverifikasi aman diubah saat jalan).

## Keputusan yang perlu disetujui EA

- Kontrak: `set_tuning` + `ack.effective_tuning` + `engine.health.identity_metrics` (aditif, pesan lama utuh).
- ea-r17 default berubah tanpa saklar. ea-r21: tes mengikuti profil lapangan (profil = kebenaran).

## Uji manual di 4060 (urut; nyalakan saklar satu per satu)

1. Baseline `c990bc4` vs paket ini, saklar mati, rekaman sama 5 kamera: `identify_delays`, ANON/jam, lag, py-spy.
2. Tab Kalibrasi: ubah `analysis_trigger.enabled` -> log `set_tuning diterapkan`; `trigger_skipped_face` naik di
   health; orang diam tidak dicoba terus, orang bergerak dikenali.
3. `reid.reevaluate` setelah kalibrasi: orang pindah ruangan -> log `digabung ke`; wajah -> dua `identity.resolved`.
4. NMS 0,7, `cross_camera_claims` + pasangan kamera, `boxes.maxAgeMs` 1000: lihat CHANGELOG masing-masing.
5. Engine dimatikan-dinyalakan: kalibrasi dari dashboard otomatis diterapkan lagi.
