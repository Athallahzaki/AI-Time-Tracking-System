"""Embedder ReID ONNX (paket ea-r3): pra-proses identik latihan, L2, SHA-256,
penolakan start, dan model ONNX mini ujung ke ujung (dilewati tanpa `onnx`)."""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from engine.config import load_config
from engine.config.schema import ReidSettings
from engine.identity import face_onnx
from engine.identity.reid import embedder_onnx
from engine.identity.reid.embedder_onnx import (
    ReidModelUnavailable,
    build_reid_embedder,
    l2_rows,
    preprocess,
)

ROOT = Path(__file__).resolve().parents[2]


def _reid_common():
    """`tools/reid_train/reid_common.py` = definisi resmi pra-proses latihan."""
    path = ROOT / "tools" / "reid_train" / "reid_common.py"
    spec = importlib.util.spec_from_file_location("reid_common_untuk_tes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _crops():
    rng = np.random.default_rng(3)
    return [
        rng.integers(0, 256, size=(300, 140, 3), dtype=np.uint8),   # mengecil -> INTER_AREA
        rng.integers(0, 256, size=(120, 50, 3), dtype=np.uint8),    # membesar -> INTER_LINEAR
        rng.integers(0, 256, size=(256, 128, 3), dtype=np.uint8),   # ukuran pas
    ]


def test_praproses_identik_dengan_kit_latih():
    common = _reid_common()
    ours = preprocess(_crops())
    theirs = common.muat_batch(_crops())
    assert ours.shape == (3, 3, 256, 128)
    assert ours.dtype == np.float32
    np.testing.assert_array_equal(ours, theirs)


def test_konstanta_praproses_sama_dengan_kit_latih():
    common = _reid_common()
    assert (embedder_onnx.INPUT_HEIGHT, embedder_onnx.INPUT_WIDTH) == (common.TINGGI, common.LEBAR)
    np.testing.assert_array_equal(embedder_onnx.MEAN, common.MEAN)
    np.testing.assert_array_equal(embedder_onnx.STD, common.STD)


def test_l2_per_baris_dan_vektor_nol_ditolak():
    out = l2_rows(np.array([[3.0, 4.0], [0.0, 2.0]]))
    np.testing.assert_allclose(np.linalg.norm(out, axis=1), 1.0, atol=1e-6)
    with pytest.raises(ValueError):
        l2_rows(np.array([[0.0, 0.0]]))


def test_reid_mati_tidak_memuat_apa_pun(monkeypatch):
    def jangan_dipanggil(*args, **kwargs):
        raise AssertionError("embedder dimuat padahal reid.enabled false")

    monkeypatch.setattr(embedder_onnx, "OnnxReidEmbedder", jangan_dipanggil)
    monkeypatch.setattr(face_onnx, "_session", jangan_dipanggil)
    assert build_reid_embedder(ReidSettings()) is None
    for name in ("default_config", "demo-4060", "demo-4060-tick", "demo-1060"):
        config = load_config(f"engine/config/{name}.yaml")
        assert config.reid.enabled is False, name
        assert build_reid_embedder(config.reid) is None


def test_berkas_model_hilang_ditolak(tmp_path):
    settings = ReidSettings(enabled=True, model_path=str(tmp_path / "tidak_ada.onnx"))
    with pytest.raises(ReidModelUnavailable, match="tidak ditemukan"):
        build_reid_embedder(settings)


def test_sha256_salah_ditolak_sebelum_onnxruntime(tmp_path, monkeypatch):
    model = tmp_path / "osnet.onnx"
    model.write_bytes(b"bukan model")
    monkeypatch.setattr(face_onnx, "_session", lambda *a, **k: pytest.fail("sesi dibuat"))
    settings = ReidSettings(enabled=True, model_path=str(model), model_sha256="0" * 64)
    with pytest.raises(ReidModelUnavailable, match="SHA-256"):
        build_reid_embedder(settings)


def test_sha256_benar_tetapi_berkas_rusak_ditolak(tmp_path):
    pytest.importorskip("onnxruntime")
    model = tmp_path / "osnet.onnx"
    model.write_bytes(b"bukan model")
    digest = hashlib.sha256(b"bukan model").hexdigest()
    settings = ReidSettings(enabled=True, model_path=str(model), model_sha256=digest.upper(),
                            onnx_providers=("CPUExecutionProvider",))
    with pytest.raises(ReidModelUnavailable, match="gagal memuat"):
        build_reid_embedder(settings)


def test_cuda_diminta_tapi_jatuh_ke_cpu_ditolak(tmp_path, monkeypatch):
    module = types.ModuleType("onnxruntime")
    module.get_available_providers = lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"]

    class Session:
        def __init__(self, path, providers):
            pass

        def get_providers(self):
            return ["CPUExecutionProvider"]

    module.InferenceSession = Session
    monkeypatch.setitem(sys.modules, "onnxruntime", module)
    monkeypatch.setattr(face_onnx, "_DLLS_PRELOADED", True)
    model = tmp_path / "osnet.onnx"
    model.write_bytes(b"x")
    settings = ReidSettings(enabled=True, model_path=str(model),
                            onnx_providers=("CUDAExecutionProvider", "CPUExecutionProvider"))
    with pytest.raises(ReidModelUnavailable, match="reid.onnx_providers"):
        build_reid_embedder(settings)


def test_engine_menolak_start_bila_model_reid_hilang(tmp_path):
    from engine.runtime import EngineRuntime, RuntimeOptions

    base = dataclasses.replace(load_config(), source_type="mock", auto_warmup=False)
    config = dataclasses.replace(
        base,
        recognition=dataclasses.replace(
            base.recognition, enabled=True, recognizer="onnx_face",
            face_detector_model="det.onnx", face_embedder_model="emb.onnx",
        ),
        reid=ReidSettings(enabled=True, model_path=str(tmp_path / "hilang.onnx")),
    )
    with pytest.raises(ReidModelUnavailable):
        EngineRuntime(config=config, options=RuntimeOptions(tcp=None),
                      recognize=lambda track, frame: None)


# --------------------------------------------------------------------------
# Model ONNX mini: pra-proses + normalisasi L2 ujung ke ujung
# --------------------------------------------------------------------------

def _model_mini(path: Path, weights: np.ndarray, l2_in_graph: bool = False) -> None:
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper, numpy_helper

    nodes = [
        helper.make_node("ReduceMean", ["input"], ["pooled"], axes=[2, 3], keepdims=0),
        helper.make_node("MatMul", ["pooled", "W"], ["raw"]),
    ]
    out_name = "raw"
    if l2_in_graph:
        nodes.append(helper.make_node("LpNormalization", ["raw"], ["embedding"], axis=1, p=2))
        out_name = "embedding"
    graph = helper.make_graph(
        nodes, "osnet_mini",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, ["N", 3, 256, 128])],
        [helper.make_tensor_value_info(out_name, TensorProto.FLOAT, ["N", weights.shape[1]])],
        initializer=[numpy_helper.from_array(weights.astype(np.float32), "W")],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    path.write_bytes(model.SerializeToString())


