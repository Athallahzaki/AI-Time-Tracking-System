"""Fallback kotak penuh untuk rekognisi wajah (paket ea-r30).

Kasus lapangan 12 Nov: tangan terangkat lurus. Batas atas kotak orang pindah ke
ujung jari; wajah jatuh di ±42-72% tinggi kotak, di luar potongan kepala 45%
teratas. SCRFD hanya melihat tangan dan lengan, jadi setiap percobaan gagal
sampai tangan turun, padahal wajah frontal dan tidak tertutup. Dengan
`recognition.full_box_fallback: true`, potongan kepala yang kosong dicari ulang
sekali di seluruh kotak.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import List

import numpy as np
import pytest

from engine.config import load_config
from engine.identity import face_onnx
from engine.identity.face_onnx import (
    FaceDetection,
    OnnxFaceRecognizer,
    full_box_crop,
    head_crop,
)

FRONTAL = np.array([[30, 40], [70, 40], [50, 60], [35, 80], [65, 80]], dtype=np.float32)

# Kotak tangan terangkat: tinggi 300, ujung jari di y=0, wajah 126-216 (42-72%).
KOTAK_TANGAN_NAIK = SimpleNamespace(x1=100, y1=0, x2=300, y2=300)
WAJAH_ATAS, WAJAH_BAWAH = 126, 216


class DetectorBerpotongan:
    """SCRFD palsu: wajah ada bila potongan (koordinat potongan) memuat seluruh wajah."""

    def __init__(self, face_box) -> None:
        self.face_box = face_box  # (x1, y1, x2, y2) dalam koordinat potongan kotak penuh
        self.calls: List[tuple] = []

    def detect(self, crop):
        self.calls.append(crop.shape[:2])
        x1, y1, x2, y2 = self.face_box
        if crop.shape[0] < y2 or crop.shape[1] < x2:
            return []
        size = x2 - x1
        landmarks = FRONTAL * (size / 100.0) + np.array([x1, y1], np.float32)
        return [FaceDetection(bbox=(x1, y1, x2, y2), score=0.9, landmarks=landmarks)]


class EmbedderPalsu:
    input_size = 112

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, aligned):
        self.calls += 1
        vector = np.ones(512, np.float32)
        return vector / np.linalg.norm(vector)


def _panggil(recognizer, box=KOTAK_TANGAN_NAIK):
    track = SimpleNamespace(bbox=box)
    frame = SimpleNamespace(image=np.zeros((400, 500, 3), np.uint8), metadata=SimpleNamespace(pts=2.0))
    return recognizer(track, frame)


def _recognizer(face_box, **kwargs):
    detector, embedder = DetectorBerpotongan(face_box), EmbedderPalsu()
    recognizer = OnnxFaceRecognizer(detector, embedder, "auraface-v1", min_face_px=40, **kwargs)
    return recognizer, detector, embedder


WAJAH_TENGAH = (55, WAJAH_ATAS, 145, WAJAH_BAWAH)   # pusat x = 100 dari lebar 200


def test_tangan_naik_wajah_di_luar_potongan_kepala():
    """Akar masalahnya geometri: potongan 45% berhenti sebelum wajah."""
    image = np.zeros((400, 500, 3), np.uint8)
    head, _ = head_crop(image, KOTAK_TANGAN_NAIK, 40)
    full, offset = full_box_crop(image, KOTAK_TANGAN_NAIK, 40)
    assert head.shape[0] == 135 < WAJAH_BAWAH
    assert full.shape[0] == 300 >= WAJAH_BAWAH and offset == (100, 0)


def test_default_mati_perilaku_lama():
    recognizer, detector, embedder = _recognizer(WAJAH_TENGAH)
    assert _panggil(recognizer) is None
    assert len(detector.calls) == 1 and embedder.calls == 0
    assert recognizer.gate_metrics()["fallback_dicoba"] == 0


def test_fallback_menemukan_wajah_di_tengah_kotak():
    recognizer, detector, embedder = _recognizer(WAJAH_TENGAH, full_box_fallback=True)
    evidence = _panggil(recognizer)
    assert evidence is not None and evidence.pts == 2.0
    assert detector.calls == [(135, 200), (300, 200)]
    assert embedder.calls == 1
    metrics = recognizer.gate_metrics()
    assert (metrics["fallback_dicoba"], metrics["fallback_ketemu"], metrics["embedded"]) == (1, 1, 1)


def test_landmark_digeser_ke_koordinat_frame(monkeypatch):
    seen = {}

    def align(image, landmarks, size):
        seen["landmarks"] = landmarks.copy()
        return np.zeros((size, size, 3), np.uint8)

    monkeypatch.setattr(face_onnx, "align_face", align)
    recognizer, _, _ = _recognizer(WAJAH_TENGAH, full_box_fallback=True)
    assert _panggil(recognizer) is not None
    # mata kiri: 55 + 30*0.9 (potongan) + 100 (x1 kotak); y: 126 + 40*0.9 + 0
    assert seen["landmarks"][0] == pytest.approx([55 + 27 + 100, WAJAH_ATAS + 36])


def test_wajah_di_pinggir_kotak_ditolak():
    """Wajah orang lain yang kotaknya tumpang-tindih biasanya di tepi, bukan di tengah."""
    recognizer, _, embedder = _recognizer((0, WAJAH_ATAS, 60, WAJAH_ATAS + 60), full_box_fallback=True)
    assert _panggil(recognizer) is None
    assert embedder.calls == 0
    metrics = recognizer.gate_metrics()
    assert (metrics["fallback_dicoba"], metrics["fallback_ketemu"]) == (1, 0)


def test_potongan_kepala_berhasil_fallback_tidak_dipanggil():
    recognizer, detector, _ = _recognizer((55, 20, 145, 110), full_box_fallback=True)
    assert _panggil(recognizer) is not None
    assert len(detector.calls) == 1
    assert recognizer.gate_metrics()["fallback_dicoba"] == 0


def test_kotak_pendek_tidak_dicari_ulang():
    """Kotak setinggi min_face_px: potongan kepala sudah seluruh kotak, tidak ada yang baru."""
    box = SimpleNamespace(x1=0, y1=0, x2=60, y2=40)
    recognizer, detector, _ = _recognizer((0, 0, 50, 50), full_box_fallback=True)
    assert _panggil(recognizer, box) is None
    assert len(detector.calls) == 1
    assert recognizer.gate_metrics()["fallback_dicoba"] == 0


def test_config_dibaca_default_mati(tmp_path):
    assert load_config().recognition.full_box_fallback is False
    path = tmp_path / "c.yaml"
    path.write_text("recognition:\n  full_box_fallback: true\n", encoding="utf-8")
    assert load_config(str(path)).recognition.full_box_fallback is True


def test_build_recognizer_meneruskan_flag(monkeypatch, tmp_path):
    monkeypatch.setattr(face_onnx, "ScrfdDetector", lambda *a, **k: DetectorBerpotongan(WAJAH_TENGAH))
    monkeypatch.setattr(face_onnx, "OnnxFaceEmbedder", lambda *a, **k: EmbedderPalsu())
    rec = SimpleNamespace(
        recognizer="onnx_face", face_detector_model="d.onnx", face_embedder_model="e.onnx",
        onnx_providers=None, onnx_gpu_mem_limit_mb=None, face_detection_threshold=0.5,
        embedding_version="auraface-v1", min_face_px=40.0, full_box_fallback=True,
    )
    recognizer = face_onnx.build_recognizer(rec)
    assert _panggil(recognizer) is not None
