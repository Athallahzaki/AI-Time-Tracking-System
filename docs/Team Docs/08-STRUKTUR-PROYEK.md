# 08 — Struktur Proyek

Versi 1.2 · diperbarui 9 Oktober 2026 · lihat dokumen 12 (kesepakatan) dan 13 (daftar pembaruan)

Mengikuti `PROJECT STRUCTURE.md` v1.2 (19 Sep 2026) sebagai rencana yang sudah disepakati, dengan pembaruan untuk kondisi kode saat ini dan kebutuhan fase 1. Prinsipnya tetap: satu folder, satu mekanisme, satu pemilik; batas folder mencerminkan batas proses; kontrak adalah warga kelas satu di root.

## 1. Root

Struktur sasaran (dokumen 12 §10.3):

```
.
├── README.md      # Pintu masuk + indeks dokumen
├── .gitattributes # *.sh text eol=lf + penanda biner (paket r8; * text=auto ditunda)
├── .gitignore  .env.example  pytest.ini  requirements-dev.txt
├── engine/        # Pengamatan: kamera → identitas → event. Tanpa aturan perusahaan
├── backend/       # Kebijakan: event → kunjungan → jatah → peringatan → API
├── frontend/      # Tampilan: dashboard, enrollment, koreksi, laporan, admin
├── contracts/     # Skema protokol, fixture, validator, pemeriksa batas
├── bench/         # DATA benchmark: gonogo.yaml, baseline, anotasi (kode ada di engine/bench)
├── deploy/        # Compose (lokal dan Portainer), nginx, MediaMTX, skrip laptop, VPS, env contoh
├── scripts/       # Skrip pengembang: demo, smoke test, run tests, lag probe, ringkasan gladi
└── docs/          # Dokumen acuan (sumber kebenaran; Project hanya salinan)
    ├── CHANGELOG.md   # Satu changelog untuk semua paket, terbaru di atas
    ├── ARCHITECTURE.md  ENGINE_PROTOCOL.md  PROJECT_STRUCTURE.md  WORKPLAN.md
    ├── DEMO-1060.md  DEMO-REMOTE.md  SETUP-GPU.md  UJI-LAG.md
    └── arsip/         # Catatan perubahan lama yang disimpan apa adanya
```

Perubahan dari kondisi sekarang (per 8 Oktober 2026 root berisi ±30 file `.md`, 28 di antaranya catatan perubahan):

- Semua catatan perubahan (`PERUBAHAN-*.md`, `PERBAIKAN-*.md`, `CHANGES.md`, `CHANGES_TIMER_BACKEND.md`, dan `docs/CHANGES_TIMER_BACKEND_2026-09-22.md`) digabung ke **`docs/CHANGELOG.md`** (urut tanggal). File aslinya dipindah ke `docs/arsip/` dengan `git mv`. Dua versi catatan timer backend yang isinya berbeda disatukan. Changelog **tidak** lagi di root.
- `WORKPLAN_STATUS.md` dan `PACKAGE_VERSION.txt` (status/build 23 September) dihapus atau diperbarui; status terkini ada di dokumen 12 dan tabel target.
- `.gitattributes` ditambahkan, lalu `git add --renormalize .` agar `.sh` kembali LF.
- `README.md` root ditambah indeks dokumen.
- Pemindahan dan penghapusan dilakukan lewat skrip `git mv`/`git rm`, karena paket zip tidak bisa memindahkan atau menghapus file.

Status 9 Oktober 2026: **dikerjakan di paket r8**. 31 file dipindah ke `docs/arsip/` (28 catatan perubahan, dua dokumen status basi, catatan timer 22 September) lewat skrip sekali jalan; `.gitignore` root ditambah bobot model (`*.pt`, `*.onnx`, ...) dan database SQLite karena `model_path` relatif ke root. `* text=auto` ditunda (dokumen 12 §10.3).

## 2. Engine (direstruktur terbatas, dokumen 04 §14)

```
engine/
├── ports/        # Antarmuka abstrak [BERSAMA EA/EB]; Frame dapat membawa data di GPU (rencana)
├── ingest/       # PyAV, PTS, epoch, reconnect, koreksi drift; mailbox frame terbaru (r9), NVDEC (rencana)
├── perception/   # Detector D-FINE, tracker ByteTrack/IoU, crop
├── identity/     # Recognizer ONNX, matcher, arbiter, admission, enrollment
├── presence/     # Binding track↔identitas, assembler interval, zona
├── api/          # Server NDJSON, event, outbox
├── pipeline/     # Loop frame, worker rekognisi asinkron (baru) [BERSAMA]
├── runtime/      # Layanan multi-kamera, state per kamera, penjadwal berdetak (r9), entry point
├── store/        # Referensi wajah (terenkripsi, fase 1)
├── streams/      # (tentukan pemilik dan tujuan dalam satu kalimat)
├── config/       # Loader + skema config; profil dfine-{n,s,m}.yaml, demo-1060.yaml, demo-4060.yaml
├── bench/        # Harness benchmark (kode)
├── tools/        # fake_engine, overlay, probe_ingest
└── tests/
```

