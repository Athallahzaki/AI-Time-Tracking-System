# Rekognisi async + koreksi jam + buffer tracker berbasis detik + alat diagnosis 4 fps (2 Okt 2026, malam)

Disiapkan tanpa GPU (RTX 4060 mati semalam). Tujuannya agar uji besok tinggal ukur dan setel.
Paket ini juga memuat isi paket "lag-kamera-terukur" dan "perbaikan lag-probe" sebelumnya, jadi cukup
diekstrak di atas zip Engine B "stream live dan detector".

Verifikasi: 478 tes contracts+engine lulus, 3 dilewati. Semua config YAML ter-load.
Langkah uji besok ada di `docs/UJI-LAG.md`, bagian "Uji lanjutan".

## 1. Rekognisi wajah keluar dari loop frame (P7) — Engine A + bersama
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

## 2. Koreksi bias offset jam (P18) — sentuh folder Engine B
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

## 3. Buffer IoU tracker dalam detik PTS — sentuh folder Engine B
- `engine/perception/iou_tracker.py`:
  - Track dibuang setelah `track_buffer_seconds` detik PTS tanpa terlihat. Sebelumnya patokannya
    jumlah frame, padahal di 4 fps jumlah frame yang sama berarti 3× lebih lama.
  - Bila PTS mundur (epoch baru), semua track dibuang.
  - Tanpa PTS, kembali ke hitungan frame.
- `engine/factory.py` meneruskan `max_missing_seconds`.
- **ByteTrack belum**: buffer-nya masih berbasis frame di dalam LibreYOLO.

## 4. Diagnosis plafon 4 fps tanpa GPU — alat untuk Engine B
- Baru, `engine/tools/ingest_ceiling.py`: detector diganti beban tiruan (`sleep` = menunggu GPU,
  `gil` = kerja Python).
- Membandingkan varian decoder: `latest-auto`, `latest-slice`, `latest-frame2`, `latest-1thread`,
  `none-auto`.
- Kesimpulan per varian: OK / TERTAHAN SEBAGIAN / INGEST MENAHAN PIPELINE.
- Hipotesis yang diuji: frame threading FFmpeg (AUTO) di thread pembaca berebut CPU/GIL dengan
  pipeline. Belum terbukti; besok yang menentukan.

## 5. Probe
- `scripts/lag_probe.py`:
  - Kolom `drift_s` baru.
  - `track.identified` dicatat.
  - Ringkasan mencetak drift awal → akhir dan jumlah identified.
- Semua YAML di `engine/config/` sekarang menulis eksplisit `offset_correction`, `execution` dan
  `worker_queue` (nilai default, perilaku tidak berubah). Tujuannya supaya tombolnya kelihatan.

## 6. Tambahan 3 Okt pagi: dua tombol untuk plafon 4 fps (default mati)
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

## Berkas folder Engine B yang disentuh (mohon direview Engine B)
- `engine/ingest/timeline.py`
- `engine/ingest/pyav_source.py`
- `engine/perception/iou_tracker.py`
- `engine/factory.py`
- `engine/tools/ingest_ceiling.py` (baru)
- `pyav_source.py` juga dapat parameter `hwaccel`. Default "none": jalur lama tidak berubah.

Berkas bersama: `engine/runtime/*`, `engine/pipeline/*`, `engine/config/*`.

## Tombol mundur (tanpa ganti kode)
- `recognition.execution: "sync"`
- `ingest.offset_correction: "none"`
- `core.cpu_threads: 0`
- `ingest.hwaccel: "none"`

## Belum
- Penyebab pasti plafon 4 fps: diukur besok dengan `ingest_ceiling`.
- Buffer ByteTrack berbasis detik.
- Sinkronisasi kotak di frontend (P10/P16).
- Config MediaMTX (P4/P19).
- Sisi backend untuk auth/forget/ack.
