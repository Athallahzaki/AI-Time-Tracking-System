"""Pembanding: checkpoint OSNet yang SAMA di PyTorch GPU (env reid-env). Jalankan:
    python X:\\data\\diag_reid_torch.py <checkpoint best.pth> [folder tools\\reid_train]
Kalau di sini cepat (beberapa ms) dan di ONNX Runtime lambat, masalahnya di ORT/cuDNN."""
import sys
import time
from pathlib import Path

import torch

CKPT = sys.argv[1] if len(sys.argv) > 1 else r"X:\data\runs\ain_cepat\best.pth"
KIT = Path(sys.argv[2] if len(sys.argv) > 2 else r"X:\Projek\AI-Time-Tracking-System\tools\reid_train")
sys.path.insert(0, str(KIT))
from export_onnx import muat_checkpoint  # noqa: E402

print("torch:", torch.__version__, "| CUDA:", torch.cuda.is_available(), "| cuDNN:", torch.backends.cudnn.version())
model, arch, info = muat_checkpoint(CKPT, None, False)
model = model.cuda().eval()
print("model:", arch, info)
for benchmark in (False, True):
    torch.backends.cudnn.benchmark = benchmark
    print(f"\n== cudnn.benchmark={benchmark}")
    print("putaran   b1        b2        b3        b4        b8   (ms)")
    with torch.inference_mode():
        for putaran in range(3):
            hasil = []
            for n in (1, 2, 3, 4, 8):
                x = torch.randn(n, 3, 256, 128, device="cuda")
                torch.cuda.synchronize()
                t = time.perf_counter()
                model(x)
                torch.cuda.synchronize()
                hasil.append(f"{1000 * (time.perf_counter() - t):8.1f}")
            print(f"{putaran:<8d}" + "  ".join(hasil))
