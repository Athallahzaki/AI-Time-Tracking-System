"""Profil waktu per OPERASI OSNet di ONNX Runtime (env vision-engine). Jalankan:
    python tools/reid_train/diag_reid_profile.py [path onnx]

Mengukur kondisi STEADY-STATE: run warmup (cuDNN algo search, alokasi) dibuang
dari statistik. Membandingkan cudnn_conv_algo_search HEURISTIC vs EXHAUSTIVE,
untuk batch 1 dan 4, plus latensi end-to-end tanpa overhead profiler.

CATATAN: breakdown per-op di CUDA EP adalah waktu dispatch di CPU, bukan waktu
GPU. Untuk waktu kernel GPU yang sebenarnya pakai Nsight Systems.

SENGAJA tanpa `import torch`: torch membuat cuDNN ikut memakai NVRTC sehingga
setiap shape baru stall 10-15 detik. Kondisi ini harus sama dengan engine."""
import collections
import json
import os
import sys
import tempfile
import time

import numpy as np
import onnxruntime as ort

if hasattr(ort, "preload_dlls"):
    ort.preload_dlls()

ONNX = sys.argv[1] if len(sys.argv) > 1 else (
    r"D:\Hobby\Coding\Forgor\AI-Time-Tracking-System\engine\models\reid\osnet_ain_reid.onnx")
BATCHES = (1, 4)
SEARCHES = ("HEURISTIC", "EXHAUSTIVE")
WARM = 20      # run yang dibuang (algo search, alokasi memori)
RUNS = 100     # run yang dihitung


def nvrtc_termuat():
    if os.name != "nt":
        return "n/a (bukan Windows)"
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetModuleHandleW.restype = ctypes.c_void_p
    k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    ada = [n for n in ("nvrtc64_120_0.dll", "nvrtc64_120_0.alt.dll") if k32.GetModuleHandleW(n)]
    return f"YA {ada}" if ada else "TIDAK"


def providers(search):
    return [("CUDAExecutionProvider", {"cudnn_conv_algo_search": search}),
            "CPUExecutionProvider"]


def buat_sesi(search, so=None):
    s = ort.InferenceSession(ONNX, so, providers=providers(search)) if so else \
        ort.InferenceSession(ONNX, providers=providers(search))
    if s.get_providers()[0] != "CUDAExecutionProvider":
        sys.exit(f"!! CUDA EP tidak aktif (tersedia: {ort.get_available_providers()}). Dibatalkan.")
    return s


def latensi(search, batch, x):
    """Latensi end-to-end tanpa profiler (profiler menambah overhead per node)."""
    s = buat_sesi(search)
    nama = s.get_inputs()[0].name
    t = time.perf_counter()
    s.run(None, {nama: x})
    pertama = (time.perf_counter() - t) * 1e3
    for _ in range(WARM - 1):
        s.run(None, {nama: x})
    ts = []
    for _ in range(RUNS):
        t = time.perf_counter()
        s.run(None, {nama: x})
        ts.append((time.perf_counter() - t) * 1e3)
    del s
    ts = np.array(ts)
    return pertama, np.median(ts), np.percentile(ts, 95)


def profil(search, batch, x):
    so = ort.SessionOptions()
    so.enable_profiling = True
    so.profile_file_prefix = os.path.join(tempfile.gettempdir(), f"osnet_{search}_b{batch}")
    s = buat_sesi(search, so)
    nama = s.get_inputs()[0].name
    for _ in range(WARM + RUNS):
        s.run(None, {nama: x})
    berkas = s.end_profiling()
    del s

    data = json.load(open(berkas, encoding="utf-8"))
    awal_run = sorted(e["ts"] for e in data if e.get("name") == "model_run")
    if len(awal_run) < WARM + RUNS:
        raise RuntimeError(f"event model_run cuma {len(awal_run)}, harusnya {WARM + RUNS}")
    t0 = awal_run[WARM]  # semua event sebelum run ke-WARM = warmup, dibuang

    per_op = collections.defaultdict(float)
    per_node = collections.defaultdict(float)
    for ev in data:
        if (ev.get("cat") != "Node" or ev["ts"] < t0
                or not ev.get("name", "").endswith("_kernel_time")):
            continue
        op = ev.get("args", {}).get("op_name", "?")
        ms = ev["dur"] / 1000.0 / RUNS          # mikrodetik -> ms, rata-rata per run
        per_op[op] += ms
        per_node[(op, ev["name"][:-12])] += ms
    return per_op, per_node, berkas


print(f"onnxruntime {ort.__version__} | torch di proses ini: "
      f"{'YA (BAHAYA)' if 'torch' in sys.modules else 'TIDAK'}")
print(f"warmup {WARM} run dibuang, statistik dari {RUNS} run\n")

for batch in BATCHES:
    x = np.random.default_rng(0).standard_normal((batch, 3, 256, 128)).astype(np.float32)
    for search in SEARCHES:
        pertama, med, p95 = latensi(search, batch, x)
        per_op, per_node, berkas = profil(search, batch, x)
        total = sum(per_op.values())
        print(f"== batch {batch} | {search}")
        print(f"   end-to-end: run pertama {pertama:8.1f} ms | median {med:6.2f} ms | "
              f"p95 {p95:6.2f} ms | {batch / med * 1e3:7.1f} img/s")
        print(f"   total dispatch CPU (profiler) {total:6.2f} ms per run  ({berkas})")
        for op, ms in sorted(per_op.items(), key=lambda kv: -kv[1])[:8]:
            print(f"     {op:26s} {ms:8.3f} ms  ({100 * ms / max(total, 1e-9):5.1f}%)")
        print("   node termahal:")
        for (op, node), ms in sorted(per_node.items(), key=lambda kv: -kv[1])[:5]:
            print(f"     {ms:8.3f} ms  {op}  {node}")
        print()

print("NVRTC termuat:", nvrtc_termuat())
