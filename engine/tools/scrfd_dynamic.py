"""SCRFD berbentuk tetap 640 -> berdimensi dinamis, tanpa ekspor ulang dari PyTorch (ea-r11).

`scrfd_10g_bnkps.onnx` tim menuliskan bentuk keluaran tetap untuk 640 ([12800, 1],
[3200, 1], [800, 1], ...). Dengan input 480, onnxruntime tetap jalan tetapi
memeriksa bentuk itu di setiap run (peringatan VerifyOutputSizes) dan rekognisi
jadi 10x lebih lambat (uji 4060, 15 Okt; engine sekarang menolaknya, ea-r9).

Alat ini:

1. mengganti dimensi tinggi/lebar input dan jumlah anchor keluaran menjadi simbolik;
2. membuang `value_info` (bentuk antara yang ikut tertulis untuk 640);
3. memeriksa konstanta Reshape: jumlah anchor yang ditulis mati (mis. 12800) diganti
   -1 bila aman; bila tidak aman, alat berhenti dan TIDAK menulis model;
4. memverifikasi dengan onnxruntime: keluaran model baru di 640 harus sama dengan
   model asli, dan di setiap `--cek-ukuran` jumlah anchor harus (ukuran/stride)^2 x 2.

    python -m engine.tools.scrfd_dynamic --input engine/models/recognition/scrfd_10g_bnkps.onnx --output engine/models/recognition/scrfd_10g_bnkps_dinamis.onnx

Butuh paket `onnx` (scripts/setup-env-trt.ps1 memasangnya) dan onnxruntime. Model
asli tidak diubah. Model baru TIDAK di-commit (*.onnx di-ignore).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

STRIDES = (8, 16, 32)
NUM_ANCHORS = 2
REFERENCE_SIZE = 640
MAX_ABS_DIFF = 1e-4


class ConversionRefused(RuntimeError):
    """Model tidak bisa dibuat dinamis dengan aman; tidak ada berkas yang ditulis."""


@dataclass
class Conversion:
    input_name: str
    input_was_static: bool
    outputs_changed: int
    value_info_removed: int
    reshapes_fixed: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def _anchor_counts(size: int) -> List[int]:
    return [(size // s) ** 2 * NUM_ANCHORS for s in STRIDES]


def _set_symbolic(dim: Any, name: str) -> None:
    dim.Clear()
    dim.dim_param = name


def _initializer_map(graph: Any) -> Dict[str, Any]:
    return {init.name: init for init in graph.initializer}


def _constant_nodes(graph: Any) -> Dict[str, Any]:
    out = {}
    for node in graph.node:
        if node.op_type == "Constant" and node.output:
            for attr in node.attribute:
                if attr.name == "value":
                    out[node.output[0]] = attr.t
    return out


def _int_values(tensor: Any) -> Optional[np.ndarray]:
    """Isi tensor INT64/INT32 (raw_data atau int64_data/int32_data)."""
    import onnx

    if tensor.data_type == onnx.TensorProto.INT64:
        if tensor.raw_data:
            return np.frombuffer(tensor.raw_data, dtype="<i8").copy()
        return np.array(list(tensor.int64_data), dtype=np.int64)
    if tensor.data_type == onnx.TensorProto.INT32:
        if tensor.raw_data:
            return np.frombuffer(tensor.raw_data, dtype="<i4").astype(np.int64)
        return np.array(list(tensor.int32_data), dtype=np.int64)
    return None


def _write_int_values(tensor: Any, values: np.ndarray) -> None:
    import onnx

    if tensor.data_type == onnx.TensorProto.INT64:
        dtype = "<i8"
    else:
        dtype = "<i4"
    del tensor.int64_data[:]
    del tensor.int32_data[:]
    tensor.raw_data = np.asarray(values).astype(dtype).tobytes()


def _fix_reshapes(graph: Any, size_dependent: Sequence[int]) -> List[str]:
    """Konstanta Reshape yang memuat jumlah anchor 640 -> -1, bila hanya satu dan belum ada -1."""
    initializers = _initializer_map(graph)
    constants = _constant_nodes(graph)
    suspicious = set(int(v) for v in size_dependent)
    fixed: List[str] = []
    for node in graph.node:
        if node.op_type != "Reshape" or len(node.input) < 2:
            continue
        tensor = initializers.get(node.input[1]) or constants.get(node.input[1])
        if tensor is None:
            continue  # bentuk dihitung dari graf (Shape/Concat): sudah dinamis
        values = _int_values(tensor)
        if values is None:
            continue
        hits = [i for i, v in enumerate(values) if int(v) in suspicious]
        if not hits:
            continue
        if len(hits) > 1 or (values == -1).any():
            raise ConversionRefused(
                f"Reshape {node.name or node.output[0]} memakai bentuk {values.tolist()} yang bergantung "
                f"pada ukuran {REFERENCE_SIZE} dan tidak bisa diganti -1 dengan aman. Ekspor ulang SCRFD "
                "dari sumber dengan dynamic_axes.")
        before = values.tolist()
        values = values.copy()
        values[hits[0]] = -1
        _write_int_values(tensor, values)
        fixed.append(f"{node.name or node.output[0]}: {before} -> {values.tolist()}")
    return fixed


def _check_sizes_resize(graph: Any) -> List[str]:
    """Resize dengan `sizes` konstan mengunci ukuran peta fitur -> tolak."""
    initializers = _initializer_map(graph)
    constants = _constant_nodes(graph)
    problems = []
    for node in graph.node:
        if node.op_type == "Resize" and len(node.input) >= 4 and node.input[3]:
            if node.input[3] in initializers or node.input[3] in constants:
                problems.append(node.name or node.output[0])
    return problems


def convert(model: Any) -> Conversion:
    """Ubah `model` (ModelProto) di tempat. ConversionRefused bila tidak aman."""
    graph = model.graph
    initializer_names = {init.name for init in graph.initializer}
    inputs = [i for i in graph.input if i.name not in initializer_names]
    if len(inputs) != 1:
        raise ConversionRefused(f"SCRFD diharapkan 1 input, dapat {len(inputs)}")
    if len(graph.output) != 9:
        raise ConversionRefused(f"SCRFD dengan keypoint diharapkan 9 keluaran, dapat {len(graph.output)}")
    dims = inputs[0].type.tensor_type.shape.dim
    if len(dims) != 4:
        raise ConversionRefused(f"input SCRFD diharapkan 4 dimensi (NCHW), dapat {len(dims)}")
    resize = _check_sizes_resize(graph)
    if resize:
        raise ConversionRefused(f"Resize dengan sizes konstan ({', '.join(resize)}): ukuran peta fitur terkunci")
    was_static = all(d.HasField("dim_value") for d in dims[2:])
    _set_symbolic(dims[2], "tinggi")
    _set_symbolic(dims[3], "lebar")

    changed = 0
    for index, output in enumerate(graph.output):
        out_dims = output.type.tensor_type.shape.dim
        if not out_dims:
            continue
        # [N, k] atau [1, N, k]: dimensi jumlah anchor = dimensi kedua dari belakang.
        anchor_dim = out_dims[len(out_dims) - 2] if len(out_dims) >= 2 else out_dims[0]
        _set_symbolic(anchor_dim, f"anchor_{index}")
        changed += 1
    removed = len(graph.value_info)
    del graph.value_info[:]
    fixed = _fix_reshapes(graph, _anchor_counts(REFERENCE_SIZE))
    notes = []
    if not was_static:
        notes.append("input sudah dinamis; yang terkunci hanya bentuk keluaran tertulis")
    return Conversion(input_name=inputs[0].name, input_was_static=was_static, outputs_changed=changed,
                      value_info_removed=removed, reshapes_fixed=fixed, notes=notes)


# --------------------------------------------------------------------------
# verifikasi dengan onnxruntime
# --------------------------------------------------------------------------

def _pattern(size: int) -> np.ndarray:
    """Input deterministik yang tidak rata (bukan nol), supaya selisih kelihatan."""
    rng = np.random.default_rng(1234 + size)
    return rng.uniform(-1.0, 1.0, size=(1, 3, size, size)).astype(np.float32)


def _session(path: str, providers: Optional[Sequence[str]]):
    import onnxruntime as ort

    return ort.InferenceSession(path, providers=list(providers or ["CPUExecutionProvider"]))


def verify(original: str, converted: str, sizes: Sequence[int],
           providers: Optional[Sequence[str]] = None) -> List[str]:
    """Baris laporan; ConversionRefused bila hasilnya salah."""
    old = _session(original, providers)
    new = _session(converted, providers)
    name_old = old.get_inputs()[0].name
    name_new = new.get_inputs()[0].name
    lines = []
    blob = _pattern(REFERENCE_SIZE)
    out_old = old.run(None, {name_old: blob})
    out_new = new.run(None, {name_new: blob})
    worst = max(float(np.max(np.abs(a - b))) if a.size else 0.0 for a, b in zip(out_old, out_new))
    if worst > MAX_ABS_DIFF:
        raise ConversionRefused(f"keluaran {REFERENCE_SIZE} berbeda dari model asli (selisih maks {worst:.2e})")
    lines.append(f"OK {REFERENCE_SIZE}: keluaran sama dengan model asli (selisih maks {worst:.1e})")
    for size in sizes:
        if size % 32:
            raise ConversionRefused(f"ukuran {size} bukan kelipatan 32")
        outputs = new.run(None, {name_new: _pattern(size)})
        expected = _anchor_counts(size)
        got = [int(np.prod(o.shape)) // max(1, int(o.shape[-1])) for o in outputs[: len(STRIDES)]]
        if got != expected:
            raise ConversionRefused(f"ukuran {size}: jumlah anchor {got}, seharusnya {expected}")
        lines.append(f"OK {size}: jumlah anchor {got}")
    return lines


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="SCRFD asli (tidak diubah)")
    parser.add_argument("--output", required=True, help="SCRFD berdimensi dinamis yang ditulis")
    parser.add_argument("--cek-ukuran", default="320,480,640", help="ukuran yang diverifikasi, dipisah koma")
    parser.add_argument("--providers", default="CPUExecutionProvider",
                        help="provider onnxruntime untuk verifikasi (CPU cukup dan paling teliti)")
    args = parser.parse_args(argv)

    try:
        import onnx
    except ImportError:
        print("butuh paket onnx: pip install onnx (scripts/setup-env-trt.ps1 sudah memasangnya)", file=sys.stderr)
        return 2
    source, target = Path(args.input), Path(args.output)
    if source.resolve() == target.resolve():
        print("--output tidak boleh sama dengan --input; model asli dipakai sebagai pembanding", file=sys.stderr)
        return 2
    model = onnx.load(str(source))
    try:
        info = convert(model)
    except ConversionRefused as error:
        print(f"DITOLAK: {error}", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".sementara")
    onnx.save(model, str(temporary))
    sizes = [int(s) for s in args.cek_ukuran.split(",") if s.strip()]
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    try:
        lines = verify(str(source), str(temporary), sizes, providers)
    except ConversionRefused as error:
        temporary.unlink(missing_ok=True)
        print(f"DITOLAK saat verifikasi: {error}", file=sys.stderr)
        return 1
    temporary.replace(target)
    print(f"input {info.input_name}: {'tetap' if info.input_was_static else 'sudah dinamis'} -> tinggi x lebar; "
          f"{info.outputs_changed} keluaran simbolik; {info.value_info_removed} value_info dibuang")
    for line in info.reshapes_fixed:
        print(f"Reshape diperbaiki: {line}")
    for line in info.notes + lines:
        print(line)
    print(f"ditulis: {target}")
    print("Berikutnya: python -m engine.tools.face_bench ... --ukuran 640,320 --model-detektor " + str(target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
