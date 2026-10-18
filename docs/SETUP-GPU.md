# Setup engine di mesin GPU (RTX 4060 / RTX 3050 / GTX 1060)

## Pasang

Windows, PowerShell, env baru (env lama `vision-engine` berisi xformers dan
sisa onnxruntime 1.30 -- lebih cepat mulai bersih daripada membereskannya):

```powershell
conda create -n engine-gpu python=3.12 -y
conda activate engine-gpu
cd <repo>
pip install -r engine/requirements-gpu-rtx4060.txt     # atau requirements-gpu-rtx3050.txt / -gtx1060.txt
python scripts/check_gpu_env.py
python -m pytest engine/tests -q
```

`check_gpu_env.py` wajib tanpa GAGAL. Ia menangkap: torch CPU-only dari PyPI,
GPU yang tidak didukung build torch, onnxruntime-gpu CUDA 13 di env CUDA 12,
`onnxruntime` (CPU) dan `onnxruntime-gpu` terpasang bersamaan, LibreYOLO < 1.6,
driver < 560, xformers, dan opencv ganda. Bila `models/scrfd_10g_bnkps.onnx`
ada, ia juga membuka sesi onnxruntime dan memastikan CUDA benar-benar aktif.

Setelah semua OK, simpan versi persisnya: `pip freeze > bench-out/freeze-<gpu>.txt`.

## Kenapa ketiganya memakai paket yang SAMA

| | GTX 1060 | RTX 3050 | RTX 4060 |
|---|---|---|---|
| Arsitektur | Pascal sm_61 | Ampere sm_86 | Ada sm_89 |
| torch | 2.14.1+cu126 | 2.14.1+cu126 | 2.14.1+cu126 |
| onnxruntime-gpu | < 1.27 (CUDA 12) | < 1.27 | < 1.27 |
| libreyolo | >= 1.6 | >= 1.6 | >= 1.6 |

- Build torch cu128/cu130 tidak membawa kernel Pascal. cu126 satu-satunya yang
  mendukung ketiga GPU, dan PyTorch 2.14 adalah rilis terakhir yang membuatnya
  (2.15 menghapus CUDA 12.6). Selama GTX 1060 masih dipakai, torch dipatok di 2.14.1.
- onnxruntime-gpu >= 1.27 hanya CUDA 13. Torch dan onnxruntime sekeluarga CUDA 12
  menghindari campuran DLL (kasus `cublasLt64_13.dll`, rekognisi diam-diam di CPU).
- Untuk 4060/3050 saja, CUDA 13 (torch cu130 + onnxruntime-gpu >= 1.27) juga
  mungkin. Tidak ada alasan performa untuk itu di proyek ini: penghambatnya
  peluncuran kernel, bukan versi CUDA. Satu env untuk ketiga mesin lebih murah.

## Yang berbeda: config engine

| Kunci | GTX 1060 | RTX 3050 | RTX 4060 |
|---|---|---|---|
| `detector.model_path` | LibreDFINEs.pt (S) | mulai S, naik ke M bila cukup | LibreDFINEm.pt (M) |
| `detector.half` | false (FP16 Pascal lambat) | false sampai diukur | false (FP16 terukur lebih lambat) |
| `detector.cuda_graph` | true, belum diukur | true | true (29,5 ms/gambar end-to-end, hasil identik) |
| `detector.batch_inference` / `max_batch` | sesuai batch_check | sesuai batch_check | false (batch 2/5 lebih lambat per gambar) |
| `recognition.onnx_gpu_mem_limit_mb` | 1024 | 1024 (VRAM 4-6 GB) | null |
| `ingest.live_buffer` | latest | latest | latest |

Angka 3050 belum ada: jalankan `docs/UJI-LAG.md` langkah 3b dan 3c di sana dulu.
VRAM 3050 laptop 4 GB: setiap ukuran batch dengan CUDA graph menyimpan graph
sendiri, jadi `max_batch` besar memakan VRAM.

## Env uji TensorRT (RTX 4060, paket ea-r11)

