# Changelog

Catatan perubahan kode per paket, **terbaru di atas**. Menggantikan file
`PERUBAHAN-*.md`, `PERBAIKAN-*.md`, dan `CHANGES*.md` yang dulu ada di root repo
(file aslinya dipindah ke `docs/arsip/`). Mulai paket berikutnya, catatan perubahan
ditulis langsung di sini (dokumen kesepakatan tim, dokumen 12 §10.2).

Format entri: tanggal, nama paket, apa yang berubah, alasan, file yang tersentuh, cara uji.

## 2026-10-09 · paket ea-r4 — Cache ReID dikosongkan terjadwal tiap hari

Dasar: ea-r3. Default tetap mati (`reid.enabled: false`). Keputusan ea-r3 (ANON tanpa
`track.identified`, ReID wajib rekognisi wajah, hook di `camera.py`) disetujui EA.

**Apa yang berubah**

- `config/schema.py` + `loader.py`: `reid.daily_purge_time` ("HH:MM" lokal, default `"00:00"`;
  format salah ditolak; `03:30` tanpa kutip di YAML juga diterima).
- `pipeline/reid_coordinator.py`: `maybe_purge(now)` mengosongkan galeri tubuh, kelompok ANON, dan
  rentang begitu jam purge lewat (sekali per hari). "Hari" ReID = tanggal lokal dari (waktu − jam
  purge), dipakai juga oleh pengamatan, sehingga jadwal dan data selalu sepakat. Log INFO saat purge.
  Label hanya dikirim ke kamera bila ada; pencabutan selalu lewat `revoked`. Akibatnya track yang
  hidup melintasi purge tidak kehilangan label (dan waktu kehadirannya).
- `runtime/service.py`: ticker runtime (tiap 0,5 dtk) memanggil `maybe_purge`; sebelumnya galeri
  hanya dikosongkan saat pengamatan pertama sesudah tengah malam, jadi data penampilan tertinggal
  semalaman bila kamera sepi.
- Profil `demo-4060.yaml`, `demo-4060-tick.yaml`, `demo-1060.yaml`: `daily_purge_time: "00:00"`.

**Alasan.** Dokumen 12 §3.6 butir 7 (hapus cache harian): pakaian berganti antar hari, dan data
penampilan tubuh tidak boleh disimpan lebih lama dari perlu.

**Cara uji.** `python -m pytest engine/tests -q` (617 lulus, 7 dilewati seperti sebelumnya); +10 di
`test_reid_runtime.py` (jam purge dari config/ditolak, purge terjadwal tanpa pengamatan dan sekali per
hari, label track hidup tidak dicabut, ticker memanggil jadwal). `policy_grep` bersih. Uji laptop:
langkah 7 di `docs/SERAH-TERIMA-EA-R3.md`.

## 2026-10-09 · paket ea-r3 — Model ReID OSNet ONNX dirakit ke engine (default mati)

Dasar: repo 9 Okt (sesudah eb-r10). Jalur EA. Menyambungkan model hasil kit ea-r2
(`tools/reid_train/`) ke logika ReID ea-r1 (`engine/identity/reid/`) dan memancarkan
`identity.resolved` sesuai kontrak ea-k1. **`reid.enabled: false` di semua profil**: tanpa itu
tidak ada model dimuat, tidak ada worker, dan tidak ada event yang berubah. `engine/ports/`,
`contracts/`, dan `backend/` tidak disentuh. Tidak ada berkas ONNX di repo.

**Apa yang berubah**

- Baru `engine/identity/reid/embedder_onnx.py`: OSNet ONNX lewat onnxruntime (memakai ulang
  `_session` dari `face_onnx.py`: CUDA diminta tapi aktif CPU = ditolak). Pra-proses identik
  `tools/reid_train/reid_common.py` (BGR→RGB, resize langsung 256x128 dengan aturan interpolasi
  yang sama, /255, mean/std ImageNet), batch per `max_batch`, keluaran L2. SHA-256 berkas
  diverifikasi terhadap `reid.model_sha256` (salah = start ditolak; kosong = peringatan).
- Baru `engine/identity/reid/quality.py`: gerbang crop badan (tinggi minimum, rasio aspek,
  terpotong tepi frame = kualitas rendah, tidak di-embed).
- Baru `engine/pipeline/reid_worker.py`: worker embedding satu untuk semua kamera, pola
  `recognition_worker.py` (antrean terbatas, tolak seketika bila penuh, buang crop basi), tetapi
  crop beberapa kamera digabung jadi satu batch.
- Baru `engine/pipeline/reid_coordinator.py`: satu `PendingIdentities` untuk semua kamera di bawah
  satu kunci; label per track dikirim ke kotak masuk kamera; `identity.resolved` dipancarkan di
  bawah kunci yang sama dengan gerbang interval, sehingga interval ANON selalu terbit sebelum
  penyelesaiannya dan masuk `moved_intervals`. ID ANON memuat nonce per proses (restart engine
  di tengah hari tidak menerbitkan ID yang sama lagi). Hari baru (lokal) = galeri dikosongkan.
- Baru `engine/pipeline/reid_tap.py`: sisi kamera. Embedding berbasis kejadian (track baru, wajah
  baru terkonfirmasi, lalu tiap `embed_interval_seconds`), pembaruan rentang ±1 dtk tanpa
  embedding, `TrackClosed` saat track hilang. Track berwajah tidak pernah dilabeli ReID.
- `config/schema.py` + `loader.py`: section `reid` (`enabled`, `model_path`, `model_sha256`,
  `match_threshold`, `match_margin`, `min_crop_height_px`, `min_aspect`, `max_aspect`,
  `edge_margin_px`, `embed_interval_seconds`, `max_batch`, `worker_queue`, `max_age_seconds`,
  `onnx_providers`, `onnx_gpu_mem_limit_mb`, `travel_time_seconds`, `default_travel_time_seconds`).
  `reid.enabled` tanpa `recognition.recognizer: onnx_face` ditolak. `match_threshold: null` = usulan
  0,80 yang belum dikalibrasi (peringatan di log). Blok `reid` (mati) di `demo-4060.yaml`,
  `demo-4060-tick.yaml`, dan `demo-1060.yaml` (1060: `onnx_gpu_mem_limit_mb: 512`).
- `runtime/service.py`: ReID dimuat di konstruktor (gagal = engine menolak start), dioper ke
  kamera, dihentikan saat tutup; metrik ReID di log health; `reid_worker_stopped` di
  `degraded_components`.
- `runtime/camera.py`: tap dipanggil per frame; label ReID mengisi `person_id`/`identity_source`
  di heartbeat, snapshot, dan `view.frame` hanya untuk track tanpa wajah;
  `person.unidentified_present` tetap berdasarkan wajah (ANON = belum dikenali).
- `presence/assembler.py`: `reid_assigned`/`reid_cleared` (tanpa `track.identified`), gerbang
  interval opsional. Tanpa gerbang (ReID mati) jalurnya sama dengan sebelumnya.
- `api/events.py`: `identity_resolved(...)`; `track.heartbeat` menerima `reid`/`reid_retro`.
- `face_onnx._session`: parameter pesan galat (`purpose`, `providers_key`); perilaku sama.
- `.gitignore`: `engine/models/`.
- `scripts/lag_probe.py`: opsi `--events-out NDJSON` (default mati) merekam event kanal `events`
  untuk `python -m contracts.validator`, supaya aliran ReID bisa diperiksa di laptop tanpa backend.
- Dokumen: `docs/PETA-KODE.md`, `docs/SERAH-TERIMA-EA-R3.md` (baru; `SERAH-TERIMA.md` EB tidak diganti).

**Belum aman dengan backend sungguhan**: `backend/schemas/protocol.py` belum mengenal `reid`/`reid_retro`
dan `identity.resolved` (tugas BE dari ea-k1). Lihat SERAH-TERIMA-EA-R3.

**Alasan.** Dokumen 12 §3.6 dan timeline dokumen 14 (EA 20–23 Okt): model ReID ke ONNX, quality
gate, worker, integrasi. Ambang ditahan (belum ada crop berlabel dari kamera lokasi), jadi
semuanya terpasang tetapi mati, dan ambang masih usulan.

**Cara uji.** `python -m pytest engine/tests -q` (607 lulus, 7 dilewati seperti sebelumnya);
baru: `test_reid_embedder.py` (11, termasuk model ONNX mini ujung ke ujung, dilewati tanpa `onnx`)
dan `test_reid_runtime.py` (26, embedder palsu: gerbang, config, interval, worker, dua kamera
ANON → `identity.resolved` lolos skema + `ConformanceChecker`, kamera mock), +1 di `test_lag_probe.py`
(engine ReID menyala → NDJSON lolos validator). `python
contracts/tools/policy_grep.py engine/` bersih; `contracts/tests` lulus. Uji di laptop: lihat
`docs/SERAH-TERIMA-EA-R3.md`.

## 2026-10-09 · paket eb-r10 — Alat baseline 5 kamera (`-Count`, ringkasan multi-kamera)

Dasar: repo 9 Okt (sesudah ea-r2). **Hanya alat ukur di laptop**; `engine/runtime/`, profil
`engine/config/`, `engine/ports/`, dan kontrak tidak disentuh. Eksekusi baseline dilakukan nanti di
laptop 4060 (dokumen 04 §14, DEMO-REMOTE §8.1).

**Apa yang berubah**

- `scripts/publish_test_video.ps1`: parameter `-Count N` (1..99, default 1). `-Count 1` memakai jalur
  lama (satu `ffmpeg`, `-Path` dihormati). `-Count > 1`: satu proses ffmpeg per path `cam01..camN`,
  daftar argumen encode sama (satu array dipakai kedua jalur), jeda 0,5 dtk antar start; bila satu
  proses mati, semua dihentikan dan skrip gagal (baseline yang kehilangan stream diam-diam tidak
  valid); `-Path` bersama `-Count > 1` ditolak.
- `scripts/summarize_gladi.py`: CSV dengan beberapa `camera_id` dihitung **per kamera** lalu digabung.
  Tabel: satu baris per kamera + satu baris gabungan per file (`<file> [N kam]`). Vonis tetap per file:
  LULUS hanya bila semua kamera LULUS (kamera tanpa sampel box = GAGAL). Gabungan: fps/lambat/umur box
  dari semua sampel, ganti dan stall dijumlahkan, drop/s = jumlah median per kamera. CSV satu kamera
  atau tanpa `camera_id` menghasilkan angka dan tabel yang sama seperti sebelumnya.
- `docs/DEMO-REMOTE.md` §8.1: perintah publish `-Count 5` dan cara membaca tabel multi-kamera.
- `engine/tests/test_summarize_gladi.py`: +6 tes (1 kamera ber-id = tanpa id, 5 kamera bersih,
  satu kamera macet menggagalkan file, irama per kamera bukan deret campuran, kamera tanpa box,
  `main` per file).

**Alasan.** Skrip lama mencampur semua baris `health` dari lima kamera dalam satu deret: "ganti fase"
dan laju drop jadi tak bermakna (selisih `dropped` antar kamera berbeda), dan satu kamera macet bisa
tertutup median kamera lain. Publish lima stream tadinya butuh lima terminal manual.

**Cara uji.** `python -m pytest engine/tests/test_summarize_gladi.py -q` (10 lulus).
`publish_test_video.ps1` tidak bisa diuji di cloud (tanpa PowerShell/MediaMTX): langkah di
SERAH-TERIMA.

## 2026-10-09 · paket ea-r2 — Kit latih OSNet ReID dari RandPerson (`tools/reid_train/`)

Dasar: repo 9 Okt (sudah berisi ea-r1). **Hanya alat latih di laptop**; `engine/`, `engine/ports/`,
kontrak, dan `pytest.ini` tidak disentuh. torch/torchreid bukan dependensi runtime engine.
Tidak ada dataset, bobot, atau ONNX yang diunduh/ditambahkan (`tools/reid_train/.gitignore`
menolak `runs/`, `*.pth`, `*.pt`, `*.onnx`).

**Apa yang berubah** (semua file baru)

- `prepare_randperson.py`: pindai subset (`<pid>_s<scene>_c<cam>_f<frame>.jpg`), resize 256x128, JPG
  q95, `camid` = indeks (scene, kamera); split per IDENTITAS (±90/10, seed), di val satu gambar per
  (pid, kamera) jadi query dan sisanya gallery; tulis `manifest.csv` + `summary.json`. Bisa dilanjutkan.
- `randperson_dataset.py`: `ImageDataset` torchreid dari manifest, terdaftar sebagai `randperson`.
- `train_osnet.py`: `--init imagenet|scratch`, `--arch osnet_ain_x1_0|osnet_x1_0|osnet_ain_x0_25`,
  softmax+label smoothing + triplet batch-hard 1:1, amsgrad lr 0,0015 cosine (+pemanasan), AMP,
  augmentasi kuat, `best.pth` (mAP val kosinus) + `last.pth`, `log.csv`, TensorBoard, `config.json`
  (termasuk SHA-256 bobot ImageNet), `--resume`. Bobot ImageNet dimuat sendiri (`weights_only=True`),
  bukan lewat `pretrained=True`, agar bisa dicatat SHA-nya dan gagal dengan petunjuk unduh manual.
- `export_onnx.py`: embedding saja, 1x3x256x128 batch dinamis, opset 17, verifikasi PyTorch vs
  onnxruntime (< 1e-3, batch 8 dan 1), SHA-256; menerima checkpoint torchreid eksternal (pembanding).
- `eval_reid.py`: mAP/rank-1/rank-5 + kurva ambang kosinus (sambungan benar vs salah gabung) +
  ambang rekomendasi (salah gabung ≤ 1%), banyak ONNX sekaligus, tanpa torch.
- `reid_common.py`, `MODEL-CARD.md`, `README.md`, `requirements-train.txt`, `requirements-train-deps.txt`.
- Tes: `tools/reid_train/tests/` (7 tes; ujung-ke-ujung CPU 40 gambar palsu: prepare → latih 1 epoch
  → export → eval; dilewati bila torch tidak terpasang).

**Alasan.** Menyiapkan model ReID tubuh yang bisa dilatih tanpa data klien dan dibandingkan secara
adil pada crop berlabel tim (SERAH-TERIMA ea-r1, butir "model + worker embedding tubuh").

**Temuan saat menguji.** (1) `setup.py` torchreid gagal di Python 3.13 → pakai 3.10–3.12.
(2) Pasang torchreid harus dua tahap + `--no-build-isolation` (metadata-nya mengimpor torch,
scipy, cv2): karena itu ada `requirements-train-deps.txt`. (3) torchreid dipin ke commit f8cd150.

**Cara uji.** `python -m pytest tools/reid_train/tests -q` (venv Python 3.11 + `requirements-train*.txt`;
7 lulus di venv bersih tanpa ekstensi Cython, ±8 dtk). Tanpa torchreid: hanya tes prepare yang jalan,
sisanya dilewati. `python contracts/tools/policy_grep.py engine/` bersih.

## 2026-10-09 · paket ea-r1 — Logika ReID berjangkar wajah (`engine/identity/reid/`)

Dasar: repo 9 Okt (sudah berisi ea-k1). Keputusan: dokumen 12 §3.6. **Hanya logika, tanpa
model**: embedding tubuh diterima sebagai vektor numpy. Belum dirakit ke `runtime/camera.py`
(menunggu penjadwal tahap 2 EB); `engine/ports/` dan kontrak tidak disentuh.

**Apa yang berubah** (semua file baru)

