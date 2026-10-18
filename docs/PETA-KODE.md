# Peta Kode

Untuk menemukan file tanpa menjelajah repo. Perbarui saat menambah/memindah modul.
Per 18 Oktober 2026 (paket eb-r12b). Uji ReID di 1060: `docs/UJI-REID-1060.md`.

## Alur data

```text
CCTV/ffmpeg → MediaMTX (RTSP/HLS/WebRTC)
  ├─ engine (laptop): decode → D-FINE → tracker → zona → rekognisi wajah → presence → outbox
  │     └─ TCP NDJSON (contracts/schema) ─→ backend
  └─ browser (HLS/WHEP lewat nginx frontend)
backend (FastAPI + SQLite): event → kunjungan → jatah free time → pelanggaran → email/notifikasi → API/SSE
frontend (Vue + Vite): dashboard, overlay kotak, enrollment, pengaturan
```

## Engine (`engine/`)

| Hal | File |
|---|---|
| Entry point, argumen CLI; fd 2 (stderr C) ke `logs/engine/engine-c-stderr.log` bila ReID+CUDA | `runtime/__main__.py` |
| Rakit kamera, `set_cameras`, health, detector bersama, gerbang detak, error GPU fatal → keluar kode 3 (`_on_camera_fatal`, `core.gpu_fatal_action`), rasio sibuk dispatcher (`_sample_busy_ratio`) | `runtime/service.py` |
| Loop per kamera, event presence, overlay `view.frame` (`_maybe_view`), jeda jadwal analisis `schedule_off` (`_apply_analysis_switch`, `core.analysis_off_mode`) | `runtime/camera.py` |
| Penjadwal berdetak (TickClock, TickGate, kerangka TickScheduler) | `runtime/tick_scheduler.py` |
| Detector dihemat di kamera kosong (`core.idle_fps`, `IdleDetectionGate`; dipasang di `camera.py::_build`, `Engine.detection_gate`) | `runtime/idle_gate.py` (tes `test_idle_gate.py`) |
| Langkah pipeline per frame, decimation PTS | `pipeline/engine.py` |
| Worker rekognisi asinkron | `pipeline/recognition_worker.py` |
| Antrean rekognisi berprioritas zona; `pop` per kamera dari scheduler bersama (ea-r12) | `pipeline/zoning.py` (tes `test_scheduler_lintas_kamera.py`) |
| Scheduler rekognisi: prioritas, kuota per kamera, umur dengan jam bersama (`clock`), `pop(camera_id=)` | `identity/admission.py` (tes `test_admission.py`, `test_scheduler_lintas_kamera.py`) |
| Decode RTSP/file (PyAV, slot frame terbaru, hwaccel), epoch awal dari supervisor (`stream_epoch_base`) | `ingest/pyav_source.py` |
| Mailbox frame terbaru generik | `ingest/mailbox.py` |
| NVDEC (kerangka, menunggu spike) | `ingest/nvdec_source.py` |
| PTS, epoch, offset jam; epoch bertahan saat kamera dibuka ulang (`camera.py::_epoch_announced`, ea-r14) | `ingest/timeline.py` (tes `test_epoch_buka_ulang.py`) |
| D-FINE (LibreYOLO), pra-proses GPU, CUDA graph | `perception/dfine_detector.py` |
| Satu detector untuk semua kamera, batching, berhenti memanggil model sesudah error GPU fatal (`fatal_error`) | `perception/shared_detector.py` |
| Pengenal error CUDA fatal (`is_fatal_gpu_error`, pola teks) | `perception/gpu_fatal.py` (tes `test_gpu_fatal.py`) |
| Tracker | `perception/bytetrack_tracker.py`, `perception/iou_tracker.py` |
| Crop orang/kepala | `perception/person_cropper.py` |
| Wajah (SCRFD + AuraFace ONNX), gerbang kualitas sebelum embedding (`embed_*`, `yaw_ratio`), cek bentuk model SCRFD (`_check_static_size`), TensorRT EP + cache (`recognition_providers`, `tensorrt_options`, `ProviderUnavailable`), potongan kepala (`head_crop`) | `identity/face_onnx.py` (tes `test_rekognisi_beban.py`, `test_tensorrt_rekognisi.py`) |
| Matcher, arbiter identitas, admission, enrollment | `identity/matcher.py`, `identity/arbiter.py`, `identity/admission.py`, `identity/enrollment.py` |
| ReID berjangkar wajah (logika): pesan antrean, galeri harian, aturan gabung, ANON-xxxx | `identity/reid/messages.py`, `identity/reid/gallery.py`, `identity/reid/merge.py`, `identity/reid/pending.py` (tes `test_reid_*.py`) |
| ReID model + gerbang crop (dimuat hanya bila `reid.enabled`): OSNet ONNX, pra-proses = kit latih, SHA-256, `ReidBucketRunner` (satu session per `reid.batch_buckets`) | `identity/reid/embedder_onnx.py`, `identity/reid/quality.py` (tes `test_reid_embedder.py`, `test_reid_bucket.py`) |
| ReID dirakit ke kamera (default mati): koordinator + `identity.resolved`, worker embedding, sisi kamera | `pipeline/reid_coordinator.py`, `pipeline/reid_worker.py`, `pipeline/reid_tap.py` (tes `test_reid_runtime.py`); model di `engine/models/reid/` (di-ignore) |
| Binding track ↔ identitas, interval presence, waktu sampai dikenali (`AssemblerMetrics.identify_delays`) | `presence/binding.py`, `presence/assembler.py` (tes `test_waktu_kenali.py`) |
| Server NDJSON, pembuat event, outbox SQLite | `api/server.py`, `api/events.py`, `api/outbox.py` |
| Referensi wajah tersimpan | `store/references.py` (data: `engine/data/references.sqlite3`, di-ignore) |
| Skema + loader config, profil | `config/schema.py`, `config/loader.py`, `config/*.yaml` (`demo-4060.yaml`, `demo-4060-tick.yaml`, `demo-1060.yaml`; hemat 5 kamera, belum diukur: `demo-1060-hemat.yaml`, `demo-4060-hemat.yaml`) |
| Mematikan power throttling Windows | `runtime/winpower.py` |
| Berkas detak untuk watchdog (`--heartbeat-file`), berkas stop (`--stop-file`) | `runtime/heartbeat.py`, `runtime/service.py` (`_tick_loop`) |
| Engine palsu untuk BE/FE | `tools/fake_engine/` |
| Tes | `engine/tests/test_<topik>.py` |

