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
| `detector.cuda_graph` | true, belum diukur | true | true (57 -> 12,6 ms) |
| `detector.batch_inference` / `max_batch` | sesuai batch_check | sesuai batch_check | true / 5 bila batch_check setuju |
| `recognition.onnx_gpu_mem_limit_mb` | 1024 | 1024 (VRAM 4-6 GB) | null |
| `ingest.live_buffer` | latest | latest | latest |

Angka 3050 belum ada: jalankan `docs/UJI-LAG.md` langkah 3b dan 3c di sana dulu.
VRAM 3050 laptop 4 GB: setiap ukuran batch dengan CUDA graph menyimpan graph
sendiri, jadi `max_batch` besar memakan VRAM.

## Sumber versi

- Wheel torch cu126 Windows: https://download.pytorch.org/whl/cu126/torch/ (2.14.1, cp310-cp314)
- Penghapusan CUDA 12.6 / Pascal di 2.15: https://github.com/pytorch/pytorch/issues/190385
- cu128 ke atas tanpa Maxwell/Pascal: https://dev-discuss.pytorch.org/t/cuda-toolkit-version-and-architecture-support-update-maxwell-and-pascal-architecture-support-removed-in-cuda-12-8-and-12-9-builds/3128
- Riwayat onnxruntime-gpu: https://pypi.org/project/onnxruntime-gpu/#history