- `identity/reid/messages.py`: `BodyObservation` (camera_id, track_id, track_uuid, at,
  embedding opsional, `face_person_id` hanya bila identitas track dari wajah, zone) dan
  `TrackClosed`. Dataclass + numpy saja, tanpa import `runtime/`. Validasi pola `tr_…`,
  menolak `face_person_id` berawalan `ANON-`, embedding dinormalisasi L2.
- `identity/reid/gallery.py`: `PrototypeSet` (beberapa prototipe per orang, dilebur bila
  sudutnya sama, menjaga keragaman saat penuh) dan `DailyGallery` (hanya menerima sumber
  wajah, skor = maksimum atas prototipe, `purge_day()`).
- `identity/reid/merge.py`: `ReidConfig` (+ `from_mapping` untuk blok YAML kelak), aturan
  murni `check_pair`/`check_group` (cannot-link bila rentang hidup tumpang-tindih; waktu
  tempuh minimum antar lokasi, pasangan tak tercantum = 30 dtk) dan `pick_best` (ambang 0,80
  + margin 0,05 atas skor mentah).
- `identity/reid/pending.py`: `PendingIdentities` — galeri → kelompok ANON → ANON baru;
  wajah menyelesaikan seluruh kelompok (`face_confirmed`) lalu menyapu kelompok lain yang
  cocok (`group_merged`); klaim ReID yang belakangan bertabrakan waktu dicabut (wajah tidak
  pernah dicabut); `Resolution.event_fields()` = isi `identity.resolved` tanpa amplop dan
  tanpa `moved_intervals` (milik presence); `purge_day()` melaporkan ANON yang belum selesai.
- Tes: `engine/tests/test_reid_messages_gallery.py`, `test_reid_merge.py`,
  `test_reid_pending.py` (39 tes).

**Alasan.** Dokumen 12 §3.6: ReID adalah referensi berjangkar wajah, bukan pengenal
mandiri; aturan condong ke "lebih baik terpecah daripada tertukar".

**Cara uji.** `python -m pytest engine/tests -q -k reid`; seluruh `engine/tests` lulus;
`python contracts/tools/policy_grep.py engine/` bersih. Keluaran `event_fields()` dicek
manual terhadap `$defs.identity_resolved` dengan jsonschema (lulus).

## 2026-10-09 · paket ea-k1 — Kontrak ReID dan jadwal analisis (`identity.resolved`, `schedule_off`, `reid`/`reid_retro`)

Dasar: repo 9 Okt (sudah berisi r9). Keputusan: dokumen 12 §3.3 (jadwal engine) dan §3.6
(ReID). Hanya kontrak dan `fake_engine`; **`backend/` dan `engine/` (selain
`tools/fake_engine`) tidak disentuh** — BE/EB menyesuaikan dari `SERAH-TERIMA-EA-K1.md`.

**Apa yang berubah**

- `contracts/schema/engine_protocol.schema.json`:
  - Event baru `identity.resolved` (kanal events): `anon_id` (`ANON-xxxx`) → `person_id`,
    `at`, `reason` (`face_confirmed` | `group_merged`), `track_uuids`, `moved_intervals`,
    opsional `trigger_track_uuid`.
  - `$defs.anon_id` (baru): pola `^ANON-[A-Za-z0-9]{1,32}$`, cocok dengan pola `person_id`
    sehingga dipakai apa adanya sebagai `person_id` selama belum diselesaikan.
  - `$defs.identity_source` (baru, satu sumber): `face | tracking | reid | reid_retro`.
    Menggantikan tiga enum inline (`track.heartbeat`, `snapshot.live[]`,
    `view.frame.boxes[]`). `boundary_source` (batas interval) **tidak diubah**.
  - `end_reason` + `schedule_off` (dipakai `track.ended` dan `presence.interval`).
  - **Tidak ada field wajib baru di event lama.**
- `contracts/validator/conformance.py`: aturan baru — `identity.resolved` (interval
  yang dipindah harus pernah dipancarkan dan berlabel `anon_id` itu; semua interval ANON
  harus terdaftar; tidak boleh dua kali; track harus dikenal; ANON tidak dipakai lagi
  sesudah resolusi); `schedule_off` wajib `end_source=forced` dan tidak boleh saat
  kamera putus (itu `camera_lost`); ANON yang tak pernah diselesaikan = peringatan.
- `engine/tools/fake_engine/`: directive `identity.pending`, `identity.resolved`
  (daftar interval dan anggota kelompok **diturunkan**, bukan ditulis tangan),
  `analysis.off`, `analysis.on`; skenario `15-reid-tertunda` dan `16-jadwal-mati`;
  `expected.json` memuat `resolutions` hanya bila ada resolusi. Perbaikan kecil:
  `end_source` bawaan untuk track berumber `reid` kini `tracking` (sebelumnya `face`).
- `contracts/fixtures/`: `reid-tertunda.*`, `jadwal-mati.*` (baru). **Fixture 14 skenario
  lama tidak berubah satu byte pun.**
- `contracts/tests/`: tes baru (skenario, enum, `identity.resolved`, conformance) dan
  `required_baseline.json` yang mengunci "tidak ada field wajib baru di event lama".

**Alasan.** Dokumen 12 menetapkan atribusi mundur dan penutupan track saat jadwal mati
sebagai bagian protokol; tanpa kontrak, EB/BE/FE menebak bentuknya masing-masing.
`schedule_off` dibedakan dari `left_frame` (orang pulang) dan `camera_lost` (kamera
putus) supaya jadwal mati tidak terbaca "semua orang pulang".

**Yang belum / terbuka** (rinci di SERAH-TERIMA): dokumen 07 dan `ENGINE_PROTOCOL.md`
belum diperbarui; `engine.health.cameras` belum punya status "analisis mati".

**Cara uji.**
- `python -m pytest contracts/tests -q` (151 tes) dan `python -m pytest -q` (seluruh repo: 731 lulus, 7 skip).
- `python -m engine.tools.fake_engine --all --record contracts/fixtures && git status`
  tidak boleh menunjukkan perubahan pada fixture lama.
- `python -m engine.tools.fake_engine --scenario reid-tertunda --stdout --channel events`

## 2026-10-09 · paket r9 — Kerangka penjadwal berdetak (restrukturisasi engine, tahap 1)

Dasar: repo 8 Okt + paket r8 (r8 harus sudah dipasang). Keputusan: dokumen 12 §3.9,
desain: dokumen 04 §14. **Default tidak berubah**: tanpa `core.scheduler: tick`
engine berjalan persis seperti r7/r8.

**Apa yang berubah**

- `engine/runtime/tick_scheduler.py` (baru):
  - `TickClock`: detak berperiode tetap, detak yang molor tidak dikejar, statistik
    `late_ticks` / `skipped_ticks` / `max_lateness_seconds`.
  - `TickGate` (**tahap 1, bisa dipakai**): thread kamera menunggu detak sebelum tiap
    langkah; semua kamera dilepas bersamaan. Kamera yang masih sibuk saat detak lewat
    tidak menjalankan dua langkah untuk satu detak; detak terlewat dihitung per kamera.
    Ringkasan ke log tiap 60 detik.
  - `TickScheduler` (**tahap 2, kerangka**): satu thread, satu batch per detak, kamera
    tanpa frame dilewati, kesalahan satu kamera/batch terisolasi, sisa waktu untuk
    rekognisi/ReID. Belum dirakit ke `service.py` (pekerjaan EB minggu 2).
- `engine/ingest/mailbox.py` (baru): slot frame terbaru generik (`take()` tidak memblok)
  untuk tahap 2 dan NVDEC. `PyAVSource` tetap memakai slotnya sendiri.
- `engine/ingest/nvdec_source.py` (baru, kerangka): `nvdec_available()` dan
  `NvdecSource` yang menolak dengan pesan menunjuk spike. Kontrak implementasinya
  ditulis di docstring.
- `scripts/spike_nvdec.py` (baru): spike 15–16 Okt; bandingkan PyAV CPU, PyAV
  hwaccel cuda, dan PyNvVideoCodec (frame tetap di GPU, cek `torch.from_dlpack`).
- `engine/config/schema.py`, `loader.py`: `core.scheduler` (`free` | `tick`,
  default `free`) dan `core.tick_fps` (default ikut `target_fps`). Mode tick tanpa fps
  ditolak saat load.
- `engine/runtime/service.py`: mode tick membuat `TickGate`, menyamakan `target_fps`
  dengan `tick_fps`, dan menyalakan `wait_for_all` di detector bersama.
- `engine/runtime/camera.py`: satu tunggu detak sebelum `engine.step()`;
  daftar/keluar gerbang saat kamera buka/tutup/gagal. Sumber live berslot frame terbaru
  tidak di-decimate lagi di mode tick (`engine.external_pacing`).
- `engine/pipeline/engine.py`: atribut `external_pacing` (default False).
- `engine/perception/shared_detector.py`: opsi `wait_for_all` — dispatcher berhenti
  menunggu begitu semua kamera terdaftar mengirim, paling lama `batch_wait_ms`.
- `engine/config/demo-4060-tick.yaml` (baru): profil uji tick 6 fps, `batch_wait_ms` 15.
- `deploy/laptop/start-engine.ps1`: parameter `-TargetFps` (untuk pembanding adil
  free 6 fps).
- `docs/DEMO-REMOTE.md` §8.1: protokol A/B free vs tick 5 stream.

**Alasan.** Ketidakstabilan 4060 (fps 10 ↔ 6, stall 9 detik) berasal dari irama
yang dipegang thread tiap kamera, bukan dari GPU penuh. Tahap 1 bisa diuji minggu ini
tanpa merombak `camera.py`; tahap 2 dan NVDEC menyusul sesuai dokumen 14.

**Yang belum.** Tahap 2 belum dirakit; `ports/frame.py` belum membawa data GPU
(menunggu kesepakatan EA–EB 13 Okt); NVDEC menunggu vonis spike; ringkasan detak
belum masuk `engine.health` (sengaja: perubahan wire menunggu kontrak).

**Cara uji.**
- `python -m pytest engine/tests/test_tick_scheduler.py` (22 tes) dan seluruh
  `engine/tests` tetap lulus.
- Di laptop: DEMO-REMOTE §8.1 (T0-6 vs T1, 15 menit, 5 stream), ringkas dengan
  `summarize_gladi.py --target-fps 6`.
- Spike: `python scripts/spike_nvdec.py --url rtsp://127.0.0.1:8554/cam01 --seconds 60`.

## 2026-10-08 · paket r8 — Restrukturisasi repo

Dasar: repo 8 Okt (sudah berisi r7). Tidak ada perubahan kode aplikasi.

**Apa yang berubah**

- 28 catatan perubahan di root (`PERUBAHAN-*.md`, `PERBAIKAN-*.md`, `CHANGES*.md`)
  digabung ke file ini, urut tanggal, terbaru di atas. File aslinya dipindah apa
  adanya ke `docs/arsip/`.
- Dua catatan timer backend yang isinya berbeda (`CHANGES_TIMER_BACKEND.md` di root,
  `docs/CHANGES_TIMER_BACKEND_2026-09-22.md`) kini jadi dua entri terpisah di bawah
  (22 dan 23 September); aslinya di `docs/arsip/`.
- Dokumen status basi `PACKAGE_VERSION.txt` dan `WORKPLAN_STATUS.md` (keduanya
  23 September) dipindah ke `docs/arsip/`. Status terkini: dokumen kesepakatan tim
  (dokumen 12) dan file ini.
- `.gitattributes` baru: `*.sh` selalu LF; berkas biner ditandai `binary`.
  `deploy/mediamtx/start-mediamtx.sh` dan `scripts/publish_test_video.sh`
  dikembalikan ke LF (sebelumnya CRLF, gagal dijalankan `sh` di Linux).
- `.gitignore` root: tambahan bobot model (`*.pt`, `*.onnx`, ...) dan database
  SQLite di mana pun, karena `model_path` dan `references.sqlite3` relatif ke root.
- `README.md` root berisi indeks dokumen; `docs/README.md` ditulis ulang sebagai
  indeks `docs/`.

**Alasan.** Dokumen 12 §10.2–10.3: root berisi 30 file `.md`, dua `.sh` berubah
jadi CRLF, dan status repo tersebar di dokumen yang sudah basi.

**Sengaja tidak dipakai: `* text=auto`.** Dokumen 12 §10.3 menulis
`* text=auto`. Aturan itu memaksa semua file teks disimpan LF di repo. Bila repo
saat ini menyimpan CRLF, `git add --renormalize .` akan menyentuh hampir semua
file dan menghasilkan diff raksasa yang menutupi riwayat. Jadi yang dipasang
hanya aturan `*.sh`. `* text=auto` bisa menyusul sebagai commit tersendiri bila
tim setuju.

**Konvensi mulai sekarang.** Catatan perubahan paket berikutnya ditulis langsung
di file ini, bukan file baru di root.

**File tersentuh.** Baru: `.gitattributes`, `docs/CHANGELOG.md`, `docs/arsip/*`.
Diubah: `README.md`, `docs/README.md`, `.gitignore`, dua `.sh`. Dipindah ke
`docs/arsip/`: 31 file (lihat `docs/arsip/README.md`).

**Cara uji.**
- `git status` setelah commit menampilkan file lama sebagai *renamed* ke
  `docs/arsip/`, bukan hapus + tambah.
- `git ls-files --eol -- "*.sh"` menampilkan `i/lf` untuk kedua file.
- `python -m pytest -q` tetap lulus (tidak ada kode yang berubah).

## 2026-10-08 · paket r7 — Deploy Portainer (engine di laptop via NetBird) + kotak hantu di overlay + uji A/B 4060

*Catatan asli: [`arsip/PERUBAHAN-DEPLOY-PORTAINER_KOTAK-HANTU-OVERLAY_UJI-AB-4060.md`](arsip/PERUBAHAN-DEPLOY-PORTAINER_KOTAK-HANTU-OVERLAY_UJI-AB-4060.md)*

Tanggal: 8 Okt 2026. Dasar: repo 8 Okt + paket backend r6.

Paket kumulatif r7: isi r6 ditambah perubahan di bawah. Menggantikan semua paket sebelumnya.

### 1. Kotak hantu: satu orang tampil dengan 2-3 kotak

**Penyebab.** `ByteTrackTracker.update()` (`engine/perception/bytetrack_tracker.py`) mengembalikan track yang hilang dengan state `LOST` selama `track_buffer_seconds` (1 dtk), memakai kotak **terakhir yang membeku**. Masa tenggang ini benar untuk presensi. Tapi `_maybe_view` (`engine/runtime/camera.py`) mengirim semua track ke kanal view tanpa memeriksa state. Saat ByteTrack memberi ID baru ke orang yang sama (ID switch), kotak lama membeku sampai 1 dtk di samping kotak baru. Dua switch dalam sedetik menghasilkan tiga kotak.

**Perbaikan.** Overlay hanya mengirim track `NEW`/`TRACKED`, ditambah track `LOST` yang baru hilang ≤ 0,3 dtk (`VIEW_LOST_GRACE_SECONDS`). Pengecualian 0,3 dtk itu supaya satu frame tanpa deteksi tidak membuat kotak berkedip. Presensi tidak berubah: `_remember_live` dan assembler tetap memakai masa tenggang penuh. Frame tanpa track aktif tetap dikirim kosong, supaya browser berhenti menggambar kotak lama.

**Yang tidak diperbaiki di sini:**
- **ID switch itu sendiri.** Penyetelan tracker, atau nanti ReID.
- **Deteksi ganda dari D-FINE.** Dua kotak yang sama-sama bergerak menempel satu orang.

Kalau setelah ini masih ada kotak ganda yang *ikut bergerak*, penyebabnya salah satu dari dua itu.

### 2. Uji A/B 4060

