# Perubahan — 23 September 2026 (build 2026.09.23-audit-fixes)

Perbaikan atas audit `claude/audit-masalah-2026-09-23.md`. Keputusan yang dipakai:

- **Jatah 30 menit = waktu terlihat di ruang fasilitas**, logika bisnis di backend.
- Detector: LibreYOLO D-FINE **m** (default) atau **s** (`--model s`).
- Recognizer wajah: slot terpasang, **mati secara default**, dinyalakan lewat config.

## Kanal event (tidak ada event yang hilang diam-diam)

| ID | Perbaikan | File |
|---|---|---|
| K1 | Engine asli memakai `SqliteOutbox` (`engine/data/outbox.sqlite3`, `--outbox`). `hello_ack` membawa `outbox_id`; backend menyimpan kursor per outbox dan menyambung ulang dengan kursor yang benar bila outbox berganti. Event disimpan dengan kunci `(outbox_id, seq)`. | `engine/runtime/*`, `engine/api/outbox.py`, `backend/services/engine_client.py`, `backend/core/database.py` |
| K2 | Pengiriman event berbasis kursor ke outbox (tidak ada antrian yang bisa "ambil lalu buang"). Koneksi + kursor dipasang atomik saat handshake. Backend mendeteksi lubang `seq` dan meminta replay (maks. 3x, lalu dicatat). | `engine/api/server.py`, `backend/services/engine_client.py` |
| T4 | `close()` mematikan socket sebelum menutup reader — tidak lagi deadlock. | `backend/services/engine_client.py` |
| T5 | Pesan beracun masuk `dead_letters` + di-ACK; stream jalan terus. View/kontrol yang rusak tidak memutus koneksi. `GET /api/system/dead-letters`. | `engine_client.py`, `routers/system.py` |
| T6 | Satu kunci tulis untuk semua penulisan socket engine. | `engine/api/server.py` |
| baru | `track_uuid`/`interval_id` diberi nonce per run: tidak lagi didaur ulang setelah restart engine/kamera. | `engine/runtime/camera.py`, `engine/presence/binding.py` |

## Jatah free time

| ID | Perbaikan |
|---|---|
| K3 | Hitungan "gap = istirahat" dihapus (`session_deriver.py`). Satu model: hadir di ruang fasilitas. |
| K4 | `backend/services/free_time.py`: ledger dari event durabel (`presence.interval` + track terbuka dari `track.*`), union lintas kamera, penggabungan oklusi (`visit_merge_gap_seconds`), pengaman engine mati (`open_presence_stale_seconds`), dibangun ulang dari DB saat backend start. Overlay mengambil angka dari ledger. |
| T1 | Query interval difilter per tanggal di SQL (bukan 1000 baris tertua). |
| T2 | Interval tumpang-tindih tidak lagi melempar error; digabung. |
| S3 | Jam istirahat resmi menghormati menit, bisa lebih dari satu (`official_breaks`). Satu aturan status untuk semua endpoint. |
| S4 | Koreksi HR disimpan di tabel `corrections` dan **diterapkan**: kecualikan satu kunjungan atau tambah/kurangi menit. Audit log bertahan restart. |
| S5 | Event tidak lagi disimpan dua kali. |

## Kamera, config, keamanan

| ID | Perbaikan |
|---|---|
| T3 | `door_region` dari `cameras.yaml` dikirim ke engine. Kontrak: `door_region` kini opsional (sebelumnya wajib tapi tidak pernah dikirim). |
| T7 | Kamera yang gagal dibuka ulang dengan backoff 5→60 dtk sampai dihapus dari `set_cameras`. Stream jaringan yang berakhir = `camera_lost`, bukan `engine_shutdown`. |
| T8 | `cameras.yaml` rusak = backend gagal start dengan pesan jelas (dulu: `{}` → engine menutup semua kamera). |
| T9 | Start/stop/sumber dari operator disimpan di SQLite; satu fungsi `set_cameras_message()` untuk API dan reconnect. |
| T10 | SQLite: WAL, `busy_timeout`, `foreign_keys`, koneksi ditutup. View frame ditulis thread terpisah (tidak menahan kanal event), retensi `DETECTION_RETENTION_DAYS` (default 7). |
| T11 | Engine menjawab `enroll` dengan `enroll_result` (ber-`request_id`). Re-enroll menaikkan `enrollment_version`. `GET /api/enrollments/requests/{id}`; frontend menampilkan hasil. Roster dikirim ulang setelah enrollment diterima. |
| T12 | `BACKEND_API_KEY` opsional untuk semua endpoint yang mengubah data; ganti sumber kamera hanya ke `allowed_sources`. **Autentikasi pengguna (siapa HR-nya) masih belum ada.** |
| S1 | Kode mati (`engine_worker.py`, `camera_manager.py`, `engine_service.py`) dihapus. Tes batas proses ditambahkan (`backend/tests/test_boundary.py`). |
| S2 | SSE tanpa thread per klien; default kamera = kamera pertama di config. |
| S6 | `person.unidentified_present` memakai jam PTS. |
| baru | `backend/.gitignore` meng-ignore folder `tests/` — tes backend tidak pernah masuk repo. Diperbaiki. |

## Engine B / model

- `scripts/run_demo.py --model m|s` (atau `AI_TIME_DFINE`). `dfine-s.yaml` kini `device: auto` seperti `dfine-m.yaml`.
- Slot recognizer: `engine/identity/face_onnx.py` (SCRFD + AuraFace via onnxruntime), config `recognition.recognizer: none|onnx_face`. Enrollment memakai `EnrollmentPolicy` milik Engine A yang sudah ada. Dependency: `engine/requirements-face.txt`.

## Verifikasi

- 384 tes lulus (contracts 76, engine 279, backend 29), 2 skip (butuh lingkungan tanpa torch). Tes dijalankan dengan shim pytest/fastapi karena PyPI diblokir di lingkungan build; **jalankan ulang `python -m pytest -q` di mesin kalian.**
- `scripts/integration_smoke.py` (engine asli 3 kamera ↔ klien backend) lulus semua.
- **Frontend belum di-build** (npm diblokir di lingkungan build). Perubahan FE kecil (form koreksi, hasil enrollment, label panel, header proxy) — jalankan `npm run build`.
- Recognizer ONNX **belum diuji dengan model sungguhan** (model tidak tersedia). Jalur enrollment diuji dengan stub.
