# onnxruntime-gpu untuk Pascal + tolak rekognisi yang diam-diam jalan di CPU (3 Okt 2026)

Ekstrak di root proyek di atas paket `setup-uji-rekognisi-wajah_config-face-async-sync_log-worker`.
Verifikasi: 484 tes lulus.

## Gejala (GTX 1060)
```
Error loading onnxruntime_providers_cuda.dll which depends on "cublasLt64_13.dll" which is missing
Failed to create CUDAExecutionProvider. Require cuDNN 9.* and CUDA 13.*
```

## Penyebab
- onnxruntime-gpu 1.30 dibangun untuk CUDA 13. Menurut catatan rilis 1.26, CUDA 12 dibuang mulai 1.27.
- CUDA 13 tidak lagi mendukung GPU Pascal (GTX 10xx). Memasang CUDA 13 pun tidak akan menolong di 1060.
- onnxruntime tidak error dalam kasus ini: ia menulis peringatan lalu jalan di CPU.

## Perbaikan
- `engine/identity/face_onnx.py`:
  - Memanggil `onnxruntime.preload_dlls()` sekali sebelum sesi CUDA pertama. Fungsi ini memuat DLL
    CUDA/cuDNN dari paket pip `nvidia-*` atau dari folder lib torch.
  - Bila CUDA diminta tetapi tidak aktif, engine BERHENTI dengan pesan yang menunjuk penyebabnya, tidak
    lagi jalan diam-diam di CPU.
  - Provider yang benar-benar aktif dicetak di log.
- `engine/requirements-face.txt`: `onnxruntime-gpu[cuda,cudnn]>=1.21,<1.27`.
- Tes baru: `engine/tests/test_onnx_provider_check.py` (3).

## Pasang ulang di mesin
```
pip uninstall -y onnxruntime-gpu onnxruntime
pip install "onnxruntime-gpu[cuda,cudnn]>=1.21,<1.27"
```