Protokolnya ada di `docs/DEMO-REMOTE.md` §8. Empat run 15 menit di laptop saja:
- **R0:** semua perubahan run 3;
- **R1:** tanpa `-r 25`;
- **R2:** tanpa afinitas;
- **R3:** power throttling ffmpeg/mediamtx di-reset.

`scripts/summarize_gladi.py` meringkas semuanya dalam satu tabel dengan vonis. Untuk tiga gladi 8 Okt, vonisnya sama dengan bacaan manual:

```
file                         menit fps med  lambat ganti drop/s umur med   p95   p99  maks stall  vonis
8015b0e3-gladi-4060-15m.csv   14.0    6.12   55.8%     4   13.9     0.42  3.62  6.83  8.93     2  GAGAL
4c27bf36-gladi-4060-15m.csv   14.0    5.92   84.9%     6   23.3     0.63  3.23  4.22  4.45     3  GAGAL
79f4d808-gladi-4060-15m_1.cs  14.0   10.00    0.0%     0    0.0     0.04  0.07  0.09  0.10     0  LULUS
```

### 3. Deploy Portainer

Isi sama dengan paket sebelumnya:
- **Laptop:** ffmpeg, MediaMTX, dan engine.
- **Server Portainer CE:** backend dan frontend.
- **Lewat NetBird:** backend → engine :8765, dan nginx → MediaMTX laptop :8888/:8889.
- **Video:** HLS (default); WebRTC opsional lewat TCP 8189 di IP publik VPS.

Masalah compose lama yang diselesaikan:

| Masalah di compose lama | Akibat | Di compose Portainer |
|---|---|---|
| Tidak ada `env_file` | Admin tidak terbentuk, tidak bisa login, email mati | `env_file: stack.env` |
| `backend/configs` di-mount `:ro` | Ubah batas waktu gagal | `policy.yaml` di `/data`, disalin dari image saat start pertama |
| Bind mount relatif | Tidak menunjuk ke host di Portainer CE | Dihapus; config ikut image |
| `localhost` di config kamera | Engine dan browser membuka mesin yang salah | `rtsp://127.0.0.1` (dibuka engine di laptop) dan path relatif |

Perubahan dari paket sebelumnya: `start-engine.ps1` sekarang memakai `-BindIp` (alias `-NetBirdIp` tetap jalan), supaya bisa dipakai untuk uji A/B di `127.0.0.1`. Runbook menambah §8 (uji A/B), satu baris checklist afinitas, dan satu baris gejala kotak ganda.

### Daftar file

| File | Status | Isi |
|---|---|---|
| `engine/runtime/camera.py` | UBAH | Kotak hantu: konstanta, filter di `_maybe_view`, helper `_recently_seen`. |
| `deploy/docker-compose.portainer.yml` | BARU | Compose khusus Portainer: backend + frontend, `env_file: stack.env`, tanpa bind mount relatif, `policy.yaml` di volume `/data`. |
| `deploy/portainer.env.example` | BARU | Variabel untuk ditempel di UI Portainer (Advanced mode). |
| `backend/configs/cameras.remote-hls.yaml` | BARU | Kamera mode remote, video HLS (default). |
| `backend/configs/cameras.remote-webrtc.yaml` | BARU | Kamera mode remote, video WebRTC (opsional). |
| `deploy/laptop/start-mediamtx.ps1` | BARU | MediaMTX di laptop dengan config repo; `-VpsPublicIp` untuk WebRTC. |
| `deploy/laptop/start-engine.ps1` | BARU | Engine yang hanya mendengarkan di `-BindIp` (IP NetBird, atau 127.0.0.1 untuk uji A/B); afinitas opsional. |
| `deploy/laptop/firewall.ps1` | BARU | Firewall Windows: port dibuka hanya untuk IP NetBird server/VPS; `-Remove` untuk membersihkan. |
| `deploy/vps/nginx-stream-webrtc.conf` | BARU | Penerusan TCP 8189 di VPS ke laptop (hanya WebRTC). |
| `scripts/summarize_gladi.py` | BARU | Ringkasan dan vonis LULUS/GAGAL dari satu atau beberapa CSV `lag_probe`. |
| `engine/tests/test_view_overlay_states.py` | BARU | Mengunci perbaikan kotak hantu (3 tes). |
| `engine/tests/test_summarize_gladi.py` | BARU | Tes `summarize_gladi.py` (4 tes). |
| `docs/DEMO-REMOTE.md` | BARU | Runbook demo jarak jauh, termasuk §8 uji A/B 4060. |
| `deploy/.gitignore` | UBAH | Tambah `stack.env`. |

Semua file CRLF.

### Uji

- **Seluruh tes:** `pytest` (contracts + engine + backend) **658 lulus**, 7 di-skip. Tes skip memang butuh GPU atau model.
- **Tes overlay:** ketiganya **gagal di `camera.py` lama** dan lulus di yang baru.
- **`summarize_gladi.py`:** dicek pada tiga CSV gladi 8 Okt (tabel di §2), plus 4 tes sintetis.
- **Deploy:**
  - `docker compose config` valid.
  - Backend dengan env setara container: admin login 200, `/api/cameras` benar, ubah policy 200 dengan komentar utuh.
  - Skrip `.ps1` lolos parser PowerShell 7.4.
- **Belum bisa diuji di sandbox:**
  - build dan jalan di Docker atau Portainer;
  - `stack.env` di Portainer CE;
  - skrip Windows (`Get-NetIPAddress`, firewall);
  - NetBird, VPS, dan Cloudflare;
  - WebRTC TCP.


## 2026-10-08 · paket r6 — Perubahan: review frontend 8 Okt + perbaikan backend r5 dipasang ulang

*Catatan asli: [`arsip/PERUBAHAN-REVIEW-FRONTEND-8OKT.md`](arsip/PERUBAHAN-REVIEW-FRONTEND-8OKT.md)*

### Temuan

1. **Perbaikan backend r5 tidak ikut terpasang.** Di zip 8 Okt, folder `backend/`
   sama persis dengan zip 6 Okt. Hanya `PERUBAHAN-BACKEND-FRONTEND-PERBAIKAN-REVIEW-6OKT.md`
   dan bagian frontend r5 yang masuk. Akibatnya:
   - POST koreksi masih dijawab daftar sesi aktif, dan koreksi tidak tersimpan;
   - halaman Pengaturan yang baru (PUT /api/settings/policy) akan **menghapus
     semua komentar di policy.yaml** setiap kali disimpan;
   - error evaluasi pelanggaran masih membuat event masuk dead letter;
   - `backend/.gitignore` masih mengabaikan `tests/`;
   - isi email masih berupa epoch mentah, tanpa tautan dashboard.

   File backend r5 dipasang ulang tanpa perubahan. Backend tidak berubah sejak
   6 Okt, jadi tidak ada konflik.
2. **Notifikasi: `read` vs `read_at`.** Backend mengirim `read_at` (epoch/null),
   tetapi frontend membaca `item.read`. Setelah halaman dimuat ulang, semua
   notifikasi terlihat belum dibaca, badge tidak pernah berkurang, dan tombol
   "Tandai dibaca" muncul lagi. Perbaikan di `useNotifications.ts`: `normalize()`
   menurunkan `read` dari `read_at` untuk daftar maupun SSE.

### Yang sudah baik (frontend 8 Okt)

- Login dan guard rute: semua halaman butuh login, `/enrollment` dan `/settings`
  hanya admin.
- Kotak notifikasi (popover) dengan SSE dan badge.
- Halaman Pengaturan (batas jatah, status SMTP, tombol email uji).
- Semua panggilan yang mengubah data memakai `apiFetch` (dengan token).

### Catatan kecil (tidak diubah)

- Menu "Enrollment" dan "Pengaturan Sistem" tetap tampil untuk viewer, lalu
  diam-diam dialihkan ke `/`. Lebih jelas bila disembunyikan (`isAdmin`).
- Nilai awal form pengaturan 60/10 sebelum data termuat. Lebih aman kosong /
  skeleton.

Tes: backend + engine lulus di sandbox (FastAPI 0.135 dari sumber).
`useNotifications.ts` lolos `tsc`. Template belum bisa di-build di sini;
jalankan `npm run build`.


## 2026-10-06 · paket r5 — Perubahan: perbaikan bug hasil review backend 6 Okt

*Catatan asli: [`arsip/PERUBAHAN-BACKEND-FRONTEND-PERBAIKAN-REVIEW-6OKT.md`](arsip/PERUBAHAN-BACKEND-FRONTEND-PERBAIKAN-REVIEW-6OKT.md)*

Dasar: zip repo 6 Okt (update backend: login, pelanggaran, notifikasi, email,
pengaturan). Isi paket ini juga mencakup paket engine r4 (power throttling),
yang sudah terpasang di repo itu.

### Backend

| # | Bug | Perbaikan |
|---|---|---|
| 1 | `routers/attendance.py`: dekorator `@router.post("/corrections")` nyasar menempel ke `get_active_sessions`. Karena terdaftar lebih dulu, setiap POST koreksi dijawab daftar sesi aktif (200) dan **koreksi tidak pernah tersimpan**. | Dekorator nyasar dihapus. |
| 1b | `routers/enrollments.py`: pola yang sama, membuat rute palsu `POST /api/enrollments/corrections`. | Dihapus. |
| 2 | `services/event_ingestion.py`: error di `violation_service.evaluate_event` membuat event yang sudah tersimpan masuk dead letter, dan `record_event` terlewat. `ingest()` juga tidak lagi mengembalikan `bool`. | Evaluasi dibungkus try/except (error di-log), `return inserted` dikembalikan. |
| 3 | `backend/.gitignore` mengabaikan `tests/`, sehingga tes backend tidak ikut commit. | Baris itu dihapus. |
| 4 | `PUT /api/settings/policy` menulis ulang `policy.yaml` dengan `safe_dump`, sehingga semua komentar HRD hilang (sudah terjadi di repo). | `policy_service._render` hanya mengganti nilai di baris `kunci: nilai`. `policy.yaml` dikembalikan berkomentar, dengan nilai tetap 30 / 5 menit. |
| 5 | Email pelanggaran: waktu ditampilkan sebagai epoch mentah, tidak ada tanggal, pemakaian, atau tautan dashboard (D6). | `EmailService.compose_notification`: ID, tanggal, jam lokal kebijakan, pemakaian "x dari y menit", jenis, tautan `DASHBOARD_URL`. Tanpa foto. |

Koreksi atas review sebelumnya: baris "Jenis" di email ternyata **tidak**
kosong. `save_notification` mengembalikan kunci `type`.

Tes baru `backend/tests/test_demo_backend_fixes.py` (8). Tujuh di antaranya
gagal di kode lama dan lulus di kode baru:

- tidak ada rute ganda;
- POST koreksi lewat HTTP: tanpa token 401, dengan token admin tersimpan;
- ingest tetap jalan walau evaluasi gagal;
- pelanggaran dan notifikasi tercatat sekali per orang per hari;
- komentar policy tetap ada;
- isi email lengkap.

Semua tes backend + engine lulus di sandbox. Catatan: tes di sandbox memakai
FastAPI 0.135 dari sumber; PyPI tidak bisa diakses dari sini.

### Frontend

| # | Bug | Perbaikan |
|---|---|---|
| 6 | `composables/useUnidentifiedAlerts.ts` terhapus, padahal masih di-import `UnidentifiedAlertPanel.vue`, sehingga Vite gagal memuat dashboard. | Dikembalikan dari snapshot 4 Okt (memakai `/api/attendance/active`, endpoint masih ada). |
| 7 | Backend sekarang meminta token admin untuk enrollment dan koreksi, tetapi frontend tidak punya login, sehingga **enrollment dari web 401**. | Login minimal (D7): `composables/useAuth.ts` (token di localStorage, `apiFetch` menambah `Authorization: Bearer`, 401 menghapus sesi), `views/LoginView.vue`, rute `/login`, guard `/enrollment` hanya untuk admin, tombol Masuk/Keluar di topbar. Enrollment dan koreksi memakai `apiFetch`. |

Frontend tidak bisa di-build di sandbox (npm diblokir). Bagian `<script>`
sudah diperiksa dengan TypeScript, tetapi template belum. Wajib jalankan
`npm run build` dan coba di browser.

### Cara pakai

```powershell
# .env / env sesi: admin pertama dibuat saat backend start
$env:INITIAL_ADMIN_PASSWORD = "minimal-8-karakter"
python -m pytest backend/tests engine/tests -q
cd frontend; npm run build; cd ..
python scripts/run_demo.py --mode mediamtx --engine-config engine/config/demo-4060.yaml --frontend
```

Buka `http://localhost:5173/enrollment`: diarahkan ke login, masuk sebagai
`admin`, lalu enroll seperti biasa.

### Belum dikerjakan (bukan bug, tapi masih kurang untuk demo)

- Kotak pesan di frontend (SSE `/api/notifications/stream` + badge) dan halaman
  pengaturan (batas jatah, tombol email uji). Backend-nya sudah ada.
- Endpoint GET (pelanggaran, notifikasi, daftar enrollment, policy) masih
  terbuka tanpa login. Tutup sebelum pilot.
- Email gagal kirim tidak dicoba ulang atau dicatat.
- `break_policy.classify` / `SessionDeriver` (model gap lama) hanya dipakai tes.
  Kandidat dihapus.


## 2026-10-04 · paket v14-demo — Perubahan: profil demo GTX 1060 + preflight

*Catatan asli: [`arsip/PERUBAHAN-DEMO-1060.md`](arsip/PERUBAHAN-DEMO-1060.md)*

Isinya kumulatif v14, ditambah profil demo. Perubahan v15 (konversi OpenCV,
scaling_check tiga jalur) sengaja TIDAK ikut, karena versi dibekukan untuk demo.

Dasar: batch_check 4 Okt di GTX 1060 Max-Q, video 848x478:

- M eager 70-75 ms, M graph 70,9 ms;
- S eager 55-59 ms, S graph 48,1 ms (1,17x);
- semua hasil identik.

### Berkas baru

- `engine/config/demo-1060.yaml`: salinan dfine-m-face.yaml dengan D-FINE S,
  `half: false`, `cuda_graph: true`, `fast_preprocess: false`, `target_fps: 8`,
  dan rekognisi async. Tanpa kunci `swscale_resize`, jadi profil ini juga bisa
  dimuat oleh v13.
- `scripts/preflight_demo.py`: mengecek penanda konflik git, config, model
  wajah (ada, bukan pointer LFS), roster, LibreYOLO untuk cuda_graph, MediaMTX
  cam01, port 8765/8000/5173, dan status git. Tidak memuat model ke GPU.
- `docs/DEMO-1060.md`: langkah preflight, gladi A (engine + lag_probe), gladi B
  (run_demo alur lengkap), dan tabel tombol mundur.
- Tes: `test_demo_1060_config.py` (3, mengunci keputusan profil) dan
  `test_preflight_demo.py` (8).

Tidak ada kode engine yang berubah.

### Cara pakai

```powershell
python -m pytest engine/tests -q
python scripts/preflight_demo.py
```

Lalu ikuti docs/DEMO-1060.md.

### Revisi 4 Okt 03:00 (setelah model wajah dipindah ke engine/models/)

- `demo-1060.yaml`: path model dari repo laptop 1060
  (`engine/models/recognition/scrfd_10g_bnkps.onnx`,
  `engine/models/embedder/glintr100.onnx`) dipertahankan.
- `test_demo_1060_config.py`: path file model boleh beda per mesin. Tes
  sebelumnya gagal karena itu, bukan karena perilakunya berubah. Nama file tetap
  harus sama.
