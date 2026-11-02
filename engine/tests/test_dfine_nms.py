"""Overhaul P3: NMS engine pada hasil mentah D-FINE (LibreYOLO 1.6 tidak menjalankannya)."""
from __future__ import annotations

import numpy as np
import pytest

from engine.perception.dfine_detector import nms_keep
from engine.tests.test_live_ingest_and_detector_prep import FakeModel, _detector, _frame

# Dua kotak hampir sama pada satu orang + satu orang lain di sebelahnya.
BOXES = [[100, 100, 300, 600], [105, 102, 302, 598], [400, 100, 600, 600]]
CONF = [0.90, 0.80, 0.70]


def test_kotak_ganda_satu_orang_jadi_satu_untuk_detect_dan_bytetrack():
    detector = _detector(FakeModel(BOXES, CONF), nms_iou_threshold=0.7)
    frame = _frame()
    detections = detector.detect(frame)
    assert [round(d.confidence, 2) for d in detections] == [0.9, 0.7]
    assert len(detector.last_result.boxes) == 2, "ByteTrack membaca Results yang sama"


def test_tanpa_nms_perilaku_lama():
    detector = _detector(FakeModel(BOXES, CONF))
    assert len(detector.detect(_frame())) == 3


def test_dua_orang_berdekatan_tidak_dilebur():
    # IoU ±0,43: bahu bersentuhan, bukan duplikat.
    xyxy = np.array([[0, 0, 100, 300], [60, 0, 160, 300]], dtype=np.float32)
    keep = nms_keep(xyxy, np.array([0.9, 0.8], np.float32), np.zeros(2, int), 0.7)
    assert keep.tolist() == [0, 1]


def test_nms_per_kelas_dan_terurut_skor():
    xyxy = np.array([[0, 0, 10, 10], [0, 0, 10, 10], [0, 0, 10, 10]], dtype=np.float32)
    keep = nms_keep(xyxy, np.array([0.5, 0.9, 0.7], np.float32), np.array([0, 0, 1]), 0.7)
    assert keep.tolist() == [1, 2]


def test_ambang_di_luar_rentang_ditolak():
    from engine.config.schema import DetectorConfig

    with pytest.raises(ValueError):
        DetectorConfig(nms_iou_threshold=0.0)
    assert DetectorConfig().nms_iou_threshold is None