## Backend (`backend/`)

| Hal | File |
|---|---|
| App, daftar router, startup | `main.py` |
| Config env, database (WAL), keamanan, state | `core/config.py`, `core/database.py`, `core/security.py`, `core/state.py` |
| Aturan ID ANON- (dicadangkan, bukan karyawan): `is_anon_id`, dipakai ledger/pelanggaran/state/skema employee | `core/identity.py` (tes `test_anon_identity_resolved.py`) |
| Router (`/api/...`) | `routers/attendance.py`, `auth.py`, `cameras.py`, `enrollments.py`, `notifications.py`, `settings.py`, `stats.py`, `streams.py` (`/api/detections/*`), `system.py`, `violations.py` |
| Skema Pydantic | `schemas/*.py` (`protocol.py` = pesan engine) |
| Koneksi ke engine, adaptasi protokol, ingest event (termasuk `identity.resolved` -> atribusi `reid_retro`, `_resolve_identity`) | `services/engine_client.py`, `engine_connection_manager.py`, `engine_integration.py`, `protocol_adapter.py`, `event_ingestion.py` |
| Jatah free time (ledger kunjungan) | `services/free_time.py`, `break_policy.py`, `policy_service.py` (`configs/policy.yaml`) |
| Pelanggaran, notifikasi, email | `services/violation_service.py`, `notification_service.py`, `email_service.py` |
| Login/pengguna | `services/auth_service.py` |
| Enrollment | `services/enrollment_service.py` |
| Overlay/statistik deteksi | `services/view_stream.py`, `detection_stats.py` |
| Konfigurasi kamera per mode | `configs/cameras*.yaml` (`remote-hls`, `remote-webrtc` untuk deploy Portainer) |
| Tes | `backend/tests/test_*.py` |

Belum ada (dokumen 12 §3): data master karyawan, manajemen pengguna, pengaturan
dari web (jam istirahat, jadwal engine, penerima/jadwal rekap), rekap harian,
generator `.xlsx`, halaman report, penyaringan per peran di semua endpoint.