- `scripts/check_gpu_env.py`: SCRFD dicari juga di `engine/models/recognition/`.
  Bila tidak ketemu, sekarang muncul PERINGATAN `onnx-sesi`. Dulu barisnya hilang
  diam-diam, dan itulah sebabnya model yang hilang tidak terlihat di laptop 1060.

### Revisi 4 Okt 06:15: profil RTX 4060

- `engine/config/demo-4060.yaml`: D-FINE M, `half: true`, `cuda_graph: true`,
  `fast_preprocess: true`, `target_fps: 10`. Rekognisi, ingest, dan tracker sama
  persis dengan demo-1060.
- `engine/tests/test_demo_4060_config.py` (2).
- `docs/DEMO-1060.md`: bagian "Di laptop RTX 4060".

### Revisi 4 Okt 09:30: engine keluar dari power throttling Windows

Gladi 60 menit di 4060 (`gladi-4060-60m.csv` + log nvidia-smi):

- fps berganti fase antara ±10 dan ±6, beberapa menit per fase;
- di fase 6 fps, umur kotak naik ±0,7 dtk per detik sampai 5-8 dtk lalu jatuh
  tiba-tiba, `lag_s` tetap ±0,03, dan frame yang dibuang pembaca hampir berhenti;
- jadi decode/input yang lebih lambat dari waktu nyata, bukan detector;
- GPU P0 1,6-2 GHz, utilisasi 10-20%, 53 °C: tidak terlibat.

Dugaan: EcoQoS Windows 11 memindah proses yang jendelanya tidak di depan ke
E-core. Laptop 1060 (tanpa E-core) tidak menunjukkan pola ini.

- `engine/runtime/winpower.py` (baru): `SetProcessInformation(ProcessPowerThrottling)`
  dengan StateMask 0, artinya proses engine tidak boleh di-throttle. Bila gagal,
  dicatat dan engine tetap jalan. Selain Windows: tidak ada yang diubah.
- `engine/runtime/__main__.py`: dipanggil saat start. Log menulis
  `power throttling Windows dimatikan (...)`. Opsi `--allow-power-throttling`
  untuk mematikannya.
- Tes: `test_winpower.py` (5).

Proses lain (ffmpeg publisher, MediaMTX) tidak tersentuh. Untuk itu dipakai
`powercfg /powerthrottling disable /path ...` (lihat docs/DEMO-1060.md).


## 2026-10-04 · paket v14 — Perubahan: swscale_resize (YUV -> RGB 640 langsung) + scaling_check

*Catatan asli: [`arsip/PERUBAHAN-SWSCALE-RESIZE.md`](arsip/PERUBAHAN-SWSCALE-RESIZE.md)*

Dasar: bench realtime 1 kamera di 4060, dfine-m (FP16, cuda_graph, fast_preprocess):

| tahap | run b (21:28) | run c (21:41, "Prefer maximum performance") |
|---|---|---|
| frame_convert (YUV -> BGR 1080p) | 15,8 ms | ±16 ms |
| detector_prepare (cv2.resize + cvtColor) | 5,4 | ±5 |
| detector_infer (LibreYOLO + forward) | 24,9 | 29 |
| detector_post | 0,6 | 0,5 |
| tracker | 1,6 | ±2 |

±21 ms CPU per frame hanya untuk membuat RGB 640x640, dan semuanya di thread
kamera. Dikali 5 kamera, itu ±105 ms CPU per putaran frame.

### Perubahan

- `engine/ingest/pyav_source.py`: `LazyFrame.scaled_rgb(w, h)` membuat RGB
  berukuran w x h langsung dari frame terdekode lewat satu panggilan swscale
  (`reformat(..., format="rgb24", interpolation="AREA")`). Hasil di-cache per
  ukuran, dan `image` tidak disentuh. Properti `image` sekarang aman bila
  dipanggil dua thread (rekognisi + kamera).
- `engine/perception/dfine_detector.py`: opsi `swscale_resize` (default false,
  butuh `pre_resize`). `frame_input(frame)` memakai swscale untuk frame lazy yang
  belum dikonversi dan resolusinya >= image_size. Selain itu jalur lama
  `_prepare(frame.image)`. `Prepared(model_input, colour_format, scale)`
  dipakai bersama oleh jalur langsung dan detector bersama.
- `engine/perception/shared_detector.py`: handle menyiapkan input di thread
  kamera (span `detector_prepare`), dispatcher hanya inferensi.
- `engine/pipeline/engine.py`: tidak memaksa konversi BGR sebelum detect bila
  detector `wants_lazy_frames`.
- `engine/ports/frame.py`: `frame_hw(frame)` membaca ukuran dari metadata.
  Pasca-proses D-FINE dan ByteTrack memakainya agar tidak memicu konversi
  1080p hanya untuk tahu ukuran.
- `engine/tools/scaling_check.py` (baru): frame yang sama lewat jalur OpenCV
  dan swscale, membandingkan waktu, beda piksel, dan deteksi di ambang deteksi.
- Config: `detector.swscale_resize: false` di semua yaml.
- `docs/UJI-LAG.md`: langkah 3e.

### Cara uji (4060)

```powershell
python -m pytest engine/tests -q
python -m engine.tools.scaling_check --config engine/config/dfine-m.yaml --source C:\video\uji-siap.mp4 --json bench-out\scaling-4060.json
```

Bila "frame beda di ambang" = 0 dan KESIMPULAN "layak dipakai": set
`swscale_resize: true`, ulangi bench realtime. Harapan: `frame_convert` hilang,
`detector_prepare` ±2-4 ms.

Piksel swscale tidak identik dengan cv2.INTER_AREA, jadi deteksi bisa bergeser
tipis. Karena itu default tetap false sampai scaling_check di data sungguhan
bilang aman.

Tes: test_swscale_resize.py (15). Suite engine lulus.


## 2026-10-03 · paket v13 — Perubahan: rincian span detector di bench

*Catatan asli: [`arsip/PERUBAHAN-RINCIAN-SPAN-DETECTOR.md`](arsip/PERUBAHAN-RINCIAN-SPAN-DETECTOR.md)*

Dasar: `engine.bench --mode realtime` di 4060 (3 Okt 21:28), config dfine-m
(FP16, cuda_graph, fast_preprocess):

| tahap | rata-rata | p95 |
|---|---|---|
| detector | 58,2 ms | 65,1 |
| tracker (iou) | 1,9 | 2,8 |
| zoning/listeners/sinks | < 0,2 | |
| total_pipeline | 81,9 | 100,4 |
| pacing_wait | 17,2 | 33,0 |

fps tepat 12,0 (= target), tetapi total 82 ms dari anggaran 83 ms: tidak ada
sisa. Span "detector" 58 ms, sedangkan batch_check (frame sudah ndarray) 14-21
ms. Selisih ±40 ms tidak terlihat dari mana.

### Perubahan

- `engine/pipeline/engine.py`: frame lazy (PyAV) dikonversi sebelum detector di
  span baru `frame_convert`; span `detector` tetap mencakupnya (sebanding dengan
  angka lama). Span tambahan dari `detector.last_spans` dicatat.
- `engine/perception/dfine_detector.py`: `detector_prepare` (pre_resize OpenCV),
  `detector_infer` (LibreYOLO: pra-proses + forward + pasca-proses LibreYOLO,
  diakhiri .cpu()), `detector_post` (Results -> Detection).
- `engine/perception/shared_detector.py` (runtime): `detector_shared_infer`
  (antre + inferensi di thread dispatcher) dan `detector_post`.

Tes: test_detector_spans.py (2), test_cuda_graph_batch.py +1. Suite lulus.


## 2026-10-03 · paket v12 — Perubahan: batch_check membandingkan pada ambang deteksi

*Catatan asli: [`arsip/PERUBAHAN-BATCH-CHECK-AMBANG-DETEKSI.md`](arsip/PERUBAHAN-BATCH-CHECK-AMBANG-DETEKSI.md)*

Dasar: 4060 20:24.
- FP32 + cuda_graph + fast_preprocess: 24,8 ms, IoU 1,000, Δskor 0 -> pra-proses GPU
  terbukti bit-identik. (Pembanding eager 180,5 ms: laptop sedang panas lagi;
  dingin = 17,6 ms.)
- FP16 + graph + fast vs pembanding FP32: 2 dari 60 gambar "salah", IoU min 0,000,
  Δskor 1,000 = jumlah kotak berbeda, vonis "BATCH MENGUBAH HASIL".

Dua masalah di alatnya:
1. Vonis menyebut "BATCH" padahal ukuran 1; yang berubah adalah FP16.
2. Kotak yang dibandingkan adalah SEMUA kotak, termasuk skor rendah (± raw_confidence
   0,1) yang hanya dipakai ByteTrack tahap kedua. Satu kotak 0,11 vs 0,09 sudah
   membuat gambar "salah" dengan IoU 0 dan Δskor 1, tanpa menyebut skornya.

### Perubahan (`engine/tools/batch_check.py`)

- `compare_detail(ref, cand, min_conf)`: kotak >= ambang deteksi (`detector._conf`,
  0,50 di config) WAJIB punya pasangan; pasangannya boleh sedikit di bawah ambang
  (toleransi 0,02) supaya 0,505 vs 0,495 tidak dihitung hilang. Pencocokan dua arah.
- Kolom baru: `beda-semua` (termasuk kotak skor rendah, informasi) dan `skor-maks`
  (skor tertinggi kotak tanpa pasangan) -> langsung terlihat apakah yang berbeda
  kotak penting atau kandidat ByteTrack.
- Vonis "HASIL BERUBAH pada ambang deteksi X (N gambar)" untuk batch / half /
  cuda_graph / fast_preprocess.
- docs/UJI-LAG.md diperbarui.

Tes: test_batch_check.py +3. Suite: 560 passed, 7 skipped.


## 2026-10-03 · paket v11 — Perubahan: pra-proses GPU bit-identik + batch_check --reference-fp32

*Catatan asli: [`arsip/PERUBAHAN-PRA-PROSES-GPU-BIT-IDENTIK_PEMBANDING-FP32.md`](arsip/PERUBAHAN-PRA-PROSES-GPU-BIT-IDENTIK_PEMBANDING-FP32.md)*

Dasar: batch_check 4060 20:13 dan 20:17 (cuda_graph + fast_preprocess):

| | ms/gambar | IoU min | Δskor |
|---|---|---|---|
| FP32 | 17,6 (dari 28,5) | 0,989 | 0,006 |
| FP16 | 14,4 | 1,000* | 0,000* |

*pembanding juga FP16, jadi FP16 vs FP32 belum terukur.

### 1. Selisih 1 ulp di GPU

Tes CPU membuktikan tensor identik, tetapi di GPU `div_(255.0)` dikerjakan
PyTorch sebagai kali kebalikan dan meleset 1 ulp untuk sebagian nilai -> IoU
0,989 di FP32. Sekarang normalisasi memakai tabel 256 nilai `float32(i)/255`
yang dihitung numpy (`_normalise_lut`), diindeks di GPU: identik dengan
pra-proses LibreYOLO, tetap tanpa salinan float di CPU.

Tes yang ditambahkan di berkas tes (test_tensor_di_gpu_juga_sama_persis,
test_lut_sama_dengan_pembagian_numpy) dipertahankan dan kini lulus; tes duplikat
dariku dibuang.

### 2. batch_check --reference-fp32

Pembanding dijalankan FP32 walau kandidat `--half`, sehingga "salah"/IoU/Δskor
mengukur selisih FP16 terhadap FP32. Status half dipulihkan sesudahnya.

Tes: 557 passed, 7 skipped di sini (tes ber-torch/CUDA jalan di laptop uji).


## 2026-10-03 · paket v10 — Perubahan: detector.fast_preprocess (pra-proses frame di GPU)

*Catatan asli: [`arsip/PERUBAHAN-PRA-PROSES-GPU.md`](arsip/PERUBAHAN-PRA-PROSES-GPU.md)*

Dasar: batch_check 4060 dingin, cuda_graph: D-FINE M 28,5 ms, S 25,2 ms per
gambar (end-to-end). Forward M dengan graph ±12,6 ms. S hanya 12% lebih cepat
walau FLOPs-nya < setengah M -> sisa ±13-16 ms bukan model, melainkan pra/pasca-
proses LibreYOLO di CPU yang sama untuk semua ukuran. Mengganti M ke S tidak
sepadan dengan turunnya akurasi.

### Pra-proses LibreYOLO untuk input numpy (dibaca dari kode 1.6.0)

ImageLoader.load (numpy -> PIL) -> img.copy() -> np.array -> PIL.fromarray ->
resize -> float32/255 -> transpose CHW -> torch.from_numpy -> .to(cuda) (4,9 MB
float). Dengan `pre_resize: true` frame sudah RGB 640x640, dan resize PIL ke
ukuran yang sama adalah salinan polos (diverifikasi: identik), jadi input model
= uint8/255 dalam CHW.

### Perubahan

- `engine/perception/dfine_detector.py`: `fast_preprocess` + `install_fast_preprocess()`:
  memasang `_preprocess_predict` di instance model LibreYOLO (hook resmi yang dipakai
  InferenceRunner). Frame uint8 RGB berukuran persis image_size -> upload 1,2 MB
  uint8 ke GPU, float/255, CHW. Selain itu (BGR, ukuran lain, bukan uint8, kwargs
  tambahan) -> pra-proses LibreYOLO asli. Bisa dimatikan per panggilan.
- Config: `detector.fast_preprocess` (default false) di schema/loader/factory dan
  semua yaml. Butuh `pre_resize: true` (diperingatkan bila tidak).
- `engine/tools/batch_check.py`: `--fast-preprocess`; pembanding selalu PIL + eager;
  mencetak jumlah frame yang lewat jalur cepat; vonis menyebut akselerasi yang aktif.
- `docs/UJI-LAG.md`: langkah 3d.

### Tes

test_cuda_graph_batch.py +4: kasus yang tidak boleh disentuh, fallback hook, dan
dua tes yang butuh torch/LibreYOLO (di-skip di CI tanpa torch, JALAN di laptop uji):
tensor wajib `torch.equal` dengan `preprocess_image` LibreYOLO.
Suite di sini: semua lulus (2 skip karena tanpa torch).

### Revisi v11 (uji 4060 20:13)

Hasil v10: D-FINE M cuda_graph + fast_preprocess 17,6 ms/gambar (dari 28,5),
salah 0, TETAPI IoU min 0,989 / Δskor 0,006 -- tidak bit-identik. Tes CPU lulus,
jadi bedanya di GPU: PyTorch CUDA membagi dengan skalar lewat perkalian
kebalikan (beda 1 ulp). Sekarang normalisasi memakai tabel lookup 256 nilai
float32 yang dihitung numpy persis seperti LibreYOLO -> identik di CPU dan GPU.
Tes baru `test_tensor_di_gpu_juga_sama_persis` (jalan bila ada CUDA).


## 2026-10-03 · paket v9 — Perubahan: tes async rekognisi tidak lagi bergantung kecepatan mesin

*Catatan asli: [`arsip/PERUBAHAN-TES-ASYNC-BERBASIS-THREAD.md`](arsip/PERUBAHAN-TES-ASYNC-BERBASIS-THREAD.md)*

`test_async_loop_frame_tidak_tertahan_recognizer_lambat` gagal di Windows/4060
(3 Okt 19:56): async 4410 frame vs sync 1961 = 2,25x, padahal tes meminta > 3x.
Bukan regresi: async memang 2,25x lebih cepat, tetapi rasio itu bergantung pada
seberapa cepat loop mock berputar dibanding rekognisi 50 ms, jadi berbeda per
mesin.

Tes sekarang membuktikan hal yang sebenarnya dijanjikan async: recognizer TIDAK
pernah dipanggil di thread kamera (`camera-cam01`), sedangkan di mode sync
selalu di sana. Ditambah async > sync (tanpa angka ajaib) dan async tetap
mengidentifikasi orangnya.