@pytest.mark.parametrize("l2_in_graph", [False, True])
def test_model_onnx_mini_ujung_ke_ujung(tmp_path, l2_in_graph):
    pytest.importorskip("onnxruntime")
    weights = np.array([[1.0, 0.5, -0.3, 0.2], [0.1, -1.0, 0.4, 0.7], [0.3, 0.2, 1.0, -0.5]])
    model = tmp_path / "osnet_mini.onnx"
    _model_mini(model, weights, l2_in_graph)
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    settings = ReidSettings(enabled=True, model_path=str(model), model_sha256=digest,
                            max_batch=2, onnx_providers=("CPUExecutionProvider",))
    embedder = build_reid_embedder(settings)
    assert embedder.sha256 == digest

    crops = _crops()
    got = embedder.embed(crops)   # 3 crop, batch maks 2 -> dua panggilan
    # Rujukan: pra-proses kit latih + matematika graf yang sama + L2.
    batch = _reid_common().muat_batch(crops)
    expected = batch.mean(axis=(2, 3)) @ weights.astype(np.float32)
    expected /= np.linalg.norm(expected, axis=1, keepdims=True)
    assert got.shape == (3, 4)
    np.testing.assert_allclose(np.linalg.norm(got, axis=1), 1.0, atol=1e-5)
    np.testing.assert_allclose(got, expected, atol=1e-4)
