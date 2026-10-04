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

## Revisi 4 Okt 03:00 (setelah model wajah dipindah ke engine/models/)

- `demo-1060.yaml`: path model dari repo laptop 1060
  (`engine/models/recognition/scrfd_10g_bnkps.onnx`,
  `engine/models/embedder/glintr100.onnx`) dipertahankan.
- `test_demo_1060_config.py`: path file model boleh beda per mesin. Tes
  sebelumnya gagal karena itu, bukan karena perilakunya berubah. Nama file tetap
  harus sama.
- `scripts/check_gpu_env.py`: SCRFD dicari juga di `engine/models/recognition/`.
  Bila tidak ketemu, sekarang muncul PERINGATAN `onnx-sesi`. Dulu barisnya hilang
  diam-diam, dan itulah sebabnya model yang hilang tidak terlihat di laptop 1060.

## Revisi 4 Okt 06:15: profil RTX 4060

- `engine/config/demo-4060.yaml`: D-FINE M, `half: true`, `cuda_graph: true`,
  `fast_preprocess: true`, `target_fps: 10`. Rekognisi, ingest, dan tracker sama
  persis dengan demo-1060.
- `engine/tests/test_demo_4060_config.py` (2).
- `docs/DEMO-1060.md`: bagian "Di laptop RTX 4060".

## Revisi 4 Okt 09:30: engine keluar dari power throttling Windows

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
