"""Stream kamera dibuka SETELAH detector dimuat dan dipanaskan.

Uji 3 Okt (GTX 1060, `live_buffer: none`): engine membuka RTSP, lalu memuat
D-FINE ±55 dtk tanpa membaca stream. Frame pertama yang dianalisis berumur
±58 dtk dan MediaMTX memutus pembaca yang lambat.
"""

from __future__ import annotations

import dataclasses

from engine import factory
from engine.config import load_config


class _Detector:
    def __init__(self, log):
        self.log = log
        log.append("detector.loaded")

    def warmup(self):
        self.log.append("detector.warmup")

    def detect(self, frame):
        return []


class _Source:
    fps = 25.0

    def __init__(self, log):
        self.log = log

    def start(self):
        self.log.append("source.open")

    def stop(self):
        pass

    def read(self):
        return None


def _config():
    config = load_config("engine/config/dfine-m.yaml")
    return dataclasses.replace(config, source_type="video_file", source_uri="rtsp://127.0.0.1:8554/cam01")


def test_detector_dimuat_dan_dipanaskan_sebelum_stream_dibuka(monkeypatch):
    log = []
    monkeypatch.setattr(factory, "build_detector", lambda config: _Detector(log))
    monkeypatch.setattr(factory, "build_source", lambda config, **kw: _Source(log))
    factory.build_engine(_config(), source_id="cam01")
    assert log.index("detector.loaded") < log.index("source.open")
    assert log.index("detector.warmup") < log.index("source.open")


def test_detector_yang_sudah_ada_tidak_dimuat_ulang(monkeypatch):
    log = []
    existing = _Detector(log)
    log.clear()

    def no_build(config):
        raise AssertionError("detector tidak boleh dimuat ulang saat reconnect / loop file")

    monkeypatch.setattr(factory, "build_detector", no_build)
    monkeypatch.setattr(factory, "build_source", lambda config, **kw: _Source(log))
    engine, _, _ = factory.build_engine(_config(), source_id="cam01", detector=existing)
    assert engine._detector is existing
    assert log == ["source.open"], "detector lama tidak perlu dipanaskan ulang sebelum stream dibuka"
