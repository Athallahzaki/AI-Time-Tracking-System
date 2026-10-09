# Lag kamera terukur + alat uji delay — 2 Oktober 2026

Di atas zip Engine B "stream live dan detector". Ekstrak di root proyek (timpa).
Verifikasi: 437 tes contracts+engine lulus tanpa peringatan, integration smoke lulus, policy_grep bersih.

## 1. Engine melapor sendiri saat tertinggal (P17, kontrak fase 1)
- Sebelumnya `camera.degraded` ada di skema tapi engine asli tidak pernah memancarkannya.
- `engine/runtime/lag.py` (baru): lag = PTS terbaru yang di-decode - PTS yang dianalisis; histeresis
  masuk >= 1,0 dtk selama 5 dtk, keluar <= 0,5 dtk selama 5 dtk.
- Supervisor kamera memancarkan `camera.degraded` (kind `lag`, `since_at`, `lag_seconds`) dan
  `camera.recovered`; reconnect mereset pemantau.
- `engine.health.camera_metrics`: `lag_seconds`, `effective_fps`, `frames_dropped_stale`.
- Peta `engine.health.cameras` sekarang `degraded` saat rentang lag terbuka (sebelumnya tetap `online`).
- CLI engine: `--health-seconds` (default 30) untuk uji.
- Berkas: `engine/runtime/{lag,camera,service,__main__}.py`, `engine/api/{events,__init__}.py`,
  `contracts/schema/...` (hanya teks deskripsi `frames_dropped_stale`).

## 2. Sentuhan kecil di folder Engine B (mohon diketahui Engine B)
- `engine/ingest/pyav_source.py`: dua properti baca-saja, `latest_decoded` (epoch, pts) dan
  `frames_replaced`. Tidak mengubah perilaku ingest.

## 3. Alat uji teori delay
- `scripts/lag_probe.py`: pengganti backend sementara; mencatat umur kotak + lag per kamera ke CSV
  dan menyimpulkan BERTAMBAH (engine, P17) / SEGAR (cari di frontend, P10/P16) / TETAP besar (P18),
  atau TIDAK VALID bila `at` di masa depan. Mendukung handshake HMAC (`ENGINE_SHARED_KEY`).
- `scripts/publish_test_video.ps1` / `.sh`: video uji -> MediaMTX tanpa B-frame, keyframe tiap 1 dtk.
- `docs/UJI-LAG.md`: langkah uji A/B (live_buffer latest vs none) + jalur lengkap dashboard.

## 4. Lain-lain
- `engine/tests/test_recognizer_slot.py`: perbaikan ResourceWarning (berkas config tidak ditutup).
- Tes baru: `engine/tests/test_lag_monitor.py` (9), `engine/tests/test_lag_probe.py` (4).

## Belum
- Koreksi offset frame pertama (P18) dan sinkronisasi kotak di frontend (P10/P16).
- Pilihan profil tracker untuk demo (`dfine-m` masih IoU; P8 hanya aktif di `dfine-m-bytetrack`).
