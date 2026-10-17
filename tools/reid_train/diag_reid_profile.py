"""Profil waktu per OPERASI OSNet di ONNX Runtime (env vision-engine). Jalankan:
    python X:\\data\\diag_reid_profile.py [path onnx]
Menunjukkan jenis operasi mana yang memakan waktu pada batch 1 dan batch 4."""
import collections
import json
import os
import sys
import tempfile

import numpy as np
import onnxruntime as ort

ONNX = sys.argv[1] if len(sys.argv) > 1 else r"X:\Projek\AI-Time-Tracking-System\engine\models\reid\osnet_reid.onnx"
if hasattr(ort, "preload_dlls"):
    ort.preload_dlls()

for batch in (1, 4):
    so = ort.SessionOptions()
    so.enable_profiling = True
    so.profile_file_prefix = os.path.join(tempfile.gettempdir(), f"osnet_b{batch}")
    s = ort.InferenceSession(ONNX, so, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    nama = s.get_inputs()[0].name
    x = np.random.default_rng(0).standard_normal((batch, 3, 256, 128)).astype(np.float32)
    for _ in range(3):
        s.run(None, {nama: x})
    berkas = s.end_profiling()
    data = json.load(open(berkas, encoding="utf-8"))
    per_op = collections.defaultdict(float)
    per_node = collections.defaultdict(float)
    for ev in data:
        if ev.get("cat") != "Node" or not ev.get("name", "").endswith("_kernel_time"):
            continue
        op = ev.get("args", {}).get("op_name", "?")
        per_op[op] += ev["dur"] / 3000.0          # mikrodetik -> ms, rata-rata per run
        per_node[(op, ev["name"][:-12])] += ev["dur"] / 3000.0
    total = sum(per_op.values())
    print(f"\n== batch {batch}: total kernel {total:.1f} ms per run (profil: {berkas})")
    for op, ms in sorted(per_op.items(), key=lambda kv: -kv[1])[:10]:
        print(f"   {op:28s} {ms:9.1f} ms  ({100 * ms / max(total, 1e-9):5.1f}%)")
    print("   node termahal:")
    for (op, node), ms in sorted(per_node.items(), key=lambda kv: -kv[1])[:5]:
        print(f"     {ms:9.1f} ms  {op}  {node}")
    del s