Pembagian folder engine tetap. Yang berubah per 9 Oktober 2026 adalah **cara menjalankannya** (dokumen 12 §3.9, dokumen 04 §14): ritme dipegang `runtime/tick_scheduler.py`, tiap kamera hanya men-decode ke `ingest/mailbox.py`, dan `runtime/camera.py` menjadi state per kamera tanpa thread sendiri. Kerangkanya ada di paket r9 dengan default mati. Catatan dokumen lain: harness benchmark ada di `engine/bench/` (bukan `engine/tools/bench/`), dan `engine/streams/` perlu dicatat tujuannya.

**ReID (masuk prototype, dokumen 12 §3.6).** Usulan lokasi: **`engine/identity/reid/`** (galeri harian, aturan penggabungan, identitas tertunda, model dan worker ReID), karena ReID adalah bagian dari keputusan identitas dan seluruhnya kini dipegang EA (dokumen 12 §7). Belum disepakati; tetap tunduk pada aturan §9 butir 3. ReID hanya menerima pesan lewat antrean internal (dokumen 04 §14.4), tidak mengimpor `runtime/`.

## 3. Backend (direstruktur di fase 1)

```
backend/
├── api/           # Router, skema request/response, auth, dependency
├── engine_link/   # Klien protokol engine, manajer koneksi, adapter protokol, ingest event
├── services/      # Ledger kunjungan, jatah harian, alerts, reports, enrollment
├── policy/        # Pemuat kebijakan + policy.yaml / policy.dev.yaml, kategori lokasi
├── domain/        # Entitas & enum: Employee, Camera, Visit, LocationCategory, Violation
├── notify/        # Antarmuka notifikasi + adapter fase 1: dashboard, email (lainnya menyusul)
├── store/         # Repositori per entitas, migrasi berversi, retensi
├── media/         # Hook otorisasi MediaMTX, view stream
├── config/        # Settings aplikasi/lingkungan, seed cameras*.yaml
├── main.py        # App factory + lifespan (tanpa singleton saat import)
└── tests/
```

**Peta pemindahan:**

| Sekarang | Jadi |
|---|---|
| `routers/`, `schemas/`, `core/security.py` | `api/` |
| `services/engine_client.py`, `engine_connection_manager.py`, `engine_integration.py`, `protocol_adapter.py`, `event_ingestion.py` | `engine_link/` |
| `services/free_time.py` (+ ledger kunjungan baru) | `services/` |
| `services/break_policy.py`, `configs/policy.yaml` | `policy/` |
| `core/database.py` (dipecah per repositori) + migrasi | `store/` |
| `services/view_stream.py`, `services/detection_stats.py` | `media/` |
| `core/config.py`, `configs/cameras*.yaml` (termasuk `cameras.remote-hls.yaml` dan `cameras.remote-webrtc.yaml` untuk demo jarak jauh) | `config/` |
| `core/state.py` | Ditinjau; bagian yang masih dipakai ke `media/` atau `services/`, sisanya dihapus |
| `services/camera_state.py`, `services/enrollment_service.py` | `services/` |

Saat dokumen ini diperbarui, backend masih memakai susunan lama (`backend/configs/`, `core/`, `routers/`, `schemas/`, `services/`). Path yang dirujuk deploy (`CAMERAS_CONFIG_FILE`, `deploy/docker-compose.portainer.yml`) harus ikut diperbarui saat `configs/` dipindah.

## 4. Frontend (direstruktur saat halaman baru dibuat)

```
frontend/src/
├── views/
├── features/      # live-monitoring, allowance, violations, employees, unknown,
│                  # corrections, reports, admin
├── components/    # ui/, layout/
├── composables/   # useWhep, useHls, useDirectSync, useOverlaySync, useAuth
├── services/      # api client, SSE multipleks
├── stores/        # Pinia bila ada state lintas fitur
├── router/        # rute + penjaga peran
└── assets/
```

`components/dashboard/*` dipindah ke `features/` sesuai fiturnya; komponen model gap dihapus; seluruh kode ke TypeScript.

## 5. Contracts