Untuk mengukur rekognisi wajah lewat TensorRT EP onnxruntime (glintr100 33 ms + SCRFD
21 ms per wajah di CUDA EP, uji 15 Okt). Dipasang di **env kloningan**: env kerja
`vision-engine` tidak berubah, dan kalau hasilnya buruk cukup `conda env remove -n vision-engine-trt`.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-env-trt.ps1
conda activate vision-engine-trt
python -m engine.tools.face_bench --config engine/config/demo-4060.yaml --source C:\video\uji-siap.mp4 --varian cuda,trt16 --simpan-potongan bench-out\potongan --json bench-out\face-bench-trt.json
python -m engine.tools.scrfd_dynamic --input engine/models/recognition/scrfd_10g_bnkps.onnx --output engine/models/recognition/scrfd_10g_bnkps_dinamis.onnx
python -m engine.tools.face_bench --config engine/config/demo-4060.yaml --potongan bench-out\potongan --varian cuda,trt16 --ukuran 640,320 --model-detektor engine/models/recognition/scrfd_10g_bnkps_dinamis.onnx --json bench-out\face-bench-320.json
```

TensorRT EP butuh pustaka TensorRT 10 (nvinfer) yang cocok dengan build onnxruntime-gpu.
Skrip memilihnya dari versi onnxruntime-gpu di env (paket pip `tensorrt-cu12-libs`):

| onnxruntime-gpu | TensorRT build CI |
|---|---|
| 1.21 | 10.8 |
| 1.22, 1.23 | 10.9 |
| 1.24, 1.25, 1.26 | 10.14 |

Sumber: `tools/ci_build/github/azure-pipelines/templates/common-variables.yml` di tiap tag
rilis onnxruntime (dokumentasi resmi TensorRT EP hanya mencatat sampai 1.22). Penentu
akhirnya baris `tensorrt-sesi` di `check_gpu_env.py --tensorrt`: sesi SCRFD sungguhan.

Yang perlu diketahui:

- Build engine TensorRT pertama memakan waktu (SCRFD ±1 menit, glintr100 bisa beberapa
  menit). Cache di `engine/data/trt-cache/ort<versi>-trt<versi>-fp16/` (tidak di-commit),
  dipisah per versi + presisi karena onnxruntime memakai ulang cache lama tanpa memeriksa.
  Jalankan `face_bench` sebelum engine dinyalakan watchdog supaya cache sudah terisi
  (watchdog `-StartupGraceSeconds` 240).
- `recognition.onnx_tensorrt: true` yang tidak bisa aktif = engine menolak start, kode 2
  (watchdog menunggu config berubah), bukan diam-diam jalan di CUDA EP.
- Model SCRFD dinamis dari `scrfd_dynamic` baru dipakai engine kalau
  `face_detector_model` diarahkan ke berkas itu; berkas asli tidak diubah.
- GTX 1060 (Pascal) tidak masuk jalur ini.

## Dua env, jangan tertukar (temuan 17 Okt)

Env latihan ReID (`reid-env`, `tools/reid_train/README.md`) memasang `onnxruntime` **CPU**. Engine yang
dijalankan dari env itu dulu diam-diam memakai CPU untuk rekognisi dan ReID; sejak ea-r14 engine
menolak start ("onnxruntime ini tidak membawanya"). Pakai dua jendela PowerShell terpisah dan cek
nama env di prompt. Mencampur aktivasi venv/conda di satu jendela juga bisa merusak Python
(`No module named 'encodings'`, `sys.prefix` menunjuk folder repo): buka jendela baru.

**NVRTC: JANGAN di PATH** (eb-r12, diukur di 1060 18 Okt). Bila cuDNN 9 menemukan `nvrtc64_120_0.dll`
lewat PATH, tiap pergantian batch size OSNet di onnxruntime stall detik-an. Tanpa NVRTC, cuDNN menulis
"Could not locate nvrtc64_120_0.dll" ke stderr C; spam itu kondisi BENAR dan engine mengalihkannya ke
`logs\engine\engine-c-stderr.log` (±19 KB per 5 menit). `check_gpu_env.py` baris `nvrtc`: OK bila tidak
di PATH, PERINGATAN bila ada (keluarkan folder `CUDA\vXX\bin` / `nvidia\cuda_nvrtc\bin` dari PATH jendela
engine). Ini aman karena DLL CUDA/cuDNN engine datang dari pip (`onnxruntime-gpu[cuda,cudnn]`, dimuat
`preload_dlls`), bukan dari toolkit. Saran lama (ea-r14, "tambahkan ke PATH") sudah dicabut.

## Sumber versi

- Wheel torch cu126 Windows: https://download.pytorch.org/whl/cu126/torch/ (2.14.1, cp310-cp314)
- Penghapusan CUDA 12.6 / Pascal di 2.15: https://github.com/pytorch/pytorch/issues/190385
- cu128 ke atas tanpa Maxwell/Pascal: https://dev-discuss.pytorch.org/t/cuda-toolkit-version-and-architecture-support-update-maxwell-and-pascal-architecture-support-removed-in-cuda-12-8-and-12-9-builds/3128
- Riwayat onnxruntime-gpu: https://pypi.org/project/onnxruntime-gpu/#history
- TensorRT EP (opsi, tabel versi s.d. 1.22): https://onnxruntime.ai/docs/execution-providers/TensorRT-ExecutionProvider.html
- Versi TensorRT build per rilis: https://github.com/microsoft/onnxruntime/blob/v1.26.0/tools/ci_build/github/azure-pipelines/templates/common-variables.yml
