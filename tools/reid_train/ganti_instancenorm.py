"""Ganti InstanceNormalization di ONNX (OSNet-AIN) dengan operasi dasar yang setara.

Alasan (uji 17 Okt, RTX 4060, onnxruntime-gpu 1.26 + cuDNN 9.10 dari torch): OSNet-AIN di
onnxruntime CUDA butuh +-260 ms pada batch 1-3 dan +-9.500 ms pada batch >= 4, sedangkan
checkpoint yang sama di PyTorch GPU +-32 ms di semua batch. Semua node sudah di CUDA EP,
bukan pencarian algoritma (EXHAUSTIVE = HEURISTIC), bukan optimasi graf. Dugaan: kernel
InstanceNormalization CUDA. Alat ini HANYA dipakai bila profil (`diag_reid_profile.py`)
membuktikannya.

    y = scale * (x - mean) / sqrt(var + eps) + bias,   mean/var per (n, c) atas sumbu spasial

ditulis sebagai ReduceMean, Sub, Mul, ReduceMean, Add, Sqrt, Div, Reshape, Mul, Add.
Mul(d, d), bukan Pow: pola Pow adalah yang dicari LayerNormFusion onnxruntime.

Berkas keluaran HANYA ditulis bila keluarannya sama dengan model asli (onnxruntime CPU,
batch 1 dan 4): kosinus per baris >= 0,9999 dan selisih maks <= 1e-3 x skala. SHA-256 baru
dicetak; isi `reid.model_sha256` dengan nilai itu.

Butuh `onnx` dan `onnxruntime` (env latihan `reid-env` sudah punya keduanya):
    python ganti_instancenorm.py --input osnet_reid.onnx --output osnet_reid_tanpa_in.onnx
    python ganti_instancenorm.py ... --ukur-cuda     # bandingkan kecepatan bila CUDA EP ada
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

TOLERANSI_KOSINUS = 0.9999
TOLERANSI_RELATIF = 1e-3


def _opset(model) -> int:
    for item in model.opset_import:
        if item.domain in ("", "ai.onnx"):
            return int(item.version)
    return 0


def _peringkat(model) -> Dict[str, int]:
    """Rank tensor dari shape inference; kosong bila gagal (dianggap 4D)."""
    import onnx
    try:
        hasil = onnx.shape_inference.infer_shapes(model)
    except Exception:  # noqa: BLE001
        return {}
    ranks: Dict[str, int] = {}
    for vi in list(hasil.graph.value_info) + list(hasil.graph.input) + list(hasil.graph.output):
        tipe = vi.type.tensor_type
        if tipe.HasField("shape"):
            ranks[vi.name] = len(tipe.shape.dim)
    return ranks


def ganti(model) -> int:
    """Ubah `model` di tempat. Kembalikan jumlah node InstanceNormalization yang diganti."""
    from onnx import helper, numpy_helper

    opset = _opset(model)
    if opset < 13:
        raise ValueError(f"opset {opset} < 13 tidak didukung (Reshape/ReduceMean lama)")
    ranks = _peringkat(model)
    graf = model.graph
    baru: List = []
    tambahan: List = []
    jumlah = 0
    for indeks, node in enumerate(graf.node):
        if node.op_type != "InstanceNormalization" or node.domain not in ("", "ai.onnx"):
            baru.append(node)
            continue
        x, skala, geser = node.input[0], node.input[1], node.input[2]
        y = node.output[0]
        eps = 1e-5
        for atribut in node.attribute:
            if atribut.name == "epsilon":
                eps = float(atribut.f)
        rank = ranks.get(x, 4)
        if rank < 3:
            raise ValueError(f"InstanceNormalization {node.name!r}: rank masukan {rank} < 3")
        sumbu = list(range(2, rank))
        p = f"_ganti_in{indeks}_"
        tambahan.append(numpy_helper.from_array(np.array([1, -1] + [1] * (rank - 2), dtype=np.int64), p + "bentuk"))
        tambahan.append(numpy_helper.from_array(np.array(eps, dtype=np.float32), p + "eps"))
        if opset >= 18:
            tambahan.append(numpy_helper.from_array(np.array(sumbu, dtype=np.int64), p + "sumbu"))

        def rata(masuk: str, keluar: str, nama: str):
            if opset >= 18:
                return helper.make_node("ReduceMean", [masuk, p + "sumbu"], [keluar], name=nama, keepdims=1)
            return helper.make_node("ReduceMean", [masuk], [keluar], name=nama, axes=sumbu, keepdims=1)

        baru += [
            rata(x, p + "mean", p + "rata1"),
            helper.make_node("Sub", [x, p + "mean"], [p + "d"], name=p + "kurang"),
            helper.make_node("Mul", [p + "d", p + "d"], [p + "d2"], name=p + "kuadrat"),
            rata(p + "d2", p + "var", p + "rata2"),
            helper.make_node("Add", [p + "var", p + "eps"], [p + "ve"], name=p + "tambah_eps"),
            helper.make_node("Sqrt", [p + "ve"], [p + "std"], name=p + "akar"),
            helper.make_node("Div", [p + "d", p + "std"], [p + "norm"], name=p + "bagi"),
            helper.make_node("Reshape", [skala, p + "bentuk"], [p + "s"], name=p + "bentuk_skala"),
            helper.make_node("Reshape", [geser, p + "bentuk"], [p + "b"], name=p + "bentuk_geser"),
            helper.make_node("Mul", [p + "norm", p + "s"], [p + "ns"], name=p + "kali"),
            helper.make_node("Add", [p + "ns", p + "b"], [y], name=p + "tambah"),
        ]
        jumlah += 1
    del graf.node[:]
    graf.node.extend(baru)
    graf.initializer.extend(tambahan)
    return jumlah


def _masukan(sesi, batch: int, tinggi: int, lebar: int) -> Tuple[str, np.ndarray]:
    info = sesi.get_inputs()[0]
    dims = list(info.shape)
    bentuk = [batch] + [d if isinstance(d, int) and d > 0 else None for d in dims[1:]]
    if len(bentuk) == 4:
        bentuk[2] = bentuk[2] or tinggi
        bentuk[3] = bentuk[3] or lebar
    if any(d is None for d in bentuk):
        raise ValueError(f"bentuk masukan {dims} tidak bisa ditentukan; isi --tinggi/--lebar")
    rng = np.random.default_rng(batch)
    return info.name, rng.standard_normal(bentuk).astype(np.float32)


def bandingkan(asli: bytes, hasil: bytes, tinggi: int, lebar: int) -> List[str]:
    """Kosong bila setara; selain itu daftar alasan."""
    import onnxruntime as ort

    s1 = ort.InferenceSession(asli, providers=["CPUExecutionProvider"])
    s2 = ort.InferenceSession(hasil, providers=["CPUExecutionProvider"])
    masalah: List[str] = []
    for batch in (1, 4):
        nama, x = _masukan(s1, batch, tinggi, lebar)
        a = np.asarray(s1.run(None, {nama: x})[0], dtype=np.float64).reshape(batch, -1)
        b = np.asarray(s2.run(None, {nama: x})[0], dtype=np.float64).reshape(batch, -1)
        skala = max(1.0, float(np.abs(a).max()))
        beda = float(np.abs(a - b).max())
        kos = float(np.min(np.sum(a * b, 1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1) + 1e-12)))
        print(f"  batch {batch}: selisih maks {beda:.2e} (skala {skala:.2f}), kosinus min {kos:.6f}")
        if beda > TOLERANSI_RELATIF * skala:
            masalah.append(f"batch {batch}: selisih {beda:.2e} > {TOLERANSI_RELATIF * skala:.2e}")
        if kos < TOLERANSI_KOSINUS:
            masalah.append(f"batch {batch}: kosinus {kos:.6f} < {TOLERANSI_KOSINUS}")
    return masalah


def ukur_cuda(berkas: Dict[str, bytes], tinggi: int, lebar: int) -> None:
    import onnxruntime as ort

    if hasattr(ort, "preload_dlls"):
        try:
            ort.preload_dlls()
        except Exception:  # noqa: BLE001
            pass
    if "CUDAExecutionProvider" not in ort.get_available_providers():
        print("CUDA EP tidak tersedia di onnxruntime ini: --ukur-cuda dilewati (pakai env vision-engine).")
        return
    for label, isi in berkas.items():
        sesi = ort.InferenceSession(isi, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
        baris = []
        for batch in (1, 4, 8):
            nama, x = _masukan(sesi, batch, tinggi, lebar)
            sesi.run(None, {nama: x})
            mulai = time.perf_counter()
            for _ in range(3):
                sesi.run(None, {nama: x})
            baris.append(f"b{batch} {1000 * (time.perf_counter() - mulai) / 3:8.1f} ms")
        print(f"  {label:10s} " + "  ".join(baris) + f"  | aktif {sesi.get_providers()[0]}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--input", required=True, help="ONNX asli (tidak diubah)")
    ap.add_argument("--output", required=True, help="ONNX tanpa InstanceNormalization")
    ap.add_argument("--tinggi", type=int, default=256)
    ap.add_argument("--lebar", type=int, default=128)
    ap.add_argument("--ukur-cuda", action="store_true", help="bandingkan kecepatan asli vs hasil di CUDA EP")
    a = ap.parse_args(argv)

    import onnx

    asli_bytes = Path(a.input).read_bytes()
    model = onnx.load_from_string(asli_bytes)
    jumlah = ganti(model)
    if jumlah == 0:
        print("Tidak ada InstanceNormalization di model ini; tidak ada yang ditulis.")
        return 0
    onnx.checker.check_model(model)
    hasil_bytes = model.SerializeToString()
    print(f"{jumlah} node InstanceNormalization diganti (opset {_opset(model)}). Verifikasi (CPU):")
    masalah = bandingkan(asli_bytes, hasil_bytes, a.tinggi, a.lebar)
    if masalah:
        print("DITOLAK, berkas tidak ditulis: " + "; ".join(masalah), file=sys.stderr)
        return 1
    keluar = Path(a.output)
    keluar.parent.mkdir(parents=True, exist_ok=True)
    fd, sementara = tempfile.mkstemp(dir=str(keluar.parent), suffix=".onnx")
    with os.fdopen(fd, "wb") as f:
        f.write(hasil_bytes)
    os.replace(sementara, keluar)
    print(f"Ditulis: {keluar}\nSHA-256: {hashlib.sha256(hasil_bytes).hexdigest()}  (isi reid.model_sha256)")
    if a.ukur_cuda:
        print("Kecepatan CUDA EP (rata-rata 3 run setelah 1 pemanasan):")
        ukur_cuda({"asli": asli_bytes, "tanpa IN": hasil_bytes}, a.tinggi, a.lebar)
    return 0


if __name__ == "__main__":
    sys.exit(main())