Berkas: engine/tests/test_recognition_worker.py. Suite: 553 passed, 3 skipped.


## 2026-10-03 · paket v8 — Perubahan: engine API tidak lagi tertahan backend lama yang macet (Windows)

*Catatan asli: [`arsip/PERUBAHAN-ENGINE-API-KUNCI-TULIS-PER-KONEKSI.md`](arsip/PERUBAHAN-ENGINE-API-KUNCI-TULIS-PER-KONEKSI.md)*

Dasar: `pytest engine/tests` di Windows 3 Okt 19:40, satu gagal:
`test_backend_lama_yang_macet_tidak_mengunci_handshake_baru` (TimeoutError).

### Masalah (nyata di produksi Windows, bukan hanya tes)

Backend lama berhenti membaca -> thread kirim engine tertahan di `sendall` sambil
memegang SATU kunci tulis global. Backend baru tersambung -> engine memutus
koneksi lama (`shutdown`) lalu menulis hello_ack di bawah kunci yang sama.
Di Linux `shutdown` membangunkan `sendall` yang tertahan; di Windows TIDAK.
Akibatnya backend yang reconnect setelah macet menunggu sampai batas kirim habis
(15 dtk di produksi, 60 dtk di tes) sebelum menerima hello_ack, dan thread kirim
tunggal juga tidak bisa mengirim event ke koneksi baru selama itu.

### Perbaikan (`engine/api/server.py`)

- Kunci tulis PER KONEKSI (`_lock_for(connection)`, WeakKeyDictionary), bukan
  global. Penulis ke koneksi lama hanya menahan koneksi lama.
- Thread kirim PER KONEKSI, dibuat saat handshake selesai, berhenti begitu
  generasinya lewat. Thread lama yang macet di `sendall` hanya menahan dirinya
  sendiri sampai batas kirim, lalu berhenti.
- View lama dibuang saat handshake baru (dulu dibuang oleh thread kirim tunggal
  selama tidak ada koneksi).
- Urutan tetap: hello_ack + gap ditulis dan koneksi/kursor dipasang di bawah
  kunci koneksi baru SEBELUM thread kirimnya dimulai, jadi tidak ada event yang
  mendahului hello_ack.

### Tes

Baru: `test_sendall_yang_tidak_terbangun_seperti_windows_tidak_menahan_backend_baru`
mensimulasikan perilaku Windows di Linux (koneksi lama tidak dibangunkan).
GAGAL dengan server lama, LULUS dengan yang baru.
Suite: 553 passed, 3 skipped (unix socket) dan 553 passed (ENGINE_TEST_TCP=1).


## 2026-10-03 · paket v7 — Perubahan: tes jalan di Windows, detector tidak dimuat ulang tiap retry, vonis batch_check

*Catatan asli: [`arsip/PERUBAHAN-TES-WINDOWS_DETECTOR-SEKALI-MUAT_VONIS-BATCH.md`](arsip/PERUBAHAN-TES-WINDOWS_DETECTOR-SEKALI-MUAT_VONIS-BATCH.md)*

Dasar: `pytest engine/tests` dan `batch_check --cuda-graph` di laptop RTX 4060
(Windows, LibreYOLO 1.6), 3 Okt 19:28.

### 1. 16 tes soket gagal di Windows (bukan karena upgrade)

`socket.AF_UNIX` tidak ada di Python Windows; tes protokol memakai unix socket.
Engine di Windows memang lewat TCP. Baru: `engine/tests/_transport.py` memakai
unix socket bila ada dan TCP 127.0.0.1 port acak bila tidak, jadi tes yang sama
menguji jabat tangan, replay, auth, dan batas kirim lewat TCP di Windows (tidak
dilewati). `ENGINE_TEST_TCP=1` memaksa jalur TCP di Linux; kedua mode lulus.
Diubah: test_api.py, test_api_connection.py, test_engine_phase1.py.

### 2. BUG: kamera mati = bobot D-FINE dimuat ulang tiap percobaan

Akibat urutan start baru (detector dulu, lalu stream): bila sumber gagal dibuka,
detector yang baru dimuat di `factory.build_engine` ikut hilang bersama
exception, dan percobaan ulang berikutnya memuat bobot lagi (10+ dtk di 4060,
±55 dtk di 1060). Tes `test_failed_camera_is_reopened` gagal di Windows karena
ini (dengan LibreYOLO terpasang). Perbaikan di `engine/runtime/camera.py`:
detector dibuat dan disimpan di supervisor sebelum `build_engine` membuka
sumber. Tes kini memakai MockDetector dan memastikan detector dibuat SEKALI
walau sumber gagal berulang. (Jalur detector bersama tidak terdampak.)

### 3. Vonis batch_check menyesatkan

Hasil 4060: tanpa batch, eager 206,8 ms; dengan cuda_graph ukuran 1 = 29,5,
ukuran 2 = 34,3, ukuran 5 = 53,4 ms/gambar. Vonis lama: "layak dinyalakan
(batch_inference: true, max_batch: 1)". Ukuran 1 bukan batch; percepatannya dari
cuda_graph. Vonis baru membandingkan batch dengan ukuran 1 (bukan dengan eager)
dan berbunyi "batch TIDAK membantu, biarkan batch_inference: false;
cuda_graph: true layak dipakai".

### Tes

552 passed, 3 skipped (unix socket) dan 552 passed, 3 skipped (ENGINE_TEST_TCP=1).


## 2026-10-03 · paket v6 — Perubahan: requirements engine per GPU (termasuk PyTorch) + pemeriksa env

*Catatan asli: [`arsip/PERUBAHAN-REQUIREMENTS-GPU.md`](arsip/PERUBAHAN-REQUIREMENTS-GPU.md)*

- `engine/requirements-torch-cu126.txt`: torch 2.14.1+cu126, torchvision 0.29.1+cu126
  (extra index download.pytorch.org/whl/cu126, versi lokal dipatok persis).
- `engine/requirements-gpu.txt`: torch cu126 + engine dasar + libreyolo>=1.6,<2 +
  onnxruntime-gpu[cuda,cudnn]<1.27 + pytest.
- `engine/requirements-gpu-rtx4060.txt`, `-rtx3050.txt`, `-gtx1060.txt`: masing-masing
  `-r requirements-gpu.txt` + config yang disarankan untuk GPU itu.
- `scripts/check_gpu_env.py`: OK/PERINGATAN/GAGAL untuk python, torch (CPU-only?),
  arsitektur GPU vs build, matmul CUDA, libreyolo, onnxruntime (CUDA 13 di env CUDA 12,
  paket CPU+GPU ganda, sesi CUDA sungguhan bila model SCRFD ada), PyAV, OpenCV, driver,
  xformers.
- `docs/SETUP-GPU.md`, `README.md`: cara pasang dan alasan versi.
- Tes: `engine/tests/test_check_gpu_env.py` (10). Suite: 550 passed, 3 skipped.

Paket ketiga GPU sengaja sama: cu126 satu-satunya build torch yang membawa
kernel Pascal (2.14 rilis terakhirnya), dan onnxruntime-gpu < 1.27 juga CUDA 12.


## 2026-10-03 · paket v5 — Perubahan: CUDA graph + batch sungguhan untuk D-FINE (LibreYOLO >= 1.6)

*Catatan asli: [`arsip/PERUBAHAN-CUDA-GRAPH-BATCH-SUNGGUHAN.md`](arsip/PERUBAHAN-CUDA-GRAPH-BATCH-SUNGGUHAN.md)*

Dasar: detector_profile v4 di RTX 4060 (3 Okt 18:28).

| | ms |
|---|---|
| panggilan LibreYOLO penuh (eager) | 85,9 |
| forward eager FP32 / FP16 | 57,2 / 64,8 |
| forward batch 5 langsung, per gambar | 15,0 |
| forward CUDA graph | 12,6 |
| kernel GPU sungguhan per gambar (tabel torch.profiler) | ±10 |

±1000-1400 peluncuran kernel per gambar, ±20 us masing-masing; GPU menganggur
±85% waktu. Saat CUDA graph/batch berjalan, nvidia-smi pertama kali menunjukkan
GPU bekerja sungguhan: 2460 MHz, 97%, 79 W.

### Temuan di kode LibreYOLO (1.6.0, rilis 27 Sep 2026)

- `predict(cuda_graph=True|"auto")`: forward diputar dari CUDA graph, D-FINE
  `SUPPORTS_CUDA_GRAPH = True`, diverifikasi bit-identik oleh LibreYOLO. Satu
  graph per bentuk input (maks 8 di cache).
- `predict(list, batch=N)`: SATU forward bertumpuk per potongan N gambar.
  Daftar gambar TANPA `batch=` diproses satu per satu. Itu sebabnya batch_check
  hanya 1,1x: adapter kita mengirim daftar tanpa `batch=`.

### Perubahan

- `engine/perception/dfine_detector.py`: param `cuda_graph` (false/true/"auto",
  mati di CPU); `_call()` meneruskan `cuda_graph=`; LibreYOLO yang menolaknya
  (1.5) -> satu peringatan, kembali eager. `_try_batch` mengirim
  `batch=len(daftar)`. Versi LibreYOLO dicatat di log saat model dimuat.
- `engine/config/schema.py`, `loader.py`, `factory.py`, semua `engine/config/*.yaml`:
  `detector.cuda_graph` (default false).
- `engine/tools/batch_check.py`: `--cuda-graph`; pembanding selalu eager tanpa
  batch sehingga graph yang mengubah hasil tertangkap sebagai "salah".
- `engine/tools/detector_profile.py`: waktu sibuk GPU hanya menghitung event
  perangkat (v4 menghitung kernel dua kali: 51,8 ms, padahal ±10 ms). Vonis
  "PENGHAMBAT DI GPU" v4 di 4060 karena bug ini.
- `engine/requirements-dfine.txt`: catatan >= 1.6 (pin tetap >= 1.5).
- `docs/UJI-LAG.md`: langkah 3c.

### Tes

test_cuda_graph_batch.py (14), test_detector_profile.py diperbarui.
Seluruh suite: 541 passed, 3 skipped; policy_grep bersih.


## 2026-10-03 · paket v3–v4 — Perubahan: alat profil detector (GPU vs CPU) + batch_check --no-half

*Catatan asli: [`arsip/PERUBAHAN-PROFIL-DETECTOR-GPU-VS-CPU.md`](arsip/PERUBAHAN-PROFIL-DETECTOR-GPU-VS-CPU.md)*

Dasar: uji RTX 4060 3 Okt langkah 0-3.

- ingest_ceiling (--work torch 110 ms): semua varian latest 94-95% dari harapan,
  decode 32 fps (sumber 30 fps) -> ingest BUKAN penghambat di 4060.
- batch_check: D-FINE M 84 ms/gambar, sama dengan GTX 1060. "FP16" vs "tanpa
  --half" identik karena config lokal sudah `half: true` (baris `half True` di
  kedua run), jadi FP32 belum pernah diukur. cudnn.benchmark: 0%. Batch 5:
  1,10x, benar (IoU 1,000).

Waktu yang tidak turun saat GPU diganti, tidak turun saat batch, hampir pasti
bukan waktu GPU. Alat baru memisahkannya.

### Baru: engine/tools/detector_profile.py

    python -m engine.tools.detector_profile --source C:\video\uji-siap.mp4 --torch-profile bench-out\profil-4060.txt --json bench-out\profil-4060.json

Mengukur pre_resize, panggilan LibreYOLO penuh (dengan cuda.synchronize),
forward GPU murni modul torch di dalam LibreYOLO (FP32 dan FP16, tensor sudah di
GPU), letak parameter model (cuda/cpu), dan clock/P-state/daya GPU via
nvidia-smi selama pengukuran. Vonis: PENGHAMBAT DI CPU / DI GPU / GPU TIDAK NAIK
CLOCK / MODEL DI CPU. `--torch-profile` menulis tabel operasi terberat.

### engine/tools/batch_check.py

`--no-half` memaksa FP32 apa pun isi config (eksklusif dengan `--half`).

### docs/UJI-LAG.md

Langkah 2 memakai `--no-half`; langkah baru 3b (detector_profile).

### Tes

test_detector_profile.py (7). Seluruh suite: 524 passed, 3 skipped; policy_grep bersih.

### Revisi v4 (setelah profil pertama di 4060, 18:02)

Vonis v3 "PENGHAMBAT DI GPU" SALAH. Forward "GPU murni" di PyTorch eager tetap
dibayar CPU: setiap op diluncurkan satu per satu dari Python. Data 4060:

- forward FP32 56,6 ms, tetapi kernel GPU hanya ±29,7 ms per gambar
  (torch.profiler: Self CUDA 297 ms / 10 gambar),
- ±1000 peluncuran kernel per gambar, cudaLaunchKernel 19 us masing-masing
  (CPU 191 ms / 10 gambar hanya untuk meluncurkan),
- utilisasi GPU 23-40%, daya 13-18 W, clock turun karena GPU menganggur,
- FP16 lebih LAMBAT (63,5 ms): autocast menambah op cast = lebih banyak peluncuran.

Alat sekarang juga mengukur: waktu sibuk GPU + jumlah peluncuran per forward,
forward batch 5 langsung ke modul (apakah batch sungguhan menolong), dan forward
yang direkam sebagai CUDA graph (perkiraan kecepatan tanpa overhead peluncuran).
Vonis baru: "TERIKAT CPU (peluncuran kernel)"; clock rendah dilaporkan sebagai
akibat bila GPU menganggur.

Tes: test_detector_profile.py 10 (memakai angka asli 4060).


## 2026-10-03 · paket v2 — Detector bersama antar-kamera, batching opsional, optimasi untuk RTX 4060 (3 Okt 2026)

*Catatan asli: [`arsip/PERUBAHAN-DETECTOR-BERSAMA-BATCHING-OPTIMASI-4060.md`](arsip/PERUBAHAN-DETECTOR-BERSAMA-BATCHING-OPTIMASI-4060.md)*

**Paket kumulatif.** Menggantikan semua paket sebelumnya sejak zip Engine B "stream live dan detector".
Ekstrak di root proyek di atas zip Engine B itu. Paket yang sudah tercakup:

- engineA-engineB_batas-thread-cpu_nvdec-opsional_rekognisi-async_koreksi-jam
- perbaikan-lag-probe_crash-engine-lambat-mulai
- perbaikan-urutan-start_detector-dimuat-sebelum-stream-dibuka
- setup-uji-rekognisi-wajah_config-face-async-sync_log-worker
- perbaikan-onnxruntime-cuda12-pascal_tolak-rekognisi-diam-diam-cpu
- perbaikan-engine-bisa-dihentikan_ctrl-c-q-penjaga-waktu

Termasuk juga `engine/api/server.py`: `accept()` menunggu dalam potongan 0,5 dtk, sehingga Ctrl+C tetap
jalan saat engine menunggu backend. Tesnya ada di `engine/tests/test_shutdown.py`.

Verifikasi: 511 tes engine+contracts lulus (3 dilewati), integration smoke lulus, policy_grep bersih.
Disetujui Engine B (detector bersama + batching).

### 1. Detector bersama (`engine/perception/shared_detector.py`, baru)

- Satu D-FINE untuk semua kamera.
  - Sebelumnya: 5 kamera = 5 salinan bobot, 5× waktu muat (±55 dtk masing-masing di 1060), dan 5 thread
    memanggil model tanpa koordinasi.
- Hanya satu thread dispatcher yang memanggil model. Kamera mengirim frame lalu menunggu hasil.
- Setiap kamera mendapat `DetectorHandle` dengan `last_result` sendiri, supaya ByteTrack kamera A tidak
  membaca hasil kamera B.
