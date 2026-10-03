"""Rincian span detector untuk bench: frame_convert, detector_prepare/infer/post.

Bench 4060 (3 Okt 21:28): span "detector" 58 ms per frame di pipeline, padahal
batch_check (frame sudah ndarray) 14-21 ms. Tanpa rincian, selisih ±40 ms hanya
bisa ditebak. Span "detector" tetap mencakup semuanya agar angka lama sebanding.
"""

from __future__ import annotations

import time

import numpy as np

from engine.config import EngineConfig
from engine.ingest.pyav_source import LazyFrame
from engine.perception import MockDetector, MockTracker
from engine.pipeline.engine import VisionEngine
from engine.ports.frame import FrameMetadata


class Recorder:
    def __init__(self):
        self.spans = []

    def begin_frame(self, camera_id, frame_id, pts):
        pass

    def record_span(self, stage, t_start, t_end, track_uuid=None):
        self.spans.append((stage, t_end - t_start))

    def record_frame(self):
        pass

    def record_drop(self, reason="unspecified"):
        pass


class LazySource:
    def __init__(self, n=3):
        self.n = n
        self.i = 0

    def start(self):
        pass

    def stop(self):
        pass

    def read(self):
        if self.i >= self.n:
            return None
        self.i += 1

        def convert():
            time.sleep(0.005)
            return np.zeros((48, 64, 3), np.uint8)

        meta = FrameMetadata(frame_id=self.i, timestamp=time.time(), source_id="cam", fps=10.0,
                             width=64, height=48, pts=self.i / 10.0)
        return LazyFrame(metadata=meta, convert=convert)

    def __getattr__(self, name):          # atribut sumber lain yang mungkin ditanya engine
        raise AttributeError(name)


class SpanDetector(MockDetector):
    def detect(self, frame):
        assert frame.is_converted, "pipeline wajib mengonversi dulu (span frame_convert)"
        t = time.perf_counter()
        self.last_spans = [("detector_prepare", t, t + 0.001), ("detector_infer", t + 0.001, t + 0.003)]
        return super().detect(frame)


def _run(detector):
    recorder = Recorder()
    engine = VisionEngine(source=LazySource(), detector=detector, tracker=MockTracker(),
                          config=EngineConfig(source_type="mock"), recorder=recorder)
    engine.start()
    while engine.step()[0] is not None:
        pass
    engine.stop()
    return recorder.spans


def test_konversi_dan_sub_span_detector_tercatat():
    spans = _run(SpanDetector())
    names = [name for name, _ in spans]
    assert names.count("frame_convert") == 3 and names.count("detector") == 3
    assert names.count("detector_prepare") == 3 and names.count("detector_infer") == 3
    convert = [d for n, d in spans if n == "frame_convert"]
    detector = [d for n, d in spans if n == "detector"]
    assert all(c >= 0.004 for c in convert)
    assert all(d >= c for d, c in zip(detector, convert)), "span detector tetap mencakup konversi"


def test_detector_tanpa_last_spans_tetap_jalan():
    names = [name for name, _ in _run(MockDetector())]
    assert names.count("detector") == 3 and "detector_infer" not in names
