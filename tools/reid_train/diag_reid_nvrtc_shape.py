"""Dua tes sekaligus untuk OSNet di ONNX Runtime (CUDA EP, HEURISTIC):

  A. NVRTC on vs off: tiap mode dijalankan di PROSES TERPISAH (DLL yang sudah
     ter-load tidak bisa di-unload), lalu dibandingkan cold start & steady-state.
  B. Ganti batch size di dalam SATU session: apakah tiap shape baru bikin stall?

Jalankan:
    python tools/reid_train/diag_reid_nvrtc_shape.py [path onnx]
"""
import os
import subprocess
import sys
import time

DEFAULT_ONNX = (r"D:\Hobby\Coding\Forgor\AI-Time-Tracking-System"
                r"\engine\models\reid\osnet_ain_reid.onnx")
MODES = ("nvrtc", "tanpa-nvrtc")
# urutan shape: shape baru muncul berselang-seling dengan shape lama
URUTAN = [1, 1, 3, 3, 1, 5, 5, 3, 8, 8, 1, 4, 4, 2, 2]
STEADY_BATCH = (1, 4)
WARM, RUNS = 20, 100


def child(mode, onnx_path):
    if mode == "nvrtc":
        # DLL CUDA/cuDNN/NVRTC milik torch; NVRTC ikut ter-load lewat PATH
        import torch
        tl = os.path.join(os.path.dirname(torch.__file__), "lib")
        os.add_dll_directory(tl)
        os.environ["PATH"] = tl + os.pathsep + os.environ["PATH"]
        import onnxruntime as ort
    else:
        # kondisi run pertama kamu: tanpa torch, DLL dari preload_dlls, NVRTC tidak ada
        import onnxruntime as ort
        if hasattr(ort, "preload_dlls"):
            ort.preload_dlls()
    import numpy as np

    prov = [("CUDAExecutionProvider", {"cudnn_conv_algo_search": "HEURISTIC"}),
            "CPUExecutionProvider"]
    rng = np.random.default_rng(0)
    data = {b: rng.standard_normal((b, 3, 256, 128)).astype(np.float32)
            for b in set(URUTAN) | set(STEADY_BATCH)}

    def ms(fn):
        t = time.perf_counter()
        fn()
        return (time.perf_counter() - t) * 1e3

    print(f"\n######## MODE: {mode} ########")

    # --- Tes B: satu session, batch size berganti-ganti ---
    t = time.perf_counter()
    s = ort.InferenceSession(onnx_path, providers=prov)
    print(f"buat session: {(time.perf_counter() - t) * 1e3:.0f} ms "
          f"(provider aktif: {s.get_providers()[0]})")
    if s.get_providers()[0] != "CUDAExecutionProvider":
        print(f"!! CUDA EP tidak aktif (tersedia: {ort.get_available_providers()}). "
              f"Tes dibatalkan, angka CPU tidak relevan.")
        sys.exit(2)
    nama = s.get_inputs()[0].name
    sudah = set()
    print("[B] ganti shape dalam satu session:")
    for b in URUTAN:
        d = ms(lambda: s.run(None, {nama: data[b]}))
        tanda = "SHAPE BARU" if b not in sudah else ""
        sudah.add(b)
        print(f"    batch {b}: {d:9.1f} ms  {tanda}")

    # --- Tes A: steady-state di session yang sama (semua shape sudah warm) ---
    print("[A] steady-state:")
    for b in STEADY_BATCH:
        for _ in range(WARM):
            s.run(None, {nama: data[b]})
        ts = np.array([ms(lambda: s.run(None, {nama: data[b]})) for _ in range(RUNS)])
        med = float(np.median(ts))
        print(f"    batch {b}: median {med:6.2f} ms | p95 {np.percentile(ts, 95):6.2f} ms"
              f" | {b / med * 1e3:6.1f} img/s")
    print(f"    NVRTC termuat: {nvrtc_termuat()} | torch di proses: "
          f"{'YA' if 'torch' in sys.modules else 'TIDAK'}")


def nvrtc_termuat():
    if os.name != "nt":
        return "n/a"
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetModuleHandleW.restype = ctypes.c_void_p
    k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    ada = [n for n in ("nvrtc64_120_0.dll", "nvrtc64_120_0.alt.dll") if k32.GetModuleHandleW(n)]
    return f"YA {ada}" if ada else "TIDAK"


def parent(onnx_path):
    for mode in MODES:
        p = subprocess.run([sys.executable, __file__, "--child", mode, onnx_path],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        spam = 0
        for line in p.stdout.splitlines():
            if "nvrtc64" in line and "Could not locate" in line:
                spam += 1
                continue
            print(line)
        if spam:
            print(f"    (warning 'Could not locate nvrtc' disembunyikan: {spam} baris)")
        if p.returncode != 0:
            print(f"    !! proses mode {mode} keluar dengan kode {p.returncode}")


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--child":
        child(sys.argv[2], sys.argv[3])
    else:
        parent(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ONNX)