- Batching: setelah permintaan pertama, dispatcher menunggu paling lama `batch_wait_ms` untuk kamera lain.
  Bila hanya satu kamera aktif, ia tidak menunggu.
- Kepercayaan yang berbeda (predict_raw ByteTrack) tidak digabung dalam satu panggilan.
- Detector yang tidak bisa dibagi (MockDetector) tetap dimuat per kamera seperti dulu.
- Runtime memuat detector bersama saat kamera pertama dibuka, memanaskannya, lalu membagikan handle.
  Handle dilepas saat kamera ditutup.
- Log setiap laporan health: `detector bersama: N kamera, X gambar dalam Y panggilan (rata2 .../panggilan)`.

### 2. Batching di `DFINEDetector` (berkas Engine B)

- `predict_images(images)` mengembalikan satu Results per gambar, berurutan.
- Dengan `batch_inference: true`, dicoba `model(list)`. Bila LibreYOLO menolak atau tidak mengembalikan
  satu hasil per gambar, adapter memberi peringatan SEKALI lalu menjalankan per gambar.
  Menyalakan tombol ini tidak pernah menghasilkan kotak yang salah urut.
- Gambar dengan format warna berbeda (sebagian di-pre_resize, sebagian tidak) tidak dibatch.
- `detect()` dipecah menjadi `_predict` dan `postprocess` (pure, aman dari thread kamera mana pun).

### 3. Optimasi kecil

- Inferensi D-FINE selalu di bawah `torch.no_grad()`.
  - Sebelumnya tidak ada `no_grad` di sisi engine.
  - Bukan `inference_mode`, karena tensor Results masih diubah di rescale_result dan ByteTrack.
- `detector.cudnn_benchmark` (default false): cuDNN memilih algoritma tercepat untuk input 640 yang tetap.
- `recognition.onnx_gpu_mem_limit_mb` (default kosong): batas VRAM arena onnxruntime dengan strategi
  `kSameAsRequested`, untuk GPU 8 GB yang dipakai bersama PyTorch.

### 4. Alat dan dokumen

- `engine/tools/batch_check.py` (baru):
  - Membandingkan hasil batch vs per gambar (jumlah kotak, IoU, skor) dan ms/gambar per ukuran batch.
  - Opsi `--half` / `--cudnn-benchmark`.
  - Kesimpulan: "BATCH MENGUBAH HASIL" / "tidak menerima batch" / "layak dinyalakan".
- `docs/UJI-LAG.md`: bagian "Uji di RTX 4060" (langkah 0–4, termasuk 5 kamera) dan baris tombol mundur baru.

### Config baru (semua YAML di engine/config diperbarui)

```yaml
detector:
  cudnn_benchmark: false
  share_across_cameras: true
  batch_inference: false
  max_batch: 8
  batch_wait_ms: 4.0
recognition:
  onnx_gpu_mem_limit_mb: null
```

### Tombol mundur

- `detector.share_across_cameras: false`
- `detector.batch_inference: false`
- `detector.cudnn_benchmark: false`

### Tes baru

- `test_shared_detector.py` (16), termasuk ujung ke ujung dua kamera di runtime.
- `test_batch_check.py` (4).
- `test_onnx_provider_check.py` +2.

### Belum diuji di GPU

- Batching LibreYOLO yang sesungguhnya.
- FP16 di 4060.
- 5 kamera.

Semuanya ada di `docs/UJI-LAG.md` bagian "Uji di RTX 4060".


## 2026-10-03 · paket v2 — Perubahan: koreksi jam P18 asimetris + probe tidak tertipu median

*Catatan asli: [`arsip/PERUBAHAN-KOREKSI-JAM-ASIMETRIS_PROBE-LONJAKAN.md`](arsip/PERUBAHAN-KOREKSI-JAM-ASIMETRIS_PROBE-LONJAKAN.md)*

Dasar: uji RTX 4060 (lag-A-latest-half.csv, lag-B-none-half.csv), direkam SEBELUM
paket kumulatif 3 Okt. Paket ini ditumpuk DI ATAS paket kumulatif
`engineA-engineB_kumulatif-3okt_detector-bersama-batching_optimasi-4060.zip`.

### 1. engine/runtime/clock.py — bias positif tidak lagi "dikoreksi" cepat

Temuan di run A (latest): saat fps jatuh ke 2,9, sisa bias naik ke +0,51 dtk
(semua frame tiba terlambat = thread pembaca tertinggal). Korektor menyapunya
dalam ±5 dtk (0,51 -> 0,04). Saat antrean terkuras, bias aslinya muncul lagi
sebagai -0,41/-0,47 dan harus dikoreksi balik. Dua kali salah; selama itu `at`
event ±0,5 dtk terlalu awal dan umur frame di probe terlihat lebih segar dari
kenyataan.

Offset diambil dari waktu tiba frame pertama, jadi kesalahan offset hanya bisa
membuat `at` MENDAHULUI kenyataan (bias negatif). Bias positif = delay
sungguhan. Sekarang:

- bias negatif: tetap 0,1 dtk/dtk (seperti sebelumnya),
- bias positif: maksimal `max_rate_late` = 0,002 dtk/dtk (2000 ppm). Cukup untuk
  mengejar drift kristal kamera (puluhan ppm), terlalu lambat untuk menyapu
  antrean beberapa detik.

Rollback: `OffsetCorrector(max_rate_late=0.1)` di camera.py = perilaku lama.

### 2. scripts/lag_probe.py — ringkasan tidak lagi bilang "SEGAR" saat ada lonjakan

Run A diringkas "engine SEGAR dan stabil" padahal umur sempat 6,16 dtk dan fps
jatuh ke 2,3. Sekarang ringkasan menambah p95/maks umur, min/maks fps, dan
PERINGATAN untuk: umur > 2 dtk, fps < 60% median, sisa bias positif > 0,3 dtk.
Bila median segar tetapi ada peringatan: "median SEGAR tetapi TIDAK STABIL".

Ringkas ulang CSV lama: `python scripts/lag_probe.py --summarize lag-A-latest-half.csv`

### Tes

- test_offset_correction.py: +3 tes (bias positif hampir tidak digeser, drift
  kristal 100 ppm tetap terkejar selama 3 jam, bias negatif tetap cepat) +2
  parameter ditolak.
- test_lag_probe.py: +1 tes (median segar + lonjakan -> TIDAK STABIL).
- Seluruh suite: 517 passed, 3 skipped.


## 2026-10-03 — Urutan start kamera: detector dimuat dulu, baru stream dibuka (3 Okt 2026)

*Catatan asli: [`arsip/PERUBAHAN-URUTAN-START-DETECTOR-DULU.md`](arsip/PERUBAHAN-URUTAN-START-DETECTOR-DULU.md)*

Ekstrak di root proyek di atas paket `engineA-engineB_batas-thread-cpu_nvdec-opsional_rekognisi-async_koreksi-jam`
(dan `perbaikan-lag-probe_crash-engine-lambat-mulai`). Verifikasi: 481 tes engine+contracts lulus, smoke lulus,
policy_grep bersih.

### Temuan dari uji GTX 1060 (`lag-B-none.csv`)
Kamera online pada detik 61. Frame pertama yang dianalisis berumur 58,5 dtk, dan 5 dtk kemudian
`camera.failed stream_reconnected`.

### Penyebab
- `factory.build_engine` memanggil `resolve_source_fps`, yang MEMBUKA stream untuk membaca fps.
- Pembukaan itu terjadi sebelum `build_detector` memuat bobot dan sebelum warmup CUDA (±55 dtk di 1060).
- Selama itu RTSP terbuka tetapi tidak dibaca:
  - `live_buffer: none`: antrean socket menumpuk, lalu MediaMTX memutus pembaca yang lambat.
  - `live_buffer: latest`: thread pembaca men-decode sia-sia selama model dimuat.
- Offset jam ditetapkan saat stream dibuka, sehingga `at` frame awal salah sebesar waktu muat model.
- Dengan 5 kamera, ini terjadi di setiap kamera.

### Perbaikan (`engine/factory.py`, berkas bersama EB)
- Detector dimuat lalu dipanaskan dulu, baru sumber dibuka dan fps dibaca.
- `VisionEngine.start` tetap memanaskan lagi; biayanya satu inferensi tambahan.
- Detector yang sudah ada (reconnect / loop file) tidak dimuat atau dipanaskan ulang.
- Efek samping: config sumber yang salah (fps tidak terbaca) sekarang ketahuan setelah model dimuat, bukan
  sebelumnya. Penolakannya tetap terjadi.

### Tes
- Baru: `engine/tests/test_startup_order.py` (2).
- `engine/tests/test_b0_port.py::test_source_with_unknown_fps_is_refused_not_guessed` sekarang memakai
  detector tiruan, karena urutannya berubah. Yang diuji tetap penolakan fps.

### Catatan untuk Engine B (belum diubah)
- Setiap `CameraSupervisor` memuat detector-nya sendiri: 5 kamera berarti 5 salinan D-FINE di GPU dan
  5× waktu muat.
- Berbagi satu detector (atau batching) adalah keputusan desain untuk tahap 5 kamera.


## 2026-10-03 — Setup uji rekognisi wajah tanpa roster (3 Okt 2026)

*Catatan asli: [`arsip/PERUBAHAN-SETUP-UJI-REKOGNISI-WAJAH.md`](arsip/PERUBAHAN-SETUP-UJI-REKOGNISI-WAJAH.md)*

Ekstrak di root proyek di atas paket `perbaikan-urutan-start_detector-dimuat-sebelum-stream-dibuka`.
Verifikasi: 481 tes lulus, policy_grep bersih.

### Isi
- `engine/config/dfine-m-face.yaml` dan `dfine-m-face-sync.yaml`
  - Salinan `dfine-m.yaml` dengan rekognisi menyala (SCRFD 10G + glintr100, CUDA).
  - Bedanya hanya `recognition.execution` (async vs sync), untuk uji C.
- `engine/runtime/service.py`
  - Statistik worker rekognisi sekarang dicetak di level INFO setiap laporan health:
    `rekognisi: diproses N, ditolak-penuh N, basi N, gagal N, rata2 X ms, antre N`.
  - Sebelumnya hanya DEBUG, sehingga tidak terlihat. Dengan roster kosong, baris ini satu-satunya
    bukti bahwa SCRFD dan AuraFace benar-benar jalan.
  - Mode sync tidak punya worker, jadi baris ini tidak muncul di mode sync.


## 2026-10-03 — Perbaikan lag_probe: crash saat engine lambat mulai (3 Okt 2026)

*Catatan asli: [`arsip/PERUBAHAN-PROBE-CRASH-ENGINE-LAMBAT-MULAI.md`](arsip/PERUBAHAN-PROBE-CRASH-ENGINE-LAMBAT-MULAI.md)*

Ekstrak di root proyek di atas paket `engineA-engineB_batas-thread-cpu_nvdec-opsional_rekognisi-async_koreksi-jam`.

### Gejala
`TypeError: unsupported format string passed to NoneType.__format__` di akhir probe 5 menit.

### Penyebab
- Jendela "awal" dihitung dari saat probe dibuka (0–60 dtk). Di GTX 1060, `view.frame` pertama
  baru datang setelah lebih dari 60 dtk (muat D-FINE + warmup CUDA).
- Akibatnya median awal = None dan format `:.2f` crash. CSV tetap tersimpan, karena ditulis sebelum
  ringkasan dibuat.

### Perbaikan (`scripts/lag_probe.py`)
- Jendela awal sekarang dihitung dari `view.frame` pertama.
- Ringkasan mencetak "view.frame pertama pada detik N probe; X sampel".
- Nilai kosong dicetak "-", tidak lagi crash.
- Baru: `--summarize CSV` untuk meringkas ulang hasil lama tanpa mengulang uji.

  ```
  python scripts/lag_probe.py --summarize bench-out/lag-A-latest.csv
  ```

Tes: `engine/tests/test_lag_probe.py` +1 (reproduksi kasus lapangan + ringkas ulang CSV).


## 2026-10-03 — onnxruntime-gpu untuk Pascal + tolak rekognisi yang diam-diam jalan di CPU (3 Okt 2026)

*Catatan asli: [`arsip/PERUBAHAN-ONNXRUNTIME-CUDA12-CEK-PROVIDER.md`](arsip/PERUBAHAN-ONNXRUNTIME-CUDA12-CEK-PROVIDER.md)*

Ekstrak di root proyek di atas paket `setup-uji-rekognisi-wajah_config-face-async-sync_log-worker`.
Verifikasi: 484 tes lulus.

### Gejala (GTX 1060)
```
Error loading onnxruntime_providers_cuda.dll which depends on "cublasLt64_13.dll" which is missing
Failed to create CUDAExecutionProvider. Require cuDNN 9.* and CUDA 13.*
```

### Penyebab
- onnxruntime-gpu 1.30 dibangun untuk CUDA 13. Menurut catatan rilis 1.26, CUDA 12 dibuang mulai 1.27.
- CUDA 13 tidak lagi mendukung GPU Pascal (GTX 10xx). Memasang CUDA 13 pun tidak akan menolong di 1060.
- onnxruntime tidak error dalam kasus ini: ia menulis peringatan lalu jalan di CPU.

### Perbaikan
- `engine/identity/face_onnx.py`:
  - Memanggil `onnxruntime.preload_dlls()` sekali sebelum sesi CUDA pertama. Fungsi ini memuat DLL
    CUDA/cuDNN dari paket pip `nvidia-*` atau dari folder lib torch.
  - Bila CUDA diminta tetapi tidak aktif, engine BERHENTI dengan pesan yang menunjuk penyebabnya, tidak
    lagi jalan diam-diam di CPU.
  - Provider yang benar-benar aktif dicetak di log.
- `engine/requirements-face.txt`: `onnxruntime-gpu[cuda,cudnn]>=1.21,<1.27`.
- Tes baru: `engine/tests/test_onnx_provider_check.py` (3).

### Pasang ulang di mesin
```
pip uninstall -y onnxruntime-gpu onnxruntime
pip install "onnxruntime-gpu[cuda,cudnn]>=1.21,<1.27"
```


## 2026-10-03 — Engine bisa dihentikan: Ctrl+C, `q` + Enter, dan penjaga waktu (3 Okt 2026)

*Catatan asli: [`arsip/PERUBAHAN-ENGINE-BISA-DIHENTIKAN.md`](arsip/PERUBAHAN-ENGINE-BISA-DIHENTIKAN.md)*

Ekstrak di root proyek di atas paket `perbaikan-onnxruntime-cuda12-pascal_tolak-rekognisi-diam-diam-cpu`.
Verifikasi: 489 tes lulus, integration smoke lulus.

### Gejala (Windows)
`python -m engine.runtime` tidak berhenti dengan Ctrl+C.

### Penyebab yang ditangani
1. Berhenti rapi bisa macet tanpa batas waktu:
   - thread kamera masih memuat model (±55 dtk di 1060);
   - thread terjebak di panggilan native (FFmpeg menunggu RTSP, CUDA, onnxruntime);
   - `camera.stop` menunggu 10 dtk per kamera.
2. Setelah `main()` selesai, finalisasi interpreter bisa menggantung di Windows karena thread daemon
   masih berada di dalam kode native. Selama finalisasi, handler Ctrl+C tidak jalan lagi.
3. Ctrl+C kadang tidak sampai ke Python di Windows:
   - pustaka native memasang penangan konsol sendiri;
   - jendela konsol dalam mode seleksi (QuickEdit) membekukan proses saat menulis log.

