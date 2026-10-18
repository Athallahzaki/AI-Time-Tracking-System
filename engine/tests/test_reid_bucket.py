"""Runner bucket ReID (paket eb-r12): satu session per ukuran batch, padding nol,
hasil identik dengan satu session tanpa padding. Model ONNX sintetis kecil
(Conv -> InstanceNormalization -> Relu -> GlobalAveragePool -> Flatten) di CPU EP;
dilewati tanpa `onnx`. Uji GPU/model asli dilewati bila CUDA EP atau model tidak ada."""

from __future__ import annotations

import hashlib
import logging
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from engine.config import load_config
from engine.config.schema import ReidSettings
from engine.identity.reid import embedder_onnx
from engine.identity.reid.embedder_onnx import (
    ReidBucketRunner,
    build_reid_embedder,
    l2_rows,
    preprocess,
    with_cuda_options,
)

ROOT = Path(__file__).resolve().parents[2]
MODEL_ASLI = ROOT / "engine" / "models" / "reid" / "osnet_ain_reid.onnx"
DIM = 4


def _model_sintetis(path: Path) -> None:
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper, numpy_helper

    rng = np.random.default_rng(7)
    w = rng.standard_normal((DIM, 3, 3, 3)).astype(np.float32) * 0.3
    b = rng.standard_normal(DIM).astype(np.float32) * 0.1
    scale = (1.0 + 0.2 * rng.standard_normal(DIM)).astype(np.float32)
    bias = (0.1 * rng.standard_normal(DIM)).astype(np.float32)
    graph = helper.make_graph(
        [
            helper.make_node("Conv", ["input", "W", "B"], ["conv"], pads=[1, 1, 1, 1]),
            helper.make_node("InstanceNormalization", ["conv", "S", "Bn"], ["norm"], epsilon=1e-5),
            helper.make_node("Relu", ["norm"], ["relu"]),
            helper.make_node("GlobalAveragePool", ["relu"], ["pool"]),
            helper.make_node("Flatten", ["pool"], ["embedding"], axis=1),
        ],
        "osnet_sintetis",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, ["N", 3, 256, 128])],
        [helper.make_tensor_value_info("embedding", TensorProto.FLOAT, ["N", DIM])],
        initializer=[numpy_helper.from_array(w, "W"), numpy_helper.from_array(b, "B"),
                     numpy_helper.from_array(scale, "S"), numpy_helper.from_array(bias, "Bn")],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    path.write_bytes(model.SerializeToString())


@pytest.fixture(scope="module")
def model_sintetis(tmp_path_factory):
    pytest.importorskip("onnxruntime")
    path = tmp_path_factory.mktemp("reid_bucket") / "osnet_sintetis.onnx"
    _model_sintetis(path)
    return path


def _sesi_cpu(path):
    import onnxruntime as ort

    return ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])


def _pool(n=16):
    rng = np.random.default_rng(0)
    return rng.standard_normal((n, 3, 256, 128)).astype(np.float32)


class _SesiPalsu:
    """Merekam ukuran batch setiap run; keluaran = rata-rata per sampel (DIM kolom)."""

    def __init__(self):
        self.batch_dilihat = []

    def get_inputs(self):
        return [SimpleNamespace(name="input", shape=["N", 3, 256, 128])]

    def get_providers(self):
        return ["CPUExecutionProvider"]

    def run(self, _names, feed):
        x = feed["input"]
        self.batch_dilihat.append(x.shape[0])
        return [np.repeat(x.reshape(x.shape[0], -1).mean(axis=1, keepdims=True), DIM, axis=1)]


def _runner_palsu(buckets=(1, 2, 4, 8)):
    sesi = []

    def buat():
        sesi.append(_SesiPalsu())
        return sesi[-1]

    return ReidBucketRunner(buat, buckets, warmup_runs=3, sample_shape=(3, 4, 2)), sesi


# --------------------------------------------------------------------------
# Kebenaran di CPU EP dengan model sintetis
# --------------------------------------------------------------------------

@pytest.mark.parametrize("n", [0, 1, 3, 5, 8, 9, 10])
def test_bucket_identik_dengan_satu_sesi_tanpa_padding(model_sintetis, n):
    tunggal = _sesi_cpu(model_sintetis)
    runner = ReidBucketRunner(lambda: _sesi_cpu(model_sintetis), (1, 2, 4, 8))
    blob = _pool()[:n]
    got = runner.run(blob)
    assert got.shape == (n, DIM)
    assert got.dtype == np.float32
    if n:
        ref = tunggal.run(None, {"input": blob})[0]
        assert np.abs(got - ref).max() < 1e-5


def test_n_nol_kosong_tanpa_memanggil_sesi():
    runner, sesi = _runner_palsu()
    sebelum = [len(s.batch_dilihat) for s in sesi]
    out = runner.run(np.zeros((0, 3, 4, 2), np.float32))
    assert out.shape == (0, DIM)
    assert [len(s.batch_dilihat) for s in sesi] == sebelum


