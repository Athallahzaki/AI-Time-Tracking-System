"""SCRFD berdimensi dinamis (paket ea-r11, engine/tools/scrfd_dynamic.py).

Model tiruan berpola det_10g (konv per stride -> Transpose -> Reshape, bentuk keluaran
tertulis untuk 640) dibangun dari proto ONNX lalu dijalankan lewat onnxruntime CPU.
Butuh paket `onnx`; dilewati bila tidak ada (env utama tidak memasangnya).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from engine.identity import face_onnx
from engine.identity.face_onnx import ModelConfigMismatch

# --------------------------------------------------------------------------
# SCRFD dinamis (model tiruan, dijalankan lewat onnxruntime)
# --------------------------------------------------------------------------

onnx = pytest.importorskip("onnx")
ort = pytest.importorskip("onnxruntime")
from engine.tools import scrfd_dynamic  # noqa: E402

STRIDES = (8, 16, 32)


def _tensor(name, array, dtype):
    t = onnx.TensorProto()
    t.name = name
    t.data_type = dtype
    t.dims.extend(array.shape)
    t.raw_data = array.tobytes()
    return t


def _value(name, dims):
    v = onnx.ValueInfoProto()
    v.name = name
    v.type.tensor_type.elem_type = onnx.TensorProto.FLOAT
    for d in dims:
        dim = v.type.tensor_type.shape.dim.add()
        if isinstance(d, int):
            dim.dim_value = d
        else:
            dim.dim_param = d
    return v


def _node(op, inputs, outputs, **attrs):
    n = onnx.NodeProto()
    n.op_type = op
    n.name = outputs[0] + "_" + op
    n.input.extend(inputs)
    n.output.extend(outputs)
    for key, value in attrs.items():
        a = n.attribute.add()
        a.name = key
        a.type = onnx.AttributeProto.INTS
        a.ints.extend(value)
    return n


def _scrfd_tiruan(path, reshape="minus1", static_input=False):
    """Pola det_10g: konv per stride -> Transpose -> Reshape -> keluaran tertulis untuk 640."""
    rng = np.random.default_rng(7)
    model = onnx.ModelProto()
    model.ir_version = 8
    opset = model.opset_import.add()
    opset.version = 13
    graph = model.graph
    graph.name = "scrfd_tiruan"
    graph.input.append(_value("input.1", [1, 3, 640, 640] if static_input else [1, 3, "?", "?"]))
    outputs = []
    for kind, channels, k in (("score", 2, 1), ("bbox", 8, 4), ("kps", 20, 10)):
        for s in STRIDES:
            count = (640 // s) ** 2 * 2
            w = rng.standard_normal((channels, 3, s, s)).astype(np.float32) * 0.05
            graph.initializer.append(_tensor(f"w_{kind}{s}", w, onnx.TensorProto.FLOAT))
            if reshape == "minus1":
                shape = np.array([-1, k], np.int64)
            elif reshape == "static":
                shape = np.array([count, k], np.int64)
            else:
                shape = np.array([1, count, -1], np.int64)
            graph.initializer.append(_tensor(f"shape_{kind}{s}", shape, onnx.TensorProto.INT64))
            graph.node.append(_node("Conv", ["input.1", f"w_{kind}{s}"], [f"c_{kind}{s}"],
                                    kernel_shape=[s, s], strides=[s, s]))
            graph.node.append(_node("Transpose", [f"c_{kind}{s}"], [f"t_{kind}{s}"], perm=[0, 2, 3, 1]))
            graph.node.append(_node("Reshape", [f"t_{kind}{s}", f"shape_{kind}{s}"], [f"{kind}_{s}"]))
            graph.value_info.append(_value(f"c_{kind}{s}", [1, channels, 640 // s, 640 // s]))
            outputs.append(_value(f"{kind}_{s}", [count, k] if reshape != "bad" else [1, count, k]))
    graph.output.extend(outputs)
    onnx.save(model, str(path))
    return path


def test_scrfd_tiruan_dibuat_dinamis_dan_sama_di_640(tmp_path):
    source = _scrfd_tiruan(tmp_path / "scrfd.onnx")
    target = tmp_path / "scrfd_dinamis.onnx"
    assert scrfd_dynamic.main(["--input", str(source), "--output", str(target), "--cek-ukuran", "320,480"]) == 0
    model = onnx.load(str(target))
    assert not model.graph.value_info
    assert model.graph.output[0].type.tensor_type.shape.dim[0].dim_param
    session = ort.InferenceSession(str(target), providers=["CPUExecutionProvider"])
    out = session.run(None, {"input.1": np.zeros((1, 3, 320, 320), np.float32)})
    assert [o.shape[0] for o in out[:3]] == [3200, 800, 200]


def test_scrfd_dinamis_lolos_pemeriksaan_engine(tmp_path):
    """face_onnx._check_static_size menolak model asli di 320 tetapi menerima hasil konversi."""
    source = _scrfd_tiruan(tmp_path / "scrfd.onnx")
    target = tmp_path / "scrfd_dinamis.onnx"
    assert scrfd_dynamic.main(["--input", str(source), "--output", str(target), "--cek-ukuran", "320"]) == 0
    old = ort.InferenceSession(str(source), providers=["CPUExecutionProvider"]).get_outputs()
    new = ort.InferenceSession(str(target), providers=["CPUExecutionProvider"]).get_outputs()
    with pytest.raises(ModelConfigMismatch):
        face_onnx._check_static_size("scrfd.onnx", old, 320, STRIDES, 2)
    face_onnx._check_static_size("scrfd_dinamis.onnx", new, 320, STRIDES, 2)


def test_reshape_dengan_jumlah_anchor_tertulis_diganti_minus_1(tmp_path):
    source = _scrfd_tiruan(tmp_path / "scrfd.onnx", reshape="static", static_input=True)
    model = onnx.load(str(source))
    info = scrfd_dynamic.convert(model)
    assert info.input_was_static and len(info.reshapes_fixed) == 9
    target = tmp_path / "hasil.onnx"
    onnx.save(model, str(target))
    lines = scrfd_dynamic.verify(str(source), str(target), [320])
    assert lines[0].startswith("OK 640") and lines[1].startswith("OK 320")


def test_reshape_yang_tidak_aman_ditolak_tanpa_menulis(tmp_path):
    source = _scrfd_tiruan(tmp_path / "scrfd.onnx", reshape="bad")
    target = tmp_path / "hasil.onnx"
    assert scrfd_dynamic.main(["--input", str(source), "--output", str(target)]) == 1
    assert not target.exists() and not Path(str(target) + ".sementara").exists()


def test_output_sama_dengan_input_ditolak(tmp_path):
    source = _scrfd_tiruan(tmp_path / "scrfd.onnx")
    assert scrfd_dynamic.main(["--input", str(source), "--output", str(source)]) == 2
