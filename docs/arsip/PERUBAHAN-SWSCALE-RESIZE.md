# Perubahan: swscale_resize (YUV -> RGB 640 langsung) + scaling_check

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

## Perubahan

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

## Cara uji (4060)

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