def test_tiap_sesi_hanya_melihat_shape_bucketnya():
    runner, sesi = _runner_palsu()
    assert [s.batch_dilihat for s in sesi] == [[b] * 3 for b in (1, 2, 4, 8)]   # warmup
    for n in (1, 2, 3, 5, 7, 8, 9, 10, 17, 3, 1):
        out = runner.run(np.ones((n, 3, 4, 2), np.float32))
        assert out.shape == (n, DIM)
    for bucket, s in zip((1, 2, 4, 8), sesi):
        assert set(s.batch_dilihat) == {bucket}


def test_lebih_dari_bucket_terbesar_dipecah_per_bucket_terbesar():
    runner, sesi = _runner_palsu((1, 2, 4))
    for s in sesi:
        s.batch_dilihat.clear()
    x = np.arange(11 * 24, dtype=np.float32).reshape(11, 3, 4, 2)
    out = runner.run(x)
    # 11 = 4 + 4 + 3 (padding ke 4); bucket 1 dan 2 tidak terpakai.
    assert [s.batch_dilihat for s in sesi] == [[], [], [4, 4, 4]]
    np.testing.assert_allclose(out[:, 0], x.reshape(11, -1).mean(axis=1), rtol=1e-6)


def test_lebih_dari_bucket_terbesar_model_sintetis(model_sintetis):
    tunggal = _sesi_cpu(model_sintetis)
    runner = ReidBucketRunner(lambda: _sesi_cpu(model_sintetis), (1, 2))
    blob = _pool()[:7]
    ref = tunggal.run(None, {"input": blob})[0]
    assert np.abs(runner.run(blob) - ref).max() < 1e-5


def test_bucket_tidak_sah_ditolak():
    with pytest.raises(ValueError):
        ReidBucketRunner(_SesiPalsu, (), sample_shape=(3, 4, 2))
    with pytest.raises(ValueError):
        ReidBucketRunner(_SesiPalsu, (0, 2), sample_shape=(3, 4, 2))


def test_provider_bukan_cuda_dicatat_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="engine.identity.reid.embedder_onnx"):
        _runner_palsu((1,))
    assert "BUKAN CUDAExecutionProvider" in caplog.text


# --------------------------------------------------------------------------
# Embedder: API publik tetap, isi lewat runner
# --------------------------------------------------------------------------

def _crops(n):
    rng = np.random.default_rng(5)
    return [rng.integers(0, 256, size=(200 + 10 * i, 90, 3), dtype=np.uint8) for i in range(n)]


def test_embedder_ujung_ke_ujung_dengan_bucket(model_sintetis, caplog):
    digest = hashlib.sha256(model_sintetis.read_bytes()).hexdigest()
    settings = ReidSettings(enabled=True, model_path=str(model_sintetis), model_sha256=digest,
                            batch_buckets=(1, 2, 4), onnx_providers=("CPUExecutionProvider",))
    with caplog.at_level(logging.INFO, logger="engine.identity.reid.embedder_onnx"):
        embedder = build_reid_embedder(settings)
    assert embedder.buckets == (1, 2, 4)
    assert embedder.dim == DIM
    assert "torch" in caplog.text
    tunggal = _sesi_cpu(model_sintetis)
    for n in (1, 3, 6):
        crops = _crops(n)
        ref = l2_rows(tunggal.run(None, {"input": preprocess(crops)})[0])
        got = embedder(crops)
        assert got.shape == (n, DIM)
        assert np.abs(got - ref).max() < 1e-5
    kosong = embedder.embed([])
    assert kosong.shape == (0, DIM)


def test_opsi_cuda_heuristic_digabung_tanpa_membuang_batas_vram():
    assert with_cuda_options(None) is None
    out = with_cuda_options([("CUDAExecutionProvider", {"gpu_mem_limit": 1}), "CPUExecutionProvider"])
    assert out == [("CUDAExecutionProvider", {"cudnn_conv_algo_search": "HEURISTIC", "gpu_mem_limit": 1}),
                   "CPUExecutionProvider"]
    assert with_cuda_options(["CUDAExecutionProvider", "CPUExecutionProvider"])[0] == (
        "CUDAExecutionProvider", {"cudnn_conv_algo_search": "HEURISTIC"})
    assert with_cuda_options(["CPUExecutionProvider"]) == ["CPUExecutionProvider"]


