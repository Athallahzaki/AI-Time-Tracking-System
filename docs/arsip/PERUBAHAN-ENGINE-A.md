# Perubahan Engine A — 1 Oktober 2026

Kumulatif dari build `2026.09.23-audit-fixes`. Ekstrak di root proyek (timpa).
Verifikasi: 407 tes contracts+engine lulus, integration smoke lulus, policy_grep bersih.

## 1. Koneksi engine tahan gangguan (D8, P2)
- Handshake di thread sendiri + batas 5 dtk untuk `hello`: klien diam tidak lagi menahan backend.
- Baris pertama bukan JSON tidak lagi mematikan loop accept engine.
- Koneksi lama diputus sebelum handshake mengambil kunci tulis: backend baru tidak menunggu backend macet.
- Keepalive TCP + batas waktu kirim 15 dtk (SO_SNDTIMEO, ada cabang Windows).
- Berkas: `engine/api/server.py`, `engine/tests/test_api_connection.py`

## 2. Config recognizer
- Nama model `models/glintr100.onnx`; field baru `face_detector_input_size` (default 640, kelipatan 32).
- Berkas: `engine/config/*`, `engine/identity/face_onnx.py`, `README.md`, `engine/tests/test_recognizer_slot.py`

## 3. Pembekuan skema protokol fase 1 (tambahan, protocol_version tetap 1)
- `auth_challenge`, `hello.auth`, `hello_ack.auth` (HMAC-SHA256) — P3.
- `ack` dua bentuk; ACK event backend (`through_seq`) akhirnya tercantum, `ts` wajib — P12.
- `engine.health.camera_metrics`, `outbox_depth`, `disk_free_mb`; peta `cameras` dibekukan.
- `camera.degraded.kind/since_at/lag_seconds`, event baru `camera.recovered`.
- `enroll_from_track` (+ alasan `track_unavailable`), `forget_person` → `forget_result`.
- Berkas: `contracts/schema/…`, `contracts/handshake_auth.py`, `contracts/tests/test_protocol_phase1.py`, `contracts/README.md`, `docs/ENGINE_PROTOCOL.md` §8

## 4. Implementasi engine dari kontrak fase 1
- Handshake HMAC di engine asli dan fake engine; kunci dari env `ENGINE_SHARED_KEY`.
- `forget_person` dengan penghapusan sungguhan: `secure_delete` + checkpoint WAL (foto wajah sebelumnya masih bisa dibaca dari berkas setelah "dihapus").
- `engine.health` membawa `outbox_depth`, `disk_free_mb`.
- Fake engine: `forget_person`, `enroll_from_track`, tidak lagi membalas ACK backend dengan "tidak dikenal".
- Dockerfile fake engine menyalin `contracts/handshake_auth.py`.
- Berkas: `engine/runtime/*`, `engine/store/references.py`, `engine/api/events.py`, `engine/tools/fake_engine/*`, `deploy/fake-engine/*`, `.env.example`, `engine/tests/test_engine_phase1.py`

## Belum
- `enroll_from_track` di engine asli (cache crop wajah per track) — Engine A berikutnya.
- `camera_metrics`, `camera.degraded.kind`, `camera.recovered` — Engine B (ingest).
- Seluruh sisi backend: klien auth, `forget_result`, ACK dengan `ts`.
