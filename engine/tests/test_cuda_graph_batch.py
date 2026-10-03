"""detector.cuda_graph dan batch sungguhan (LibreYOLO >= 1.6).

Uji RTX 4060, 3 Okt: forward D-FINE M eager 57 ms, CUDA graph 12,6 ms, forward
batch 5 langsung 15 ms/gambar, tetapi batch lewat LibreYOLO hanya 1,1x karena
daftar gambar tanpa `batch=` diproses satu per satu.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from engine.perception.dfine_detector import DFINEDetector, normalize_cuda_graph, version_tuple


class Model:
    names = {0: "person"}

    def __init__(self, accept_graph=True, accept_batch=True):
        self.calls = []
        self.accept_graph = accept_graph
        self.accept_batch = accept_batch

    def _one(self):
        return SimpleNamespace(boxes=None)

    def __call__(self, image, **kwargs):
        self.calls.append(kwargs)
        if "cuda_graph" in kwargs and not self.accept_graph:
            raise TypeError("Unsupported predict option(s): cuda_graph")
        if "batch" in kwargs and not self.accept_batch:
            raise TypeError("Unsupported predict option(s): batch")
        if isinstance(image, list):
            return [self._one() for _ in image]
        return self._one()


def _detector(model, **kwargs):
    detector = DFINEDetector(device=0, load_model=False, **kwargs)
    detector._model = model
    return detector


def _img():
    return np.zeros((8, 8, 3), np.uint8)


def test_cuda_graph_diteruskan_ke_libreyolo():
    model = Model()
    _detector(model, cuda_graph=True)._predict(_img())
    assert model.calls[-1]["cuda_graph"] is True


def test_cuda_graph_mati_secara_default_dan_di_cpu():
    model = Model()
    _detector(model)._predict(_img())
    assert "cuda_graph" not in model.calls[-1]
    cpu = DFINEDetector(device="cpu", load_model=False, cuda_graph=True)
    assert cpu._cuda_graph is False


def test_libreyolo_lama_menolak_cuda_graph_jatuh_ke_eager_sekali(caplog):
    model = Model(accept_graph=False)
    detector = _detector(model, cuda_graph="auto")
    detector._predict(_img())
    detector._predict(_img())
    assert detector._cuda_graph is False
    assert "cuda_graph" not in model.calls[-1]
    assert sum("cuda_graph rejected" in r.message for r in caplog.records) == 1


def test_error_lain_tidak_ditelan():
    class Broken(Model):
        def __call__(self, image, **kwargs):
            raise ValueError("CUDA out of memory")

    with pytest.raises(ValueError):
        _detector(Broken(), cuda_graph=True)._predict(_img())


def test_batch_mengirim_batch_sama_dengan_jumlah_gambar():
    """Tanpa batch=, LibreYOLO menjalankan daftar gambar satu per satu."""
    model = Model()
    detector = _detector(model, batch_inference=True, cuda_graph=True)
    out = detector.predict_images([_img(), _img(), _img()])
    assert len(out) == 3
    assert model.calls[-1]["batch"] == 3 and model.calls[-1]["cuda_graph"] is True
    assert detector._batch_supported is True


def test_libreyolo_tanpa_batch_kembali_per_gambar():
    model = Model(accept_batch=False)
    detector = _detector(model, batch_inference=True)
    assert len(detector.predict_images([_img(), _img()])) == 2
    assert detector._batch_supported is False
    assert "batch" not in model.calls[-1]


@pytest.mark.parametrize("value,expected", [(True, True), (False, False), ("auto", "auto"), ("true", True),
                                            ("off", False)])
def test_normalize(value, expected):
    assert normalize_cuda_graph(value) == expected


def test_nilai_aneh_ditolak():
    with pytest.raises(ValueError):
        normalize_cuda_graph("kadang")


def test_versi():
    assert version_tuple("1.6.0") >= (1, 6) and version_tuple("1.5.2") < (1, 6)
    assert version_tuple("1.6.0rc1") == (1, 6, 0)


def test_config_cuda_graph():
    import dataclasses

    from engine.config import load_config
    from engine.config.schema import DetectorConfig

    config = load_config("engine/config/dfine-m.yaml")
    assert config.detector.cuda_graph is False
    assert dataclasses.replace(config.detector, cuda_graph="auto").cuda_graph == "auto"
    with pytest.raises(ValueError):
        dataclasses.replace(config.detector, cuda_graph="kadang")
    assert DetectorConfig().cuda_graph is False


# --------------------------------------------------------------------------
# fast_preprocess: pra-proses di GPU, wajib bit-identik dengan LibreYOLO
# --------------------------------------------------------------------------

from engine.perception.dfine_detector import _fast_tensor, install_fast_preprocess  # noqa: E402


class HookModel(Model):
    device = None

    def __init__(self):
        super().__init__()
        self.original_calls = 0

    def _preprocess(self, image, color_format="auto", input_size=None, **kwargs):
        self.original_calls += 1
        return ("asli", None, (0, 0), 1.0)


def test_kasus_yang_bukan_salinan_polos_tidak_disentuh():
    rgb = np.zeros((640, 640, 3), np.uint8)
    assert _fast_tensor(rgb, "bgr", 640, None) is None                       # BGR: LibreYOLO membalik kanal
    assert _fast_tensor(np.zeros((720, 1280, 3), np.uint8), "rgb", 640, None) is None   # perlu resize
    assert _fast_tensor(rgb.astype(np.float32), "rgb", 640, None) is None    # bukan uint8
    assert _fast_tensor(rgb, "rgb", None, None) is None


def test_hook_kembali_ke_pra_proses_libreyolo_saat_mati_atau_tidak_cocok():
    detector = _detector(HookModel(), fast_preprocess=True)
    assert install_fast_preprocess(detector)
    model = detector._model
    out = model._preprocess_predict(np.zeros((720, 1280, 3), np.uint8), "bgr", input_size=640)
    assert out[0] == "asli" and model.original_calls == 1
    detector._fast_preprocess = False
    out = model._preprocess_predict(np.zeros((640, 640, 3), np.uint8), "rgb", input_size=640)
    assert out[0] == "asli" and model.original_calls == 2 and detector._fast_preprocess_hits == 0


def test_tensor_sama_persis_dengan_libreyolo():
    """Berjalan di mesin yang punya torch + LibreYOLO (laptop uji)."""
    torch = pytest.importorskip("torch")
    dfine_utils = pytest.importorskip("libreyolo.models.dfine.utils")
    rng = np.random.default_rng(3)
    rgb = rng.integers(0, 256, (640, 640, 3), dtype=np.uint8)
    reference, _, size, ratio = dfine_utils.preprocess_image(rgb, input_size=640, color_format="rgb")
    fast = _fast_tensor(rgb, "rgb", 640, None)
    assert fast.shape == reference.shape and fast.dtype == reference.dtype
    assert torch.equal(fast, reference), "pra-proses cepat wajib bit-identik"
    assert size == (640, 640) and ratio == 1.0


def test_hook_mengembalikan_tensor_dan_ukuran_asli():
    torch = pytest.importorskip("torch")
    detector = _detector(HookModel(), fast_preprocess=True)
    install_fast_preprocess(detector)
    rgb = np.full((640, 640, 3), 255, np.uint8)
    tensor, orig, size, ratio = detector._model._preprocess_predict(rgb, "rgb", input_size=640)
    assert isinstance(tensor, torch.Tensor) and tensor.shape == (1, 3, 640, 640)
    assert float(tensor.max()) == 1.0 and size == (640, 640) and ratio == 1.0
    assert orig.shape == (640, 640, 3) and detector._fast_preprocess_hits == 1


def test_tensor_di_gpu_juga_sama_persis():
    """Uji 4060 20:13: `.div_(255.0)` di CUDA beda 1 ulp (IoU 0,989). Tabel lookup wajib identik."""
    torch = pytest.importorskip("torch")
    dfine_utils = pytest.importorskip("libreyolo.models.dfine.utils")
    if not torch.cuda.is_available():
        pytest.skip("butuh CUDA")
    rgb = np.random.default_rng(5).integers(0, 256, (640, 640, 3), dtype=np.uint8)
    reference, _, _, _ = dfine_utils.preprocess_image(rgb, input_size=640, color_format="rgb")
    fast = _fast_tensor(rgb, "rgb", 640, "cuda")
    assert fast.is_cuda and torch.equal(fast.cpu(), reference)


def test_lut_sama_dengan_pembagian_numpy():
    from engine.perception import dfine_detector as module

    values = np.arange(256, dtype=np.uint8).astype(np.float32) / 255.0
    assert values.dtype == np.float32 and values[255] == 1.0 and values[0] == 0.0
    assert np.array_equal(values, np.array([np.float32(v) / np.float32(255.0) for v in range(256)], np.float32))
    assert hasattr(module, "_normalise_lut")


def test_tabel_pembagi_di_cpu():
    torch = pytest.importorskip("torch")
    from engine.perception.dfine_detector import _normalise_lut

    lut = _normalise_lut("cpu", torch).numpy()
    assert np.array_equal(lut, np.arange(256, dtype=np.float32) / np.float32(255.0))


def test_pembanding_fp32_dipulihkan():
    from engine.tools.batch_check import run

    detector = _detector(Model(), batch_inference=True)
    detector._half = True
    seen = []
    original = detector._call

    def spy(*a, **k):
        seen.append(detector._half)
        return original(*a, **k)

    detector._call = spy
    run(detector, [np.zeros((8, 8, 3), np.uint8)] * 2, [1], repeat=1, reference_fp32=True)
    assert seen[0] is False and seen[-1] is True and detector._half is True
