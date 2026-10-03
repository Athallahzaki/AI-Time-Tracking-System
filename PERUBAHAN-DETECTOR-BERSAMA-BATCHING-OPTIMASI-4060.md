# Detector bersama antar-kamera, batching opsional, optimasi untuk RTX 4060 (3 Okt 2026)

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

## 1. Detector bersama (`engine/perception/shared_detector.py`, baru)

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

## 2. Batching di `DFINEDetector` (berkas Engine B)

- `predict_images(images)` mengembalikan satu Results per gambar, berurutan.
- Dengan `batch_inference: true`, dicoba `model(list)`. Bila LibreYOLO menolak atau tidak mengembalikan
  satu hasil per gambar, adapter memberi peringatan SEKALI lalu menjalankan per gambar.
  Menyalakan tombol ini tidak pernah menghasilkan kotak yang salah urut.
- Gambar dengan format warna berbeda (sebagian di-pre_resize, sebagian tidak) tidak dibatch.
- `detect()` dipecah menjadi `_predict` dan `postprocess` (pure, aman dari thread kamera mana pun).

## 3. Optimasi kecil

- Inferensi D-FINE selalu di bawah `torch.no_grad()`.
  - Sebelumnya tidak ada `no_grad` di sisi engine.
  - Bukan `inference_mode`, karena tensor Results masih diubah di rescale_result dan ByteTrack.
- `detector.cudnn_benchmark` (default false): cuDNN memilih algoritma tercepat untuk input 640 yang tetap.
- `recognition.onnx_gpu_mem_limit_mb` (default kosong): batas VRAM arena onnxruntime dengan strategi
  `kSameAsRequested`, untuk GPU 8 GB yang dipakai bersama PyTorch.

## 4. Alat dan dokumen

- `engine/tools/batch_check.py` (baru):
  - Membandingkan hasil batch vs per gambar (jumlah kotak, IoU, skor) dan ms/gambar per ukuran batch.
  - Opsi `--half` / `--cudnn-benchmark`.
  - Kesimpulan: "BATCH MENGUBAH HASIL" / "tidak menerima batch" / "layak dinyalakan".
- `docs/UJI-LAG.md`: bagian "Uji di RTX 4060" (langkah 0–4, termasuk 5 kamera) dan baris tombol mundur baru.

## Config baru (semua YAML di engine/config diperbarui)

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

## Tombol mundur

- `detector.share_across_cameras: false`
- `detector.batch_inference: false`
- `detector.cudnn_benchmark: false`

## Tes baru

- `test_shared_detector.py` (16), termasuk ujung ke ujung dua kamera di runtime.
- `test_batch_check.py` (4).
- `test_onnx_provider_check.py` +2.

## Belum diuji di GPU

- Batching LibreYOLO yang sesungguhnya.
- FP16 di 4060.
- 5 kamera.

Semuanya ada di `docs/UJI-LAG.md` bagian "Uji di RTX 4060".