### Perbaikan (`engine/runtime/__main__.py`)
- Satu jalur berhenti (`_Stopper`):
  - Permintaan pertama: berhenti rapi di thread terpisah, plus penjaga waktu 20 dtk yang memaksa keluar
    bila rapi-nya macet.
  - Permintaan kedua: keluar paksa saat itu juga.
- Sumber permintaan berhenti: SIGINT (Ctrl+C), SIGTERM, SIGBREAK (Ctrl+Break di Windows), dan perintah
  terminal `q` / `quit` / `exit` / `stop` diikuti Enter.
- Setelah berhenti rapi, proses keluar dengan `os._exit` (log di-flush dulu), tanpa finalisasi
  interpreter yang bisa menggantung.

### Tes
`engine/tests/test_engine_shutdown.py` (3), termasuk proses engine sungguhan yang harus keluar dengan kode 0
setelah SIGINT.


## 2026-10-02 — Rekognisi async + koreksi jam + buffer tracker berbasis detik + alat diagnosis 4 fps (2 Okt 2026, malam)

*Catatan asli: [`arsip/PERUBAHAN-REKOGNISI-ASYNC-KOREKSI-JAM.md`](arsip/PERUBAHAN-REKOGNISI-ASYNC-KOREKSI-JAM.md)*

Disiapkan tanpa GPU (RTX 4060 mati semalam). Tujuannya agar uji besok tinggal ukur dan setel.
Paket ini juga memuat isi paket "lag-kamera-terukur" dan "perbaikan lag-probe" sebelumnya, jadi cukup
diekstrak di atas zip Engine B "stream live dan detector".

Verifikasi: 478 tes contracts+engine lulus, 3 dilewati. Semua config YAML ter-load.
Langkah uji besok ada di `docs/UJI-LAG.md`, bagian "Uji lanjutan".

### 1. Rekognisi wajah keluar dari loop frame (P7) — Engine A + bersama
- Baru, `engine/pipeline/recognition_worker.py`: satu worker untuk semua kamera, karena GPU-nya satu.
  - Antrean dibatasi (`worker_queue`, default 8). Bila penuh, permintaan ditolak seketika dan dicoba
    lagi di frame berikutnya. Loop frame tidak pernah memblok.
  - Pekerjaan yang mengantre lebih dari 0,5 dtk dibuang, karena crop basi lebih buruk dari crop baru.
  - Exception dihitung di `failed` dan tidak mematikan worker.
- Worker hanya menjalankan SCRFD + AuraFace. Arbiter, assembler, scheduler dan event tetap di thread
  kamera:
  - Hasil diantrekan balik lalu diterapkan di awal frame berikutnya (`EngineBinding.drain_results`).
  - Akibatnya urutan started → identified → ended tetap terjaga.
  - Hasil untuk track yang sudah berakhir dibuang dan dihitung.
- `engine/presence/binding.py`:
  - Parameter `executor` baru.
  - Metrik baru `recognitions_queued`, `recognitions_rejected`, `results_discarded`.
  - Hitungan evidence sekarang per uuid (`evidence_by_uuid`).
- `engine/runtime/camera.py`: alasan `unidentified` membaca hitungan evidence dari binding, bukan dari
  jumlah percobaan.
- `engine/runtime/service.py`:
  - Membuat dan menutup worker.
  - `queue_depth` di health menyertakan antrean worker.
  - Bila worker mati, health memuat `recognition_worker_stopped`.
- Config: `recognition.execution: "async" | "sync"` (default async) dan `recognition.worker_queue`.
- Tes ujung ke ujung (recognizer palsu 20 ms): dalam 2,5 dtk, sync memproses 3.304 frame dan async
  17.128 frame. Keduanya tetap menghasilkan identified.

### 2. Koreksi bias offset jam (P18) — sentuh folder Engine B
- Temuan: offset ditetapkan saat `begin_epoch()` (stream dibuka), bukan di frame pertama seperti kata
  docstring. MediaMTX mengirim mulai dari keyframe yang direkam sebelum itu, jadi `at` mendahului
  kenyataan sebesar umur keyframe, selamanya.
- `engine/ingest/timeline.py` (EB):
  - `stamp(raw_pts, arrival=None)` mencatat residu waktu tiba.
  - `offset_bias` = residu minimum dalam jendela 10 dtk PTS. Nilainya None sampai rentang ≥ 3 dtk.
  - `slew_offset(delta)` menggeser offset.
- `engine/ingest/pyav_source.py` (EB): mengirim `arrival` hanya bila thread pembaca aktif.
  - Tanpa thread pembaca, waktu tiba sebenarnya waktu baca, jadi antrean nyata akan terbaca sebagai
    bias dan ikut "dikoreksi".
- Baru, `engine/runtime/clock.py`, `OffsetCorrector`:
  - Mulai bila |bias| > 0,5 dtk, berhenti bila ≤ 0,05 dtk.
  - Laju maksimal 0,1 dtk per dtk, sehingga `at` tetap naik monoton dan `end_at` tidak pernah
    mendahului `start_at`.
- Supervisor menggeser timeline dan PtsClock assembler bersamaan (`PresenceAssembler.adjust_offset`).
  Reconnect mereset koreksi.
- Metrik baru `engine.health.camera_metrics.clock_drift_seconds`.
- Config: `ingest.offset_correction: "slew" | "none"` (default slew; hanya aktif dengan
  `live_buffer: latest`).

### 3. Buffer IoU tracker dalam detik PTS — sentuh folder Engine B
- `engine/perception/iou_tracker.py`:
  - Track dibuang setelah `track_buffer_seconds` detik PTS tanpa terlihat. Sebelumnya patokannya
    jumlah frame, padahal di 4 fps jumlah frame yang sama berarti 3× lebih lama.
  - Bila PTS mundur (epoch baru), semua track dibuang.
  - Tanpa PTS, kembali ke hitungan frame.
- `engine/factory.py` meneruskan `max_missing_seconds`.
- **ByteTrack belum**: buffer-nya masih berbasis frame di dalam LibreYOLO.

### 4. Diagnosis plafon 4 fps tanpa GPU — alat untuk Engine B
- Baru, `engine/tools/ingest_ceiling.py`: detector diganti beban tiruan (`sleep` = menunggu GPU,
  `gil` = kerja Python).
- Membandingkan varian decoder: `latest-auto`, `latest-slice`, `latest-frame2`, `latest-1thread`,
  `none-auto`.
- Kesimpulan per varian: OK / TERTAHAN SEBAGIAN / INGEST MENAHAN PIPELINE.
- Hipotesis yang diuji: frame threading FFmpeg (AUTO) di thread pembaca berebut CPU/GIL dengan
  pipeline. Belum terbukti; besok yang menentukan.

### 5. Probe
- `scripts/lag_probe.py`:
  - Kolom `drift_s` baru.
  - `track.identified` dicatat.
  - Ringkasan mencetak drift awal → akhir dan jumlah identified.
- Semua YAML di `engine/config/` sekarang menulis eksplisit `offset_correction`, `execution` dan
  `worker_queue` (nilai default, perilaku tidak berubah). Tujuannya supaya tombolnya kelihatan.

### 6. Tambahan 3 Okt pagi: dua tombol untuk plafon 4 fps (default mati)
- Dugaan baru yang lebih kuat dari "threading decoder": **rebutan thread CPU**.
  - Engine tidak membatasi thread sama sekali, sehingga torch, OpenCV dan decoder FFmpeg masing-masing
    membuka pool selebar jumlah core.
  - Di `latest`, decode berjalan bersamaan dengan pra/pasca-proses detector. Di `none` keduanya
    bergantian.
  - Dugaan ini cocok dengan gejala: `latest` < `none`, FP16 tidak berpengaruh, angka stabil ±4.
- `core.cpu_threads` (baru, default 0 = perilaku lama):
  - Implementasi di `engine/runtime/threads.py`. Mengatur OMP/MKL/OpenBLAS env,
    `torch.set_num_threads`, `torch.set_num_interop_threads` dan `cv2.setNumThreads`.
  - Diterapkan di `EngineRuntime` sebelum detector dan recognizer dimuat.
  - Hasilnya tercetak di log: `batas thread CPU: {...}`.
- `ingest.hwaccel: "none" | "cuda"` (baru, default none), menyentuh folder Engine B:
  - `PyAVSource(hwaccel=...)` membuka container dengan `HWAccel` PyAV (≥ 14).
  - Diminta tetapi tidak bisa = engine berhenti keras dengan pesan jelas, tidak diam-diam kembali
    ke CPU.
  - `describe()["hwaccel"]` melaporkan status dan `is_hwaccel` dari PyAV.
  - Frame tetap disalin balik ke RAM: hemat CPU decode, belum hemat PCIe.
- `ingest_ceiling`:
  - `--work torch` (resize OpenCV + matmul torch) supaya rebutan thread terjadi tanpa detector.
  - `--cpu-threads N`.
  - Varian `latest-cuvid`.
- `docs/UJI-LAG.md`:
  - Persiapan mesin tanpa Docker atau dengan video pendek: MediaMTX exe, pre-encode lalu `-c copy`,
    catatan Pascal.
  - Urutan uji A diperbarui.
  - Dua baris tombol mundur baru.
- Tes baru: `engine/tests/test_cpu_threads_hwaccel.py` (10), dan `test_ingest_ceiling.py` +2.

### Berkas folder Engine B yang disentuh (mohon direview Engine B)
- `engine/ingest/timeline.py`
- `engine/ingest/pyav_source.py`
- `engine/perception/iou_tracker.py`
- `engine/factory.py`
- `engine/tools/ingest_ceiling.py` (baru)
- `pyav_source.py` juga dapat parameter `hwaccel`. Default "none": jalur lama tidak berubah.

Berkas bersama: `engine/runtime/*`, `engine/pipeline/*`, `engine/config/*`.

### Tombol mundur (tanpa ganti kode)
- `recognition.execution: "sync"`
- `ingest.offset_correction: "none"`
- `core.cpu_threads: 0`
- `ingest.hwaccel: "none"`

### Belum
- Penyebab pasti plafon 4 fps: diukur besok dengan `ingest_ceiling`.
- Buffer ByteTrack berbasis detik.
- Sinkronisasi kotak di frontend (P10/P16).
- Config MediaMTX (P4/P19).
- Sisi backend untuk auth/forget/ack.


## 2026-10-02 — Lag kamera terukur + alat uji delay — 2 Oktober 2026

*Catatan asli: [`arsip/PERUBAHAN-LAG-KAMERA.md`](arsip/PERUBAHAN-LAG-KAMERA.md)*

Di atas zip Engine B "stream live dan detector". Ekstrak di root proyek (timpa).
Verifikasi: 437 tes contracts+engine lulus tanpa peringatan, integration smoke lulus, policy_grep bersih.

### 1. Engine melapor sendiri saat tertinggal (P17, kontrak fase 1)
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

### 2. Sentuhan kecil di folder Engine B (mohon diketahui Engine B)
- `engine/ingest/pyav_source.py`: dua properti baca-saja, `latest_decoded` (epoch, pts) dan
  `frames_replaced`. Tidak mengubah perilaku ingest.

### 3. Alat uji teori delay
- `scripts/lag_probe.py`: pengganti backend sementara; mencatat umur kotak + lag per kamera ke CSV
  dan menyimpulkan BERTAMBAH (engine, P17) / SEGAR (cari di frontend, P10/P16) / TETAP besar (P18),
  atau TIDAK VALID bila `at` di masa depan. Mendukung handshake HMAC (`ENGINE_SHARED_KEY`).
- `scripts/publish_test_video.ps1` / `.sh`: video uji -> MediaMTX tanpa B-frame, keyframe tiap 1 dtk.
- `docs/UJI-LAG.md`: langkah uji A/B (live_buffer latest vs none) + jalur lengkap dashboard.

### 4. Lain-lain
- `engine/tests/test_recognizer_slot.py`: perbaikan ResourceWarning (berkas config tidak ditutup).
- Tes baru: `engine/tests/test_lag_monitor.py` (9), `engine/tests/test_lag_probe.py` (4).

### Belum
- Koreksi offset frame pertama (P18) dan sinkronisasi kotak di frontend (P10/P16).
- Pilihan profil tracker untuk demo (`dfine-m` masih IoU; P8 hanya aktif di `dfine-m-bytetrack`).


## 2026-10-02 — Perbaikan: stream live (MediaMTX) dan biaya detector

*Catatan asli: [`arsip/PERBAIKAN-STREAM-LIVE-DAN-DETECTOR.md`](arsip/PERBAIKAN-STREAM-LIVE-DAN-DETECTOR.md)*

Gejala yang diperbaiki: video WebRTC di browser lancar, tapi bounding box
patah-patah dan telat. Log MediaMTX: `reader is too slow, discarding N frames`.
Engine: `PTS went backwards`.

### Akar masalah

1. **Engine membaca RTSP di thread yang sama dengan inferensi.** Selama detector
   berjalan, socket tidak dibaca, antrean kirim MediaMTX penuh, lalu paket dibuang
   di tengah GOP. Decoder menerima bitstream bolong.
2. **Frame yang dibuang decimation tetap dikonversi YUV→BGR resolusi penuh.**
   Di 30→12 fps, ~2,5 konversi 1080p (6 MB tiap frame) per frame yang dianalisis
   langsung dibuang. Ini sebagian besar dari `source_ingest` 50 ms di RTX 4060.
3. **Preprocessing LibreYOLO untuk D-FINE berjalan di CPU via PIL pada resolusi
   penuh**: 4–5 salinan 1080p per frame sebelum resize. Ini sebagian besar dari
   "detector" 110 ms di RTX 4060 (dicek langsung di kode LibreYOLO 1.6.0).
4. **`half: true` tidak berpengaruh.** LibreYOLO mengabaikan `half=` (no-op), dan
   `quantize(recipe="fp16")` tidak mendukung keluarga D-FINE.
5. **ByteTrack tidak pernah menerima kotak skor rendah** (P8): model dipanggil
   dengan `conf=0.50`, jadi asosiasi tahap kedua ByteTrack selalu kosong.
6. **Profil runtime `dfine-*.yaml` punya `reconnect_attempts: 0`**, sehingga RTSP
   yang putus sedetik mati permanen. README juga menyuruh menjalankan runtime
   dengan `default_config.yaml`, yaitu baseline bench 30 fps.

### Perubahan

| File | Isi |
| --- | --- |
| `engine/ingest/pyav_source.py` | `LazyFrame`: piksel BGR baru dibuat saat `frame.image` disentuh. Mode `live_buffer: latest` untuk stream jaringan: reader thread menguras dan men-decode stream dengan kecepatan kamera, menyimpan satu frame terbaru, dan menangani reconnect. Frame yang terlewat dihitung di `describe()["live_reader"]`. File lokal tidak berubah perilaku. |
| `engine/perception/dfine_detector.py` | `pre_resize`: resize ke `image_size²` dengan OpenCV INTER_AREA sebelum LibreYOLO, lalu kotak dipetakan balik pada objek `Results` (yang juga dimakan ByteTrack). `half` sekarang benar-benar FP16 via `torch.autocast`, dengan peringatan di GPU Pascal. `raw_confidence`: model diminta kotak sampai batas bawah ByteTrack, sedangkan `detect()` tetap memfilter di `confidence_threshold`. Kwarg no-op (`half`, `verbose`) tidak dikirim lagi. |
| `engine/factory.py` | Meneruskan `live_buffer` dan `pre_resize`. `raw_confidence=0.1` hanya kalau tracker = bytetrack. |
| `engine/config/schema.py`, `loader.py` | Field baru `ingest.live_buffer` (default `none`) dan `detector.pre_resize` (default `false`), dengan validasi. |
| `engine/config/dfine-{m,s,m-bytetrack}.yaml` | `live_buffer: latest`, `reconnect_attempts: 10`, `pre_resize: true`. |
| `engine/config/dfine-n.yaml`, `default_config.yaml` | `live_buffer: latest` (hanya berlaku untuk jaringan), `pre_resize: false` supaya baseline bench tidak bergeser. |
| `README.md` | Perintah runtime memakai `dfine-m.yaml`, bukan `default_config.yaml`. |
| `engine/tests/test_live_ingest_and_detector_prep.py` | 17 tes baru. |
| `engine/tests/test_b4_ingest.py` | Tes reformatter sekarang menyentuh `frame.image`, karena konversi kini lazy. |

