"""Beban rekognisi wajah (paket ea-r9).

Uji 4060 15 Okt, 6 fps × 5 kamera: worker rekognisi jenuh di ±18 wajah/dtk (54 ms
per wajah) dan membuang 35% permintaan. Input SCRFD 480 pada model berbentuk tetap
640 membuatnya 10× lebih lambat. Di sini diuji: gerbang kualitas sebelum embedding,
penolakan ukuran input yang tidak cocok dengan model, setelan mundur penjadwal,
peringatan worker jenuh, kode keluar 2 untuk config salah, dan laporan batch_check.
"""

from __future__ import annotations

import dataclasses
import logging
from types import SimpleNamespace
from typing import Any, List

import numpy as np
import pytest

from engine.config import load_config
from engine.identity.face_onnx import (
    FaceDetection,
    ModelConfigMismatch,
    OnnxFaceRecognizer,
    RecognizerUnavailable,
    _check_static_size,
    yaw_ratio,
)
from engine.runtime import EngineRuntime, RuntimeOptions
from engine.runtime.service import ALLOW_BATCH_CUDA_GRAPH_ENV, EXIT_CODE_CONFIG
from engine.tools.batch_check import Report, SizeResult, format_report

FRONTAL = np.array([[30, 40], [70, 40], [50, 60], [35, 80], [65, 80]], dtype=np.float32)
SAMPING = np.array([[30, 40], [70, 40], [72, 60], [55, 80], [75, 80]], dtype=np.float32)


# --------------------------------------------------------------------------
# pengukur hadap samping
# --------------------------------------------------------------------------

def test_wajah_frontal_hampir_nol_dan_samping_besar():
    assert yaw_ratio(FRONTAL) == pytest.approx(0.0, abs=1e-6)
    assert yaw_ratio(SAMPING) == pytest.approx(0.55, abs=1e-6)
    assert yaw_ratio(np.zeros((5, 2), np.float32)) == float("inf")


# --------------------------------------------------------------------------
# bentuk model SCRFD
# --------------------------------------------------------------------------

def _keluaran(*shapes):
    return [SimpleNamespace(shape=list(shape)) for shape in shapes] + [SimpleNamespace(shape=[1])] * 6


def test_model_bentuk_tetap_640_cocok_dengan_640():
    _check_static_size("scrfd.onnx", _keluaran([12800, 1], [3200, 1], [800, 1]), 640, (8, 16, 32), 2)


def test_model_bentuk_tetap_640_menolak_480():
    with pytest.raises(ModelConfigMismatch, match="face_detector_input_size=480") as caught:
        _check_static_size("scrfd.onnx", _keluaran([12800, 1], [3200, 1], [800, 1]), 480, (8, 16, 32), 2)
    assert isinstance(caught.value, RecognizerUnavailable), "pemanggil lama yang menangkap RecognizerUnavailable"


def test_model_berdimensi_dinamis_tidak_diperiksa():
    _check_static_size("scrfd.onnx", _keluaran(["n", 1], ["n", 1], ["n", 1]), 480, (8, 16, 32), 2)
    _check_static_size("scrfd.onnx", _keluaran([1, 12800, 1], [1, 3200, 1], [1, 800, 1]), 640, (8, 16, 32), 2)


# --------------------------------------------------------------------------
# gerbang kualitas sebelum embedding
# --------------------------------------------------------------------------

class DetectorPalsu:
    def __init__(self, faces: List[FaceDetection]) -> None:
        self.faces = faces

    def detect(self, crop):
        return list(self.faces)


class EmbedderPalsu:
    input_size = 112

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, aligned):
        self.calls += 1
        vector = np.ones(512, np.float32)
        return vector / np.linalg.norm(vector)


def _wajah(size: float, score: float = 0.9, landmarks=FRONTAL) -> FaceDetection:
    scale = size / 100.0
    return FaceDetection(bbox=(0.0, 0.0, size, size), score=score, landmarks=landmarks * scale)


