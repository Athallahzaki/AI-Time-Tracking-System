"""engine/tools/batch_check.py: batching hanya boleh dinyalakan bila hasilnya sama."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

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
    assert "BATCH MENGUBAH HASIL" not in report.verdict


def test_batch_yang_menggeser_kotak_ditolak():
    report = run(_detector(Model(shift_in_batch=3.0)), _images(), [3], repeat=1)
    assert report.sizes[0].mismatched_images == 6
    assert "BATCH MENGUBAH HASIL" in report.verdict
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