```
contracts/
├── schema/      # engine_protocol.schema.json (perubahan fase 1 lewat pemilik skema)
├── fixtures/    # skenario NDJSON + hasil yang diharapkan (ditambah skenario multi-lokasi)
├── validator/
├── tools/       # policy_grep.py, pemeriksa batas import
├── openapi/     # snapshot OpenAPI backend
└── tests/
```

Skenario fixture baru untuk fase 1: perpindahan antar-lokasi rekreasi, lokasi transit tidak ditagih, pengecualian karyawan, *impossible travel*, frame beku, lag/`camera.degraded`. Kontrak ReID dan jadwal (`identity.resolved`, `schedule_off`, `identity_source`) ditambahkan ke skema oleh pemilik skema (EA); skenario fixture-nya belum dirinci.

## 6. Deploy

Kondisi repo per 8 Oktober 2026 (paket r7), ditambah rencana yang belum ada:

```
deploy/
├── README.md
├── docker-compose.yml             # Alur lokal: backend, frontend (nginx), mediamtx, fake engine
├── docker-compose.portainer.yml   # Server Portainer CE: backend + frontend saja; env_file stack.env,
│                                  # policy.yaml di volume /data, tanpa bind mount relatif (baru)
├── portainer.env.example          # Variabel stack Portainer (LAPTOP_NETBIRD_IP, CAMERAS_CONFIG_FILE, dll.) (baru)
├── .env.example
├── backend/                       # Dockerfile backend
├── frontend/                      # Dockerfile frontend + nginx/ (TLS, HTTP/2, proxy, header keamanan,
│                                  # tanpa injeksi kunci API)
├── fake-engine/                   # Dockerfile fake engine
├── mediamtx/                      # mediamtx.yml dengan auth, dua path per kamera; skrip start .ps1/.sh
├── laptop/                        # Demo jarak jauh, Windows (baru):
│   ├── firewall.ps1               #   aturan firewall untuk IP NetBird server/VPS
│   ├── start-mediamtx.ps1         #   MediaMTX di laptop (opsi -VpsPublicIp untuk WebRTC)
│   └── start-engine.ps1           #   engine bind IP NetBird (opsi -Config, -AffinityMask)
├── vps/
│   └── nginx-stream-webrtc.conf   # Penerusan TCP 8189 untuk mode WebRTC (baru)
├── engine/                        # Rencana: Dockerfile engine berbasis nvidia/cuda + compose mesin A (belum ada)
├── systemd/                       # Rencana: unit service bila tidak memakai compose (belum ada)
└── chrony/                        # Rencana: konfigurasi NTP server/klien (belum ada)
```

Panduan pemakaian `docker-compose.portainer.yml`, `deploy/laptop/*.ps1`, dan `deploy/vps/` ada di `docs/DEMO-REMOTE.md`.

Skrip pendukung di `scripts/` yang terkait demo dan uji performa: `lag_probe.py`, `summarize_gladi.py` (ringkasan CSV gladi: fps median, waktu lambat, umur kotak, stall, vonis LULUS/GAGAL; baru di r7), `publish_test_video.ps1`/`.sh`, `preflight_demo.py`, `check_mediamtx.py`, `check_gpu_env.py`.

## 7. Konfigurasi dan data

| Berkas/data | Lokasi | Di repo? |
|---|---|---|
| Profil engine | `engine/config/dfine-*.yaml`, `demo-1060.yaml`, `demo-4060.yaml` | Ya |
| Kebijakan | `backend/policy/policy.yaml` (produksi), `policy.dev.yaml`; saat ini masih `backend/configs/policy.yaml`. Pada deploy Portainer disalin ke volume `/data` saat start pertama agar dapat diubah dari halaman Pengaturan | Ya (nilai produksi setelah disahkan) |
| Pengaturan dari web (jam istirahat per hari, jadwal analisis, jadwal dan penerima rekap) | Backend (penerima rekap di database; volume `/data` pada deploy Portainer) | **Tidak** (dibackup bersama database) |
| Seed kamera | `backend/config/cameras.yaml` (saat ini `backend/configs/`); varian demo jarak jauh `cameras.remote-hls.yaml` (default) dan `cameras.remote-webrtc.yaml`, dipilih lewat `CAMERAS_CONFIG_FILE` | Ya, tanpa kredensial |
| Variabel stack Portainer | Contoh `deploy/portainer.env.example`; nilai asli di UI Portainer (`stack.env`) | Contoh ya; nilai asli **tidak** |
| Kredensial kamera | `deploy/mediamtx/.env.mediamtx` | **Tidak** |
| Kunci bersama engine–backend, kunci API, secret sesi | `.env` di masing-masing mesin | **Tidak** |
| File model | `models/` di mesin A (hash dicatat di rilis) | **Tidak** |
| Outbox engine, referensi wajah | `engine/data/` di mesin A | **Tidak** (dibackup) |
| Cache/galeri ReID | Mesin engine; dihapus otomatis tiap akhir hari (dokumen 12 §3.6); lokasi folder belum diputuskan | **Tidak** |
| Database backend | `backend/data/` di mesin B | **Tidak** (dibackup) |

