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