def _panggil(recognizer):
    track = SimpleNamespace(bbox=SimpleNamespace(x1=0, y1=0, x2=400, y2=800))
    frame = SimpleNamespace(image=np.zeros((900, 500, 3), np.uint8), metadata=SimpleNamespace(pts=1.0))
    return recognizer(track, frame)


def _recognizer(face, **gate):
    embedder = EmbedderPalsu()
    recognizer = OnnxFaceRecognizer(DetectorPalsu([face]), embedder, "auraface-v1", min_face_px=40, **gate)
    return recognizer, embedder


def test_gerbang_mati_semua_wajah_di_embed_seperti_dulu():
    recognizer, embedder = _recognizer(_wajah(50, score=0.55, landmarks=SAMPING))
    assert _panggil(recognizer) is not None
    assert embedder.calls == 1
    assert recognizer.gate_metrics()["embedded"] == 1


@pytest.mark.parametrize("face, gate, alasan", [
    (_wajah(50), {"embed_min_face_px": 64}, "lewati_kecil"),
    (_wajah(100, score=0.55), {"embed_min_score": 0.7}, "lewati_skor"),
    (_wajah(100, landmarks=SAMPING), {"embed_max_yaw": 0.35}, "lewati_samping"),
])
def test_gerbang_melewati_wajah_tanpa_memanggil_embedder(face, gate, alasan):
    recognizer, embedder = _recognizer(face, **gate)
    assert _panggil(recognizer) is None
    assert embedder.calls == 0, "glintr100 dipanggil untuk wajah yang seharusnya dilewati"
    metrics = recognizer.gate_metrics()
    assert metrics[alasan] == 1 and metrics["embedded"] == 0


def test_wajah_bagus_lolos_semua_gerbang():
    recognizer, embedder = _recognizer(_wajah(100), embed_min_face_px=64, embed_min_score=0.7,
                                       embed_max_yaw=0.35)
    evidence = _panggil(recognizer)
    assert evidence is not None and embedder.calls == 1


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

