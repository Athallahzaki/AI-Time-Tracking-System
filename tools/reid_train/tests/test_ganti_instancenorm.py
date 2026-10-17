"""ganti_instancenorm.py: model kecil ber-InstanceNormalization, hasil harus setara (ea-r14).

Dilewati tanpa paket `onnx` (sesi cloud tanpa PyPI); wajib dijalankan di env reid-env.
"""
import numpy as np
import pytest

onnx = pytest.importorskip("onnx")
ort = pytest.importorskip("onnxruntime")

from onnx import TensorProto, helper, numpy_helper  # noqa: E402

import ganti_instancenorm as gi  # noqa: E402


def _model(opset: int):
    rng = np.random.default_rng(opset)
    skala = numpy_helper.from_array(rng.uniform(0.5, 1.5, 4).astype(np.float32), "skala")
    geser = numpy_helper.from_array(rng.normal(0, 0.3, 4).astype(np.float32), "geser")
    node = [
        helper.make_node("InstanceNormalization", ["x", "skala", "geser"], ["n"], epsilon=1e-5, name="in0"),
        helper.make_node("Relu", ["n"], ["y"], name="relu"),
    ]
    graf = helper.make_graph(
        node, "kecil",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, ["N", 4, 8, 6])],
        [helper.make_tensor_value_info("y", TensorProto.FLOAT, ["N", 4, 8, 6])],
        initializer=[skala, geser],
    )
    return helper.make_model(graf, opset_imports=[helper.make_opsetid("", opset)])


@pytest.mark.parametrize("opset", [17, 18])
def test_hasil_setara_dan_tanpa_instancenorm(opset):
    asli = _model(opset)
    asli_bytes = asli.SerializeToString()
    baru = onnx.load_from_string(asli_bytes)
    assert gi.ganti(baru) == 1
    onnx.checker.check_model(baru)
    assert not any(n.op_type == "InstanceNormalization" for n in baru.graph.node)
    assert gi.bandingkan(asli_bytes, baru.SerializeToString(), 8, 6) == []


def test_main_menulis_berkas_dan_sha(tmp_path):
    masuk, keluar = tmp_path / "a.onnx", tmp_path / "b.onnx"
    masuk.write_bytes(_model(17).SerializeToString())
    assert gi.main(["--input", str(masuk), "--output", str(keluar), "--tinggi", "8", "--lebar", "6"]) == 0
    assert keluar.is_file()
