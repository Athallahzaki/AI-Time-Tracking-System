# Perubahan: alat profil detector (GPU vs CPU) + batch_check --no-half

Dasar: uji RTX 4060 3 Okt langkah 0-3.

- ingest_ceiling (--work torch 110 ms): semua varian latest 94-95% dari harapan,
  decode 32 fps (sumber 30 fps) -> ingest BUKAN penghambat di 4060.
- batch_check: D-FINE M 84 ms/gambar, sama dengan GTX 1060. "FP16" vs "tanpa
  --half" identik karena config lokal sudah `half: true` (baris `half True` di
  kedua run), jadi FP32 belum pernah diukur. cudnn.benchmark: 0%. Batch 5:
  1,10x, benar (IoU 1,000).

Waktu yang tidak turun saat GPU diganti, tidak turun saat batch, hampir pasti
bukan waktu GPU. Alat baru memisahkannya.

## Baru: engine/tools/detector_profile.py

    python -m engine.tools.detector_profile --source C:\video\uji-siap.mp4 --torch-profile bench-out\profil-4060.txt --json bench-out\profil-4060.json

Mengukur pre_resize, panggilan LibreYOLO penuh (dengan cuda.synchronize),
forward GPU murni modul torch di dalam LibreYOLO (FP32 dan FP16, tensor sudah di
GPU), letak parameter model (cuda/cpu), dan clock/P-state/daya GPU via
nvidia-smi selama pengukuran. Vonis: PENGHAMBAT DI CPU / DI GPU / GPU TIDAK NAIK
CLOCK / MODEL DI CPU. `--torch-profile` menulis tabel operasi terberat.

## engine/tools/batch_check.py

`--no-half` memaksa FP32 apa pun isi config (eksklusif dengan `--half`).

## docs/UJI-LAG.md

Langkah 2 memakai `--no-half`; langkah baru 3b (detector_profile).

## Tes

test_detector_profile.py (7). Seluruh suite: 524 passed, 3 skipped; policy_grep bersih.

## Revisi v4 (setelah profil pertama di 4060, 18:02)

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