def test_config_gerbang_dan_mundur_dibaca_dan_diteruskan(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text(
        "recognition:\n  embed_min_face_px: 64\n  embed_min_score: 0.7\n  embed_max_yaw: 0.35\n"
        "  backoff_interval_seconds: 8\n  attempts_before_backoff: 3\n", encoding="utf-8")
    rec = load_config(str(path)).recognition
    assert (rec.embed_min_face_px, rec.embed_min_score, rec.embed_max_yaw) == (64.0, 0.7, 0.35)
    kwargs = rec.scheduler_kwargs()
    assert kwargs["backoff_interval_seconds"] == 8.0 and kwargs["attempts_before_backoff"] == 3


def test_default_tidak_berubah():
    rec = load_config().recognition
    assert rec.embed_min_face_px is None and rec.embed_min_score is None and rec.embed_max_yaw is None
    assert "backoff_interval_seconds" not in rec.scheduler_kwargs()
    assert "attempts_before_backoff" not in rec.scheduler_kwargs()


@pytest.mark.parametrize("field, value", [
    ("embed_min_score", 1.5), ("embed_max_yaw", 0.0), ("embed_min_face_px", -1.0),
    ("backoff_interval_seconds", 0.0), ("attempts_before_backoff", 0),
])
def test_nilai_gerbang_salah_ditolak(field, value):
    rec = load_config().recognition
    with pytest.raises(ValueError, match=field):
        dataclasses.replace(rec, **{field: value})


# --------------------------------------------------------------------------
# peringatan worker jenuh
# --------------------------------------------------------------------------

def _runtime() -> EngineRuntime:
    config = dataclasses.replace(load_config(), source_type="mock", auto_warmup=False)
    return EngineRuntime(config=config, options=RuntimeOptions(tcp=("127.0.0.1", 0)))


def _worker(processed, rejected, stale, ms=54.0):
    return {"processed": processed, "rejected_full": rejected, "dropped_stale": stale, "avg_recognize_ms": ms}


def test_peringatan_saat_worker_membuang_banyak_permintaan(caplog):
    runtime = _runtime()
    try:
        caplog.set_level(logging.WARNING, logger="engine.runtime")
        assert runtime._report_recognition_load(100.0, _worker(0, 0, 0)) is None
        ratio = runtime._report_recognition_load(130.0, _worker(480, 210, 50))
        assert ratio == pytest.approx(260 / 740)
        assert any("membuang 35%" in r.getMessage() for r in caplog.records)
        caplog.clear()
        assert runtime._report_recognition_load(160.0, _worker(960, 225, 55)) == pytest.approx(20 / 500)
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert runtime._report_recognition_load(161.0, _worker(965, 225, 55)) is None, "terlalu sedikit untuk dinilai"
    finally:
        runtime.close()


# --------------------------------------------------------------------------
# kode keluar 2 untuk config salah
# --------------------------------------------------------------------------

def test_config_tidak_valid_keluar_kode_2(tmp_path):
    from engine.runtime.__main__ import main

    path = tmp_path / "rusak.yaml"
    path.write_text("core:\n  kunci_tidak_ada: 1\n", encoding="utf-8")
    assert main(["--config", str(path), "--tcp", "127.0.0.1:0", "--outbox", str(tmp_path / "o.sqlite3"),
                 "--quiet"]) == EXIT_CODE_CONFIG == 2


def test_config_ditolak_runtime_keluar_kode_2(tmp_path, monkeypatch):
    from engine.runtime.__main__ import main

    monkeypatch.delenv(ALLOW_BATCH_CUDA_GRAPH_ENV, raising=False)
    path = tmp_path / "batch.yaml"
    path.write_text("core:\n  source_type: mock\n  auto_warmup: false\n"
                    "detector:\n  batch_inference: true\n  cuda_graph: true\n", encoding="utf-8")
    assert main(["--config", str(path), "--tcp", "127.0.0.1:0", "--outbox", str(tmp_path / "o.sqlite3"),
                 "--quiet"]) == EXIT_CODE_CONFIG


def test_model_tidak_cocok_dengan_config_keluar_kode_2(tmp_path, monkeypatch):
    from engine.runtime import __main__ as entry

    def tolak(*_args, **_kwargs):
        raise ModelConfigMismatch("scrfd.onnx: model ini berbentuk tetap")

    monkeypatch.setattr(entry, "_build_runtime", tolak)
    assert entry.main(["--tcp", "127.0.0.1:0", "--outbox", str(tmp_path / "o.sqlite3"), "--quiet"]) == 2


# --------------------------------------------------------------------------
# laporan batch_check
# --------------------------------------------------------------------------

def test_laporan_batch_check_ascii_dan_membandingkan_dengan_ukuran_1():
    report = Report(images=60, reference_ms_per_image=139.8, batch_supported=True, sizes=[
        SizeResult(batch_size=1, ms_per_image=17.6, speedup=7.94),
        SizeResult(batch_size=5, ms_per_image=18.6, speedup=7.51, batched=True),
    ], detection_threshold=0.5)
    text = format_report(report)
    text.encode("cp1252")  # konsol Windows yang dialirkan ke Tee-Object
    assert "vs ukuran1" in text
    baris5 = next(line for line in text.splitlines() if line.strip().startswith("5 "))
    assert "0.95x" in baris5, "batch 5 harus terlihat LEBIH LAMBAT dari ukuran 1, bukan 7,5x lebih cepat"


def test_laporan_tanpa_ukuran_1_memberi_petunjuk():
    report = Report(images=60, reference_ms_per_image=160.8, batch_supported=True,
                    sizes=[SizeResult(batch_size=5, ms_per_image=19.7, speedup=8.16, batched=True)])
    assert "tambahkan 1 ke --batch-sizes" in format_report(report)
