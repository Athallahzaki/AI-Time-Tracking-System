# Perubahan: requirements engine per GPU (termasuk PyTorch) + pemeriksa env

- `engine/requirements-torch-cu126.txt`: torch 2.14.1+cu126, torchvision 0.29.1+cu126
  (extra index download.pytorch.org/whl/cu126, versi lokal dipatok persis).
- `engine/requirements-gpu.txt`: torch cu126 + engine dasar + libreyolo>=1.6,<2 +
  onnxruntime-gpu[cuda,cudnn]<1.27 + pytest.
- `engine/requirements-gpu-rtx4060.txt`, `-rtx3050.txt`, `-gtx1060.txt`: masing-masing
  `-r requirements-gpu.txt` + config yang disarankan untuk GPU itu.
- `scripts/check_gpu_env.py`: OK/PERINGATAN/GAGAL untuk python, torch (CPU-only?),
  arsitektur GPU vs build, matmul CUDA, libreyolo, onnxruntime (CUDA 13 di env CUDA 12,
  paket CPU+GPU ganda, sesi CUDA sungguhan bila model SCRFD ada), PyAV, OpenCV, driver,
  xformers.
- `docs/SETUP-GPU.md`, `README.md`: cara pasang dan alasan versi.
- Tes: `engine/tests/test_check_gpu_env.py` (10). Suite: 550 passed, 3 skipped.

Paket ketiga GPU sengaja sama: cu126 satu-satunya build torch yang membawa
kernel Pascal (2.14 rilis terakhirnya), dan onnxruntime-gpu < 1.27 juga CUDA 12.
