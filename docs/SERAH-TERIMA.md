# Serah Terima

Ditulis ulang di akhir setiap sesi. Terakhir: 16 Oktober 2026, sesi EA + EB (paket ea-r11). `SERAH-TERIMA-EA-R3.md` tetap berlaku untuk ReID/`schedule_off`/watchdog. Angka uji: CHANGELOG ea-r9 (vonis 14–15 Okt) dan ea-r10 (gerbang).

## Selesai

- Vonis uji 4060: 6 fps × 5 kamera **LULUS**; crash GPU → kode 3 **lulus**; batch D-FINE **gugur**; P18 **bukan bug jam**; NVDEC **tunda**; hambatan = **rekognisi wajah** (54 ms/wajah = SCRFD ±21 + glintr100 ±33).
- Gerbang rekognisi gugur sebagai solusi beban (ea-r10); metrik "identifikasi: ... median" ada di log dan `lag_probe`.
- ea-r11 (BELUM diukur, 4060 tidak tersedia): TensorRT EP opsional (`recognition.onnx_tensorrt`, default mati, tidak aktif = kode 2), `engine/tools/face_bench.py`, `engine/tools/scrfd_dynamic.py`, `scripts/setup-env-trt.ps1`, `check_gpu_env.py --tensorrt`.
- Tes cloud: lihat CHANGELOG ea-r11; `policy_grep` bersih.

## Belum (diurutkan)

1. **Ukur ea-r11 di 4060** (uji manual #1–#4). Patokan: cos embedder ≥ 0,99, ms/wajah, lalu gladi dengan TensorRT menyala: `rata2 ms`, porsi buang, `identifikasi: ... median` tidak naik.
2. Stress test bertahap dengan video berorang banyak (mis. MOT20) sebelum M4 (6 Nov).
3. MSDA "No accelerated MSDA provider": coba `libreyolo[hub-kernels]` di env kloningan (prioritas rendah).
4. `swscale_resize: true` setelah `scaling_check`.
5. Traceback asli uji crash ea-r8 belum dicatat.
6. Kolom `drop/s` `summarize_gladi` = `frames_replaced`; ganti nama/beri catatan.
7. Backend: ReID dihitung salah diam-diam (SERAH-TERIMA-EA-R3 #2); endpoint baca + video belum butuh login.
8. Opsional: kalibrasi `embed_max_yaw` saja.

## Keputusan yang perlu disetujui

- Penjadwal tahap 2: batch gugur → tetap `free`. Rapat EA–EB.
- Gerbang rekognisi tidak dipakai di profil; beban dikejar lewat percepatan model.
- Patokan setiap perubahan rekognisi: median waktu sampai dikenali tidak naik (dok. 12 §2.2: ≤ 5 dtk).
- SCRFD 320 hanya boleh dipakai bila wajah hilang di `face_bench` kecil DAN median identifikasi di gladi tidak naik.

## Uji manual di laptop

1. Baseline: gladi 5 menit `demo-4060.yaml` asli di env `vision-engine` (watchdog `-HealthSeconds 2 -TargetFps 6`, `lag_probe` ke CSV baru). Catat `rata2 ms`, porsi buang, `identifikasi: ... median` (harap ±4–6 dtk).
2. Env: `powershell -ExecutionPolicy Bypass -File scripts\setup-env-trt.ps1`. Harap: `tensorrt` OK dan `tensorrt-sesi` OK. Gagal → kirim `bench-out\env-trt.json`.
3. `conda activate vision-engine-trt`, lalu `python -m engine.tools.face_bench --config engine/config/demo-4060.yaml --source <video> --varian cuda,trt16 --simpan-potongan bench-out\potongan --json bench-out\face-bench-trt.json`. Kirim tabelnya.
4. `python -m engine.tools.scrfd_dynamic --input engine/models/recognition/scrfd_10g_bnkps.onnx --output engine/models/recognition/scrfd_10g_bnkps_dinamis.onnx`, lalu face_bench `--potongan bench-out\potongan --ukuran 640,320 --model-detektor <dinamis>`. DITOLAK = SCRFD harus diekspor ulang dari sumber.
5. Bila #3 bagus: salinan config dengan `onnx_tensorrt: true`, gladi seperti #1 di env TRT, bandingkan.

## Langkah berikutnya

Uji manual #1–#4 → putuskan TensorRT (dan 320) dari angka → gladi #5 → stress test.