Hasil tes: seluruh `contracts/tests` dan `engine/tests` lulus.

### Yang harus diverifikasi di mesin kalian

Saya tidak punya GPU, PyAV, atau LibreYOLO asli di lingkungan kerja. Logikanya
diuji dengan fake, tapi angka performa dan akurasi harus kalian ukur sendiri.

1. **Bench ulang di 4060**, dengan video dan config yang sama seperti sebelumnya:
   `python -m engine.bench --config engine/config/dfine-m-bytetrack.yaml --source <video 1080p> --mode throughput --label prep`.
   Bandingkan `source_ingest` dan `detector` dengan run lama (50 ms / 112 ms).
2. **Akurasi pre_resize**: di CPU saya, beda piksel rata-rata 1,35/255
   (p99 8/255) dibanding resize PIL, sementara preprocessing 1080p turun dari
   ~39 ms ke ~10 ms. Bandingkan jumlah deteksi dan kotaknya pada klip yang sama
   dengan `pre_resize: true` dan `false`.
3. **FP16 di 4060**: setel `half: true`, bench lagi, dan pastikan deteksinya
   tidak berubah berarti. Jangan aktifkan di 1060.
4. **Live**: jalankan `python -m engine.runtime --config engine/config/dfine-m.yaml --tcp 0.0.0.0:8765`
   dengan MediaMTX. Kriteria lulus: tidak ada lagi `reader is too slow` dan
   `PTS went backwards` ≈ 0. Saat engine berhenti, log menunjukkan berapa frame
   yang di-decode, diambil, dan dilewati.
5. **ByteTrack**: perilakunya berubah karena tahap kedua sekarang hidup. Track
   seharusnya lebih jarang putus saat orang teroklusi. Bandingkan umur track
   sebelum dan sesudah.

### Yang belum dikerjakan

- **Sinkronisasi box vs video WebRTC di frontend.** Jalur box tetap lebih lambat
  daripada video. Perlu PTS/`requestVideoFrameCallback`, `jitterBufferTarget`,
  atau interpolasi per track ID.
- NVDEC, TensorRT, dan overlap decode/inferensi di thread terpisah untuk file.


## 2026-10-01 — Perubahan Engine A — 1 Oktober 2026

*Catatan asli: [`arsip/PERUBAHAN-ENGINE-A.md`](arsip/PERUBAHAN-ENGINE-A.md)*

Kumulatif dari build `2026.09.23-audit-fixes`. Ekstrak di root proyek (timpa).
Verifikasi: 407 tes contracts+engine lulus, integration smoke lulus, policy_grep bersih.

### 1. Koneksi engine tahan gangguan (D8, P2)
- Handshake di thread sendiri + batas 5 dtk untuk `hello`: klien diam tidak lagi menahan backend.
- Baris pertama bukan JSON tidak lagi mematikan loop accept engine.
- Koneksi lama diputus sebelum handshake mengambil kunci tulis: backend baru tidak menunggu backend macet.
- Keepalive TCP + batas waktu kirim 15 dtk (SO_SNDTIMEO, ada cabang Windows).
- Berkas: `engine/api/server.py`, `engine/tests/test_api_connection.py`

### 2. Config recognizer
- Nama model `models/glintr100.onnx`; field baru `face_detector_input_size` (default 640, kelipatan 32).
- Berkas: `engine/config/*`, `engine/identity/face_onnx.py`, `README.md`, `engine/tests/test_recognizer_slot.py`

### 3. Pembekuan skema protokol fase 1 (tambahan, protocol_version tetap 1)
- `auth_challenge`, `hello.auth`, `hello_ack.auth` (HMAC-SHA256) — P3.
- `ack` dua bentuk; ACK event backend (`through_seq`) akhirnya tercantum, `ts` wajib — P12.
- `engine.health.camera_metrics`, `outbox_depth`, `disk_free_mb`; peta `cameras` dibekukan.
- `camera.degraded.kind/since_at/lag_seconds`, event baru `camera.recovered`.
- `enroll_from_track` (+ alasan `track_unavailable`), `forget_person` → `forget_result`.
- Berkas: `contracts/schema/…`, `contracts/handshake_auth.py`, `contracts/tests/test_protocol_phase1.py`, `contracts/README.md`, `docs/ENGINE_PROTOCOL.md` §8

### 4. Implementasi engine dari kontrak fase 1
- Handshake HMAC di engine asli dan fake engine; kunci dari env `ENGINE_SHARED_KEY`.
- `forget_person` dengan penghapusan sungguhan: `secure_delete` + checkpoint WAL (foto wajah sebelumnya masih bisa dibaca dari berkas setelah "dihapus").
- `engine.health` membawa `outbox_depth`, `disk_free_mb`.
- Fake engine: `forget_person`, `enroll_from_track`, tidak lagi membalas ACK backend dengan "tidak dikenal".
- Dockerfile fake engine menyalin `contracts/handshake_auth.py`.
- Berkas: `engine/runtime/*`, `engine/store/references.py`, `engine/api/events.py`, `engine/tools/fake_engine/*`, `deploy/fake-engine/*`, `.env.example`, `engine/tests/test_engine_phase1.py`

### Belum
- `enroll_from_track` di engine asli (cache crop wajah per track) — Engine A berikutnya.
- `camera_metrics`, `camera.degraded.kind`, `camera.recovered` — Engine B (ingest).
- Seluruh sisi backend: klien auth, `forget_result`, ACK dengan `ts`.


## 2026-09-23 — Perubahan — 23 September 2026 (build 2026.09.23-audit-fixes)

*Catatan asli: [`arsip/CHANGES.md`](arsip/CHANGES.md)*

Perbaikan atas audit `claude/audit-masalah-2026-09-23.md`. Keputusan yang dipakai:

- **Jatah 30 menit = waktu terlihat di ruang fasilitas**, logika bisnis di backend.
- Detector: LibreYOLO D-FINE **m** (default) atau **s** (`--model s`).
- Recognizer wajah: slot terpasang, **mati secara default**, dinyalakan lewat config.

### Kanal event (tidak ada event yang hilang diam-diam)

| ID | Perbaikan | File |
|---|---|---|
| K1 | Engine asli memakai `SqliteOutbox` (`engine/data/outbox.sqlite3`, `--outbox`). `hello_ack` membawa `outbox_id`; backend menyimpan kursor per outbox dan menyambung ulang dengan kursor yang benar bila outbox berganti. Event disimpan dengan kunci `(outbox_id, seq)`. | `engine/runtime/*`, `engine/api/outbox.py`, `backend/services/engine_client.py`, `backend/core/database.py` |
| K2 | Pengiriman event berbasis kursor ke outbox (tidak ada antrian yang bisa "ambil lalu buang"). Koneksi + kursor dipasang atomik saat handshake. Backend mendeteksi lubang `seq` dan meminta replay (maks. 3x, lalu dicatat). | `engine/api/server.py`, `backend/services/engine_client.py` |
| T4 | `close()` mematikan socket sebelum menutup reader — tidak lagi deadlock. | `backend/services/engine_client.py` |
| T5 | Pesan beracun masuk `dead_letters` + di-ACK; stream jalan terus. View/kontrol yang rusak tidak memutus koneksi. `GET /api/system/dead-letters`. | `engine_client.py`, `routers/system.py` |
| T6 | Satu kunci tulis untuk semua penulisan socket engine. | `engine/api/server.py` |
| baru | `track_uuid`/`interval_id` diberi nonce per run: tidak lagi didaur ulang setelah restart engine/kamera. | `engine/runtime/camera.py`, `engine/presence/binding.py` |

### Jatah free time

| ID | Perbaikan |
|---|---|
| K3 | Hitungan "gap = istirahat" dihapus (`session_deriver.py`). Satu model: hadir di ruang fasilitas. |
| K4 | `backend/services/free_time.py`: ledger dari event durabel (`presence.interval` + track terbuka dari `track.*`), union lintas kamera, penggabungan oklusi (`visit_merge_gap_seconds`), pengaman engine mati (`open_presence_stale_seconds`), dibangun ulang dari DB saat backend start. Overlay mengambil angka dari ledger. |
| T1 | Query interval difilter per tanggal di SQL (bukan 1000 baris tertua). |
| T2 | Interval tumpang-tindih tidak lagi melempar error; digabung. |
| S3 | Jam istirahat resmi menghormati menit, bisa lebih dari satu (`official_breaks`). Satu aturan status untuk semua endpoint. |
| S4 | Koreksi HR disimpan di tabel `corrections` dan **diterapkan**: kecualikan satu kunjungan atau tambah/kurangi menit. Audit log bertahan restart. |
| S5 | Event tidak lagi disimpan dua kali. |

### Kamera, config, keamanan

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

### Engine B / model

- `scripts/run_demo.py --model m|s` (atau `AI_TIME_DFINE`). `dfine-s.yaml` kini `device: auto` seperti `dfine-m.yaml`.
- Slot recognizer: `engine/identity/face_onnx.py` (SCRFD + AuraFace via onnxruntime), config `recognition.recognizer: none|onnx_face`. Enrollment memakai `EnrollmentPolicy` milik Engine A yang sudah ada. Dependency: `engine/requirements-face.txt`.

### Verifikasi

- 384 tes lulus (contracts 76, engine 279, backend 29), 2 skip (butuh lingkungan tanpa torch). Tes dijalankan dengan shim pytest/fastapi karena PyPI diblokir di lingkungan build; **jalankan ulang `python -m pytest -q` di mesin kalian.**
- `scripts/integration_smoke.py` (engine asli 3 kamera ↔ klien backend) lulus semua.
- **Frontend belum di-build** (npm diblokir di lingkungan build). Perubahan FE kecil (form koreksi, hasil enrollment, label panel, header proxy) — jalankan `npm run build`.
- Recognizer ONNX **belum diuji dengan model sungguhan** (model tidak tersedia). Jalur enrollment diuji dengan stub.


## 2026-09-23 — Live timer and backend completion

*Catatan asli: [`arsip/CHANGES_TIMER_BACKEND.md`](arsip/CHANGES_TIMER_BACKEND.md)*

### Implemented

- Real `view.frame` messages now update the backend `SystemState`.
- Every active track gets a backend-owned `first_seen` time and a live
  `session_elapsed` value.
- `/api/attendance/active` calculates duration at request time, so its timer
  continues between detection frames.
- Detection SSE boxes carry `session_elapsed`, `dwell_time`, and
  `presence_status`.
- The frontend continues each displayed timer from the last backend value.
- `/api/cameras` reports runtime FPS, online state, and active-person count.
- `/api/stats` now receives state from the real TCP engine path.
- Added `GET /api/attendance/breaks?date=YYYY-MM-DD` for the existing break
  allowance panel.
- Real protocol events are included in the recent backend event history.
- Fixed `snapshot.live[].stream_epoch` generation and backend schema support.
- Removed the duplicate dashboard `useDetectionStream()` owner to prevent SSE
  reconnect storms.
- Removed the duplicate case-only `useUnIdentifiedAlerts.ts` file that broke
  Linux builds.

### Timer behavior

- A timer is keyed by `camera_id + track_uuid`, not by identity. Identifying a
  track later therefore does not reset or duplicate its timer.
- A session becomes stale after 12 seconds without a new frame for that track.
- Completed usage is capped at the last observed time rather than including the
  stale grace period.

### Verification

- 54 selected backend, contract, and runtime tests passed.
- Frontend TypeScript and production Vite build passed.
- Three existing Unix-domain-socket tests could not run in the build sandbox
  because `AF_UNIX` socket creation is blocked there; this is environment
  specific and unrelated to the timer implementation.
- The complete test suite additionally needs the optional OpenCV dependency.
### Aturan timer free time

- Kehadiran harus berlanjut selama 20 detik sebelum dianggap sebagai kunjungan; orang yang keluar sebelum itu tidak memakai jatah.
- Pemakaian baru dimulai setelah 20 detik tersebut, bukan dihitung mundur dari `first_seen`.
- Pukul 12:00–13:00 zona `Asia/Jakarta`, validasi dan pemakaian sama-sama dijeda.
- Jatah pemakaian adalah 30 menit per pegawai per tanggal lokal dan pemakaian kunjungan yang selesai disimpan di SQLite.
- Overlay video menampilkan fase validasi, pemakaian harian, jeda istirahat, peringatan, dan batas tercapai, termasuk pada grid compact.


## 2026-09-22 — Live timer and backend completion

*Catatan asli: [`arsip/CHANGES_TIMER_BACKEND_2026-09-22.md`](arsip/CHANGES_TIMER_BACKEND_2026-09-22.md)*

> **Digantikan 23 Sep 2026:** timer tidak lagi menagih dari kanal `view`. Lihat `CHANGES.md`.


### Implemented

- Real `view.frame` messages now update the backend `SystemState`.
- Every active track gets a backend-owned `first_seen` time and a live
  `session_elapsed` value.
- `/api/attendance/active` calculates duration at request time, so its timer
  continues between detection frames.
- Detection SSE boxes carry `session_elapsed`, `dwell_time`, and
  `presence_status`.
- The frontend continues each displayed timer from the last backend value.
- `/api/cameras` reports runtime FPS, online state, and active-person count.
- `/api/stats` now receives state from the real TCP engine path.
- Added `GET /api/attendance/breaks?date=YYYY-MM-DD` for the existing break
  allowance panel.
- Real protocol events are included in the recent backend event history.
- Fixed `snapshot.live[].stream_epoch` generation and backend schema support.
- Removed the duplicate dashboard `useDetectionStream()` owner to prevent SSE
  reconnect storms.
- Removed the duplicate case-only `useUnIdentifiedAlerts.ts` file that broke
  Linux builds.

### Timer behavior

- A timer is keyed by `camera_id + track_uuid`, not by identity. Identifying a
  track later therefore does not reset or duplicate its timer.
- A session becomes stale after 12 seconds without a new frame for that track.
- Completed usage is capped at the last observed time rather than including the
  stale grace period.

### Verification

- 54 selected backend, contract, and runtime tests passed.
- Frontend TypeScript and production Vite build passed.
- Three existing Unix-domain-socket tests could not run in the build sandbox
  because `AF_UNIX` socket creation is blocked there; this is environment
  specific and unrelated to the timer implementation.
- The complete test suite additionally needs the optional OpenCV dependency.
### Aturan timer free time

- Kehadiran harus berlanjut selama 20 detik sebelum dianggap sebagai kunjungan; orang yang keluar sebelum itu tidak memakai jatah.
- Pemakaian baru dimulai setelah 20 detik tersebut, bukan dihitung mundur dari `first_seen`.
- Pukul 12:00–13:00 zona `Asia/Jakarta`, validasi dan pemakaian sama-sama dijeda.
- Jatah pemakaian adalah 30 menit per pegawai per tanggal lokal dan pemakaian kunjungan yang selesai disimpan di SQLite.
- Overlay video menampilkan fase validasi, pemakaian harian, jeda istirahat, peringatan, dan batas tercapai, termasuk pada grid compact.
