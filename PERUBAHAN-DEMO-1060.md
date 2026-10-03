# Perubahan: profil demo GTX 1060 + preflight

Isinya kumulatif v14, ditambah profil demo. Perubahan v15 (konversi OpenCV,
scaling_check tiga jalur) sengaja TIDAK ikut, karena versi dibekukan untuk demo.

Dasar: batch_check 4 Okt di GTX 1060 Max-Q, video 848x478:

- M eager 70-75 ms, M graph 70,9 ms;
- S eager 55-59 ms, S graph 48,1 ms (1,17x);
- semua hasil identik.

## Berkas baru

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

## Cara pakai

```powershell
python -m pytest engine/tests -q
python scripts/preflight_demo.py
```

Lalu ikuti docs/DEMO-1060.md.