def test_nvrtc_hanya_diperiksa_di_windows():
    import os

    if os.name != "nt":
        assert embedder_onnx.loaded_nvrtc() is None


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def test_config_bucket_default_dan_model_ain():
    settings = ReidSettings()
    assert settings.batch_buckets == (1, 2, 4, 8)
    assert settings.model_path.endswith("osnet_ain_reid.onnx")
    for path in sorted((ROOT / "engine" / "config").glob("demo-*.yaml")):
        reid = load_config(str(path)).reid
        assert reid.model_path.endswith("osnet_ain_reid.onnx"), path.name
        assert reid.batch_buckets == (1, 2, 4, 8), path.name


@pytest.mark.parametrize("buruk", [(), (0, 1), (2, 1), (1, 1, 2)])
def test_config_bucket_tidak_sah_ditolak(buruk):
    with pytest.raises(ValueError, match="batch_buckets"):
        ReidSettings(batch_buckets=buruk)


def test_config_bucket_dibaca_dari_yaml(tmp_path):
    path = tmp_path / "engine.yaml"
    path.write_text("reid:\n  batch_buckets: [1, 4]\n", encoding="utf-8")
    assert load_config(str(path)).reid.batch_buckets == (1, 4)


# --------------------------------------------------------------------------
# fd 2 dialihkan; traceback Python tetap ke konsol
# --------------------------------------------------------------------------

def test_reid_cuda_memicu_pengalihan_stderr():
    from engine.runtime.__main__ import _reid_wants_cuda

    cuda = SimpleNamespace(reid=ReidSettings(enabled=True, onnx_providers=("CUDAExecutionProvider",)))
    cpu = SimpleNamespace(reid=ReidSettings(enabled=True, onnx_providers=("CPUExecutionProvider",)))
    mati = SimpleNamespace(reid=ReidSettings(enabled=False, onnx_providers=("CUDAExecutionProvider",)))
    assert _reid_wants_cuda(cuda)
    assert not _reid_wants_cuda(cpu)
    assert not _reid_wants_cuda(mati)
    assert not _reid_wants_cuda(load_config())


def test_fd2_ke_berkas_traceback_tetap_ke_konsol(tmp_path):
    log = tmp_path / "logs" / "engine-c-stderr.log"
    kode = textwrap.dedent(f"""
        import logging, os, sys
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        from pathlib import Path
        from engine.runtime.__main__ import _redirect_c_stderr
        _redirect_c_stderr(Path({str(log)!r}))
        os.write(2, b"Could not locate nvrtc64_120_0.dll\\n")
        logging.getLogger("uji").warning("log python ke konsol")
        raise RuntimeError("traceback ke konsol")
    """)
    hasil = subprocess.run([sys.executable, "-c", kode], cwd=str(ROOT), capture_output=True,
                           text=True, timeout=60)
    assert hasil.returncode != 0
    assert "traceback ke konsol" in hasil.stderr
    assert "log python ke konsol" in hasil.stderr
    assert "nvrtc" not in hasil.stderr
    assert "Could not locate nvrtc64_120_0.dll" in log.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# GPU + model asli (laptop): dilewati otomatis di cloud
# --------------------------------------------------------------------------

def _cuda_tersedia():
    try:
        import onnxruntime as ort
    except ImportError:
        return False
    return "CUDAExecutionProvider" in ort.get_available_providers()


@pytest.mark.skipif(not MODEL_ASLI.is_file(), reason="model asli osnet_ain_reid.onnx tidak ada")
@pytest.mark.skipif(not _cuda_tersedia(), reason="CUDAExecutionProvider tidak tersedia")
def test_gpu_model_asli_bucket_cepat_dan_identik():
    from engine.identity.face_onnx import _session

    prov = with_cuda_options(["CUDAExecutionProvider", "CPUExecutionProvider"])

    def buat():
        # Jalur engine: preload_dlls (DLL CUDA/cuDNN dari pip) + galat jelas bila CUDA
        # diminta tetapi jatuh ke CPU. InferenceSession mentah jatuh ke CPU diam-diam.
        return _session(str(MODEL_ASLI), prov, purpose="tes bucket GPU",
                        providers_key="reid.onnx_providers")

    runner = ReidBucketRunner(buat, (1, 2, 4, 8))
    for bucket, (sesi, _nama) in runner._sessions.items():
        assert sesi.get_providers()[0] == "CUDAExecutionProvider", f"bucket {bucket} tidak di CUDA"
    tunggal = buat()
    pool = _pool()
    jumlah = np.random.default_rng(0).integers(1, 11, 60)
    waktu = []
    for n in jumlah:
        t = time.perf_counter()
        runner.run(pool[:n])
        waktu.append((time.perf_counter() - t) * 1e3)
    for n in (1, 3, 5, 10):
        ref = tunggal.run(None, {tunggal.get_inputs()[0].name: pool[:n]})[0]
        assert np.abs(runner.run(pool[:n]) - ref).max() < 1e-4
    assert sum(w > 100 for w in waktu) <= 1, f"frame > 100 ms: {sorted(waktu)[-5:]}"
