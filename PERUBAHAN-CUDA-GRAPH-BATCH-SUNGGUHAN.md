# Perubahan: CUDA graph + batch sungguhan untuk D-FINE (LibreYOLO >= 1.6)

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

## Temuan di kode LibreYOLO (1.6.0, rilis 27 Sep 2026)

- `predict(cuda_graph=True|"auto")`: forward diputar dari CUDA graph, D-FINE
  `SUPPORTS_CUDA_GRAPH = True`, diverifikasi bit-identik oleh LibreYOLO. Satu
  graph per bentuk input (maks 8 di cache).
- `predict(list, batch=N)`: SATU forward bertumpuk per potongan N gambar.
  Daftar gambar TANPA `batch=` diproses satu per satu. Itu sebabnya batch_check
  hanya 1,1x: adapter kita mengirim daftar tanpa `batch=`.

## Perubahan

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

## Tes

test_cuda_graph_batch.py (14), test_detector_profile.py diperbarui.
Seluruh suite: 541 passed, 3 skipped; policy_grep bersih.
