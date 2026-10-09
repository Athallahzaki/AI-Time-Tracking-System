# Perubahan: rincian span detector di bench

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

## Perubahan

- `engine/pipeline/engine.py`: frame lazy (PyAV) dikonversi sebelum detector di
  span baru `frame_convert`; span `detector` tetap mencakupnya (sebanding dengan
  angka lama). Span tambahan dari `detector.last_spans` dicatat.
- `engine/perception/dfine_detector.py`: `detector_prepare` (pre_resize OpenCV),
  `detector_infer` (LibreYOLO: pra-proses + forward + pasca-proses LibreYOLO,
  diakhiri .cpu()), `detector_post` (Results -> Detection).
- `engine/perception/shared_detector.py` (runtime): `detector_shared_infer`
  (antre + inferensi di thread dispatcher) dan `detector_post`.

Tes: test_detector_spans.py (2), test_cuda_graph_batch.py +1. Suite lulus.