## Frontend (`frontend/src/`)

| Hal | File |
|---|---|
| Halaman | `views/DashboardView.vue`, `EnrollmentView.vue`, `SettingsView.vue`, `LoginView.vue` |
| Layout, sidebar, notifikasi | `layouts/DashboardLayout.vue`, `components/layout/*` |
| Video + overlay kotak | `components/dashboard/LiveFeedSection.vue`, `CameraFeedCard.vue`, `DetectionBox.vue`, `composables/useDetectionStream.ts` |
| Data (composable) | `composables/useAuth.ts`, `useNotifications.ts`, `useSettings.ts`, `useEnrollment.ts`, `useEmployeeAllowance.ts`, `useUnidentifiedAlerts.ts` |
| Komponen UI dasar (shadcn-vue, jangan diubah tanpa perlu) | `components/ui/` |

## Kontrak, deploy, skrip

| Hal | File |
|---|---|
| Skema pesan engine ↔ backend, fixture, validator | `contracts/schema/`, `contracts/fixtures/`, `contracts/validator/` |
| Pemeriksa kebijakan di engine | `contracts/tools/policy_grep.py` |
| Compose lokal / Portainer | `deploy/docker-compose.yml`, `deploy/docker-compose.portainer.yml`, `deploy/portainer.env.example` |
| nginx frontend (proxy API, HLS, WHEP) | `deploy/frontend/nginx/` |
| Laptop engine (Windows); watchdog + tugas auto-start (Task Scheduler). Kode keluar engine: 0 berhenti, 1 galat (dinyalakan ulang), 2 config salah (tunggu config diubah), 3 GPU fatal (dinyalakan ulang) | `deploy/laptop/start-engine.ps1`, `start-mediamtx.ps1`, `firewall.ps1`, `engine-watchdog.ps1`, `install-engine-task.ps1` (log di `logs/engine/`, di-ignore) |
| VPS WebRTC | `deploy/vps/nginx-stream-webrtc.conf` |
| Uji lag/gladi, ringkasan (`lag_probe.py --events-out` = rekam event NDJSON untuk validator; kolom `identify_s` = waktu sampai dikenali) | `scripts/lag_probe.py`, `scripts/summarize_gladi.py` |
| Spike NVDEC | `scripts/spike_nvdec.py` |
| Ukur rekognisi per wajah: CUDA vs TensorRT EP, ukuran SCRFD, kosinus embedding (juga mengisi cache TensorRT) | `engine/tools/face_bench.py` |
| SCRFD bentuk tetap 640 -> berdimensi dinamis + verifikasi onnxruntime | `engine/tools/scrfd_dynamic.py` (tes `test_scrfd_dinamis.py`, butuh paket `onnx`) |
| Env kloningan uji TensorRT (Windows) + pemeriksaannya (`check_gpu_env.py --tensorrt`) | `scripts/setup-env-trt.ps1`, `scripts/check_gpu_env.py`, `docs/SETUP-GPU.md` |
| Zip ramping untuk sesi Claude | `scripts/pack_for_claude.py` |
| Kit latih ReID OSNet dari RandPerson (laptop; torch di luar runtime engine) | `tools/reid_train/` — `README.md` (langkah dari nol), `prepare_randperson.py`, `randperson_dataset.py`, `train_osnet.py`, `export_onnx.py`, `eval_reid.py`, `reid_common.py`, `MODEL-CARD.md` (templat; kandidat demo: `MODEL-CARD-osnet-ain-entireid.md`), `requirements-train*.txt`, tes di `tests/` (jalankan terpisah: `python -m pytest tools/reid_train/tests -q`) |

## Dokumen

| Hal | File |
|---|---|
| Aturan untuk Claude | `CLAUDE.md` |
| Status kerja terakhir | `docs/SERAH-TERIMA.md` |
| Serah terima per paket EA (berlaku bersama SERAH-TERIMA.md) | `docs/SERAH-TERIMA-EA-K1.md`, `docs/SERAH-TERIMA-EA-R3.md` |
| Riwayat perubahan (entri teratas cukup) | `docs/CHANGELOG.md` |
| Runbook demo jarak jauh + uji A/B | `docs/DEMO-REMOTE.md` |
| Protokol (rinci) | `docs/ENGINE_PROTOCOL.md` |