## 8. Kepemilikan

| Folder | Pemilik |
|---|---|
| `engine/api`, `engine/identity`, `engine/presence`, `engine/store`, `engine/tools/fake_engine` | Engine A |
| `engine/ingest`, `engine/perception`, `engine/bench`, `bench/` | Engine B |
| `engine/ports`, `engine/pipeline`, `engine/runtime`, `engine/config` | Bersama EA/EB (beri tahu sebelum mengubah) |
| `engine/runtime/tick_scheduler.py`, `engine/ingest/mailbox.py`, `engine/ingest/nvdec_source.py` | Engine B (struktur engine, dokumen 12 §3.9) |
| Kode ReID (usulan `engine/identity/reid/`) | Engine A (logika, model, worker) |
| `backend/**` | Backend |
| `frontend/**` | Frontend |
| `contracts/**` | Pemilik skema (EA), perubahan diumumkan ke semua jalur |
| `deploy/`, `docs/`, `scripts/` | Bersama |
| `docs/CHANGELOG.md` | Bersama; setiap paket menambah satu bagian di atas (dokumen 12 §10.2) |

## 9. Aturan restrukturisasi

1. Pemindahan dan perubahan isi **tidak** dalam commit yang sama: satu commit memindahkan dan menyambung ulang import (tes hijau sebelum dan sesudah), commit berikutnya mengubah logika.
2. Setelah pemindahan, perbarui pola path di `policy_grep.py` dan tes batas import agar tidak diam-diam berhenti memeriksa folder yang pindah.
3. Folder baru butuh tujuan yang bisa dikalimatkan tanpa kata "dan".
4. Tidak ada import silang `engine/` ↔ `backend/`.
5. Setiap paket perubahan dicatat sebagai satu bagian di `docs/CHANGELOG.md` (tanggal dan nama paket, apa yang berubah, alasan, file yang tersentuh, cara uji); tidak ada lagi file `PERUBAHAN-*.md` baru di root.
6. Kode dikirim sebagai zip kumulatif dengan struktur repo; line ending CRLF kecuali `.sh` (LF), dijaga oleh `.gitattributes`.

## Riwayat perubahan

- 9 Oktober 2026 (v1.2): §1 status paket r8 dan `.gitattributes` tanpa `* text=auto`. §2 "tidak direstruktur" diganti "direstruktur terbatas" (penjadwal berdetak, mailbox, NVDEC; dokumen 04 §14); usulan folder ReID `engine/identity/reid/`. §8 kepemilikan file penjadwal (EB) dan ReID (EA seluruhnya).

- Ditambahkan baris versi 1.1 (8 Oktober 2026) dengan rujukan ke dokumen 12 dan 13.
- §1: pohon root disesuaikan dengan struktur sasaran dokumen 12 §10.3 (`docs/CHANGELOG.md` menggantikan `CHANGELOG.md` di root, `docs/arsip/`, `.gitattributes`, README berindeks); daftar langkah restrukturisasi diperbarui.
- §2: profil `demo-1060.yaml`/`demo-4060.yaml` dicatat; ditambah catatan bahwa lokasi folder ReID belum diputuskan beserta pembagian EA/EB.
- §3: peta pemindahan menyebut `cameras.remote-hls.yaml` dan `cameras.remote-webrtc.yaml`; ditambah catatan bahwa backend masih memakai susunan lama dan path deploy ikut diperbarui.
- §5: ditambah catatan kontrak `identity.resolved`, `schedule_off`, `identity_source`.
- §6: pohon `deploy/` disesuaikan dengan repo r7 (`docker-compose.portainer.yml`, `portainer.env.example`, `laptop/*.ps1`, `vps/`, `backend/`, `fake-engine/`); item yang belum ada ditandai rencana; ditambah daftar skrip termasuk `scripts/summarize_gladi.py` dan rujukan `docs/DEMO-REMOTE.md`.
- §7: ditambah baris pengaturan dari web, variabel stack Portainer, cache ReID; baris kebijakan dan seed kamera diperbarui (volume `/data`, varian remote, lokasi saat ini).
- §8: ditambah kepemilikan kode ReID dan `docs/CHANGELOG.md`.
- §9: ditambah aturan 5 (changelog tunggal) dan 6 (zip kumulatif, line ending).
