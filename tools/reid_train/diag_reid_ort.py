"""Diagnosis OSNet di ONNX Runtime (env vision-engine). Simpan di luar repo, jalankan:
    python X:\\data\\diag_reid_ort.py [path onnx]
Mencetak versi, operasi yang jatuh ke CPU, dan waktu per batch untuk 3 konfigurasi."""
import os
import sys
import tempfile
import time

import numpy as np
import onnxruntime as ort

ONNX = sys.argv[1] if len(sys.argv) > 1 else r"X:\Projek\AI-Time-Tracking-System\engine\models\reid\osnet_reid.onnx"
print("python      :", sys.executable)
print("onnxruntime :", ort.__version__, "| tersedia:", ort.get_available_providers())
try:
    import torch
    print("torch       :", torch.__version__, "| cuDNN torch:", torch.backends.cudnn.version())
except Exception as e:  # noqa: BLE001
    print("torch       : tidak bisa diimpor:", e)
if hasattr(ort, "preload_dlls"):
    try:
        ort.preload_dlls()
        print("preload_dlls: ok")
    except Exception as e:  # noqa: BLE001
        print("preload_dlls: gagal:", e)
print("nvrtc di PATH:", [p for p in os.environ.get("PATH", "").split(os.pathsep)
                         if p and os.path.isfile(os.path.join(p, "nvrtc64_120_0.dll"))] or "TIDAK")


def sesi(cuda_opsi, matikan_optimasi=False, verbose=False):
    so = ort.SessionOptions()
    if matikan_optimasi:
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    if verbose:
        so.log_severity_level = 0
    return ort.InferenceSession(ONNX, so, providers=[("CUDAExecutionProvider", cuda_opsi), "CPUExecutionProvider"])


# 1) Penempatan node: tangkap log verbose ORT (stderr level C) ke berkas sementara.
log = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
log.close()
sys.stderr.flush()
simpan = os.dup(2)
fd = os.open(log.name, os.O_WRONLY | os.O_TRUNC)
os.dup2(fd, 2)
try:
    s = sesi({}, verbose=True)
    del s
finally:
    sys.stderr.flush()
    os.dup2(simpan, 2)
    os.close(fd)
    os.close(simpan)
teks = open(log.name, encoding="utf-8", errors="replace").read()
print("\n== Penempatan node (dari log verbose ORT) ==")
baris = [b for b in teks.splitlines() if "placed on" in b or "Provider: [" in b or "Node placements" in b]
for b in baris[:20]:
    print("  ", b.strip()[:400])
if not baris:
    print("   (tidak ada baris penempatan; log lengkap di", log.name, ")")
print("   jumlah baris 'nvrtc' di log:", teks.lower().count("nvrtc"))

# 2) Waktu per batch.
KONFIG = [
    ("bawaan", {}, False),
    ("HEURISTIC + workspace kecil", {"cudnn_conv_algo_search": "HEURISTIC", "cudnn_conv_use_max_workspace": "0"}, False),
    ("optimasi graf MATI", {}, True),
]
rng = np.random.default_rng(0)
for nama, opsi, mati in KONFIG:
    s = sesi(opsi, matikan_optimasi=mati)
    nama_in = s.get_inputs()[0].name
    print(f"\n== {nama} | aktif {s.get_providers()}")
    print("putaran   b1        b2        b3        b4        b8   (ms)")
    for putaran in range(3):
        hasil = []
        for n in (1, 2, 3, 4, 8):
            x = rng.standard_normal((n, 3, 256, 128)).astype(np.float32)
            t = time.perf_counter()
            s.run(None, {nama_in: x})
            hasil.append(f"{1000 * (time.perf_counter() - t):8.1f}")
        print(f"{putaran:<8d}" + "  ".join(hasil))
    del s
