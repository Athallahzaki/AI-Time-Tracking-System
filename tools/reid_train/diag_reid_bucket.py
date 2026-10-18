"""Verifikasi solusi stall ganti-shape OSNet: SATU SESSION PER BUCKET batch.

Hipotesis: CUDA EP (cuDNN) hanya menyimpan plan conv untuk shape terakhir per
session, jadi tiap pergantian batch size = replan ~350 ms. Kalau tiap session
hanya pernah melihat satu shape, replan tidak pernah terjadi.

Membandingkan, pada urutan jumlah crop acak yang sama (meniru jumlah orang per frame):
  1. satu session, batch = jumlah crop apa adanya   (kondisi engine sekarang)
  2. session per bucket {1,2,4,8}, crop di-padding ke bucket terdekat

Jalankan (TANPA torch di proses ini):
    python tools/reid_train/diag_reid_bucket.py [path onnx]
"""
import os
import sys
import tempfile
import time

# Spam "Could not locate nvrtc" ditulis cuDNN (kode C) langsung ke fd 2.
# fd 2 dialihkan ke file log; sys.stderr Python tetap ke konsol, jadi traceback
# dan warning Python tetap terlihat.
_LOG = os.path.join(tempfile.gettempdir(), "diag_reid_bucket_stderr.log")
_konsol = os.dup(2)
_fd_log = os.open(_LOG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
os.dup2(_fd_log, 2)
sys.stderr = os.fdopen(_konsol, "w", buffering=1)

import numpy as np
import onnxruntime as ort

if hasattr(ort, "preload_dlls"):
    ort.preload_dlls()

ONNX = sys.argv[1] if len(sys.argv) > 1 else (
    r"D:\Hobby\Coding\Forgor\AI-Time-Tracking-System\engine\models\reid\osnet_ain_reid.onnx")
BUCKETS = (1, 2, 4, 8)
WARM_PER_BUCKET = 5
N_FRAME = 200
PROV = [("CUDAExecutionProvider", {"cudnn_conv_algo_search": "HEURISTIC"}),
        "CPUExecutionProvider"]


def buat_sesi():
    s = ort.InferenceSession(ONNX, providers=PROV)
    if s.get_providers()[0] != "CUDAExecutionProvider":
        sys.exit(f"!! CUDA EP tidak aktif (tersedia: {ort.get_available_providers()}). Dibatalkan.")
    return s


class ReidBucket:
    """Satu session per ukuran batch; crop di-padding ke bucket terkecil yang muat,
    dipecah per BUCKETS[-1] kalau lebih banyak."""

    def __init__(self):
        self.sesi = {}
        for b in BUCKETS:
            s = buat_sesi()
            nama = s.get_inputs()[0].name
            x = np.zeros((b, 3, 256, 128), np.float32)
            for _ in range(WARM_PER_BUCKET):
                s.run(None, {nama: x})
            self.sesi[b] = (s, nama)

    def __call__(self, crops):
        hasil = []
        maks = BUCKETS[-1]
        for i in range(0, len(crops), maks):
            potong = crops[i:i + maks]
            n = len(potong)
            b = next(k for k in BUCKETS if k >= n)
            if b > n:
                pad = np.zeros((b - n,) + potong.shape[1:], potong.dtype)
                potong = np.concatenate([potong, pad])
            s, nama = self.sesi[b]
            hasil.append(s.run(None, {nama: potong})[0][:n])
        return np.concatenate(hasil)


def ringkas(label, ts):
    ts = np.asarray(ts)
    print(f"  {label:34s} median {np.median(ts):7.2f} | p95 {np.percentile(ts, 95):7.2f} | "
          f"maks {ts.max():8.1f} | >100 ms: {(ts > 100).sum():3d}/{len(ts)}  (ms/frame)")


rng = np.random.default_rng(0)
jumlah = rng.integers(1, 11, N_FRAME)          # 1..10 orang per frame, berubah tiap frame
pool = rng.standard_normal((16, 3, 256, 128)).astype(np.float32)

print(f"onnxruntime {ort.__version__} | torch di proses ini: "
      f"{'YA (BAHAYA)' if 'torch' in sys.modules else 'TIDAK'}")
print(f"{N_FRAME} frame, jumlah crop per frame acak 1..10\n")

# 1) satu session, shape mengikuti jumlah crop
s = buat_sesi()
nama = s.get_inputs()[0].name
s.run(None, {nama: pool[:1]})
t1 = []
for n in jumlah:
    t = time.perf_counter()
    ref = s.run(None, {nama: pool[:n]})[0]
    t1.append((time.perf_counter() - t) * 1e3)

# 2) session per bucket
t = time.perf_counter()
reid = ReidBucket()
print(f"siapkan {len(BUCKETS)} session + warmup: {(time.perf_counter() - t) * 1e3:.0f} ms")
t2 = []
for n in jumlah:
    t = time.perf_counter()
    reid(pool[:n])
    t2.append((time.perf_counter() - t) * 1e3)

# kebenaran: padding tidak boleh mengubah embedding crop asli
for n in (1, 3, 5, 10):
    a = s.run(None, {nama: pool[:n]})[0]
    b = reid(pool[:n])
    print(f"  cek n={n:2d}: selisih maks embedding {np.abs(a - b).max():.2e}")

print()
ringkas("1 session, shape ikut jumlah", t1)
ringkas("session per bucket + padding", t2)

os.close(_fd_log)
with open(_LOG, encoding="utf-8", errors="replace") as f:
    isi = f.read()
spam = isi.count("Could not locate nvrtc")
lain = [b for b in isi.splitlines() if b.strip() and "Could not locate nvrtc" not in b]
print(f"\nstderr level C: {spam} baris spam nvrtc (= NVRTC tidak ter-load, bagus), "
      f"{len(lain)} baris lain -> {_LOG}")
for b in lain[:10]:
    print("   ", b[:300])
