"""engine/tools/batch_check.py: batching hanya boleh dinyalakan bila hasilnya sama."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from engine.tools.batch_check import compare, format_report, run


class Boxes:
    def __init__(self, xyxy, conf):
        self.xyxy = np.asarray(xyxy, np.float32).reshape(-1, 4)
        self.conf = np.asarray(conf, np.float32)
        self.cls = np.zeros(len(self.conf), np.float32)
        self.id = None

    def __len__(self):
        return len(self.conf)


class Model:
    names = {0: "person"}

    def __init__(self, batch=True, shift_in_batch=0.0):
        self.batch = batch
        self.shift = shift_in_batch

    def _one(self, image, shift=0.0):
        tag = float(image[0, 0, 0])
        return SimpleNamespace(boxes=Boxes([[tag + shift, 0, tag + 10 + shift, 10]], [0.9]),
                               orig_shape=image.shape[:2])

    def __call__(self, image, **kwargs):
        if isinstance(image, list):
            if not self.batch:
                raise TypeError("tidak ada batch")
            return [self._one(item, self.shift) for item in image]
        return self._one(image)


def _detector(model):
    from engine.perception.dfine_detector import DFINEDetector

    detector = DFINEDetector(device="cpu", load_model=False, batch_inference=True)
    detector._model = model
    return detector


def _images(n=6):
    return [np.full((8, 8, 3), 10 * i, dtype=np.uint8) for i in range(n)]


def test_batch_yang_benar_lolos():
    report = run(_detector(Model()), _images(), [1, 3], repeat=1)
    assert report.batch_supported is True
    assert all(s.mismatched_images == 0 for s in report.sizes)
    assert "HASIL BERUBAH" not in report.verdict


def test_batch_yang_menggeser_kotak_ditolak():
    report = run(_detector(Model(shift_in_batch=3.0)), _images(), [3], repeat=1)
    assert report.sizes[0].mismatched_images == 6
    assert "HASIL BERUBAH" in report.verdict
    assert "KESIMPULAN" in format_report(report)


def test_libreyolo_tanpa_batch_dilaporkan():
    report = run(_detector(Model(batch=False)), _images(), [3], repeat=1)
    assert report.batch_supported is False
    assert "tidak menerima batch" in report.verdict


def test_compare_jumlah_kotak_beda_tidak_cocok():
    a = SimpleNamespace(boxes=Boxes([[0, 0, 10, 10]], [0.9]))
    b = SimpleNamespace(boxes=Boxes(np.zeros((0, 4)), []))
    assert compare(a, b)[0] is False
    assert compare(a, a)[0] is True


def test_vonis_saat_ukuran_1_tercepat_bukan_batch():
    """Uji 4060 3 Okt 19:28 (LibreYOLO 1.6, cuda_graph): 29,5 / 34,3 / 53,4 ms untuk ukuran 1/2/5.
    Vonis lama berbunyi "layak dinyalakan (batch_inference: true, max_batch: 1)"."""
    from engine.tools.batch_check import Report, SizeResult

    report = Report(images=60, reference_ms_per_image=206.8, batch_supported=True, cuda_graph=True,
                    sizes=[SizeResult(1, 29.5, 7.01), SizeResult(2, 34.3, 6.03, True),
                           SizeResult(5, 53.4, 3.87, True)])
    assert "batch TIDAK membantu" in report.verdict and "batch_inference: false" in report.verdict
    assert "cuda_graph: true" in report.verdict


def test_vonis_batch_dibanding_ukuran_1_bukan_eager():
    from engine.tools.batch_check import Report, SizeResult

    report = Report(images=60, reference_ms_per_image=80.0, batch_supported=True,
                    sizes=[SizeResult(1, 30.0, 2.67), SizeResult(5, 15.0, 5.33, True)])
    assert "2.00x lebih cepat per gambar dibanding ukuran 1" in report.verdict
    assert "max_batch: 5" in report.verdict


def test_kotak_skor_rendah_yang_beda_tidak_menggagalkan_vonis():
    """Uji 4060 20:24 (FP16 vs FP32): 2 gambar beda jumlah kotak. Yang menentukan
    adalah kotak di atas ambang deteksi; kotak 0,1-an hanya kandidat ByteTrack."""
    from engine.tools.batch_check import compare_detail

    ref = SimpleNamespace(boxes=Boxes([[0, 0, 10, 10], [50, 50, 60, 60]], [0.9, 0.12]))
    cand = SimpleNamespace(boxes=Boxes([[0, 0, 10, 10]], [0.9]))
    ok, _, _, unmatched = compare_detail(ref, cand, 0.5)
    assert ok and not unmatched
    ok_all, _, _, unmatched_all = compare_detail(ref, cand, None)
    assert not ok_all and unmatched_all == [pytest.approx(0.12)]


def test_kotak_tepat_di_ambang_tidak_dihitung_hilang():
    from engine.tools.batch_check import compare_detail

    ref = SimpleNamespace(boxes=Boxes([[0, 0, 10, 10]], [0.505]))
    cand = SimpleNamespace(boxes=Boxes([[0, 0, 10, 10]], [0.495]))
    assert compare_detail(ref, cand, 0.5)[0] is True


def test_kotak_di_atas_ambang_yang_hilang_tetap_gagal():
    from engine.tools.batch_check import compare_detail

    ref = SimpleNamespace(boxes=Boxes([[0, 0, 10, 10], [50, 50, 60, 60]], [0.9, 0.8]))
    cand = SimpleNamespace(boxes=Boxes([[0, 0, 10, 10]], [0.9]))
    ok, _, _, unmatched = compare_detail(ref, cand, 0.5)
    assert not ok and unmatched == [pytest.approx(0.8)]
