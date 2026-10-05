"""detector.swscale_resize: YUV -> RGB 640 langsung, tanpa BGR 1080p.

Bench 4060 (3 Okt 21:41): frame_convert ±16 ms + detector_prepare ±5 ms per
frame hanya untuk menghasilkan RGB 640x640 yang ujungnya diberikan ke model.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import numpy as np
import pytest

from engine.config import EngineConfig
from engine.ingest.pyav_source import LazyFrame
from engine.perception import MockDetector, MockTracker
from engine.perception.dfine_detector import DFINEDetector, Prepared
from engine.pipeline.engine import VisionEngine
from engine.ports.frame import Frame, FrameMetadata, frame_hw
from engine.tools.scaling_check import ScalingReport, format_report, run


def _meta(width=1920, height=1080, frame_id=1):
    return FrameMetadata(frame_id=frame_id, timestamp=time.time(), source_id="cam", fps=10.0,
                         width=width, height=height, pts=frame_id / 10.0)


class Counter:
    def __init__(self):
        self.convert = 0
        self.scale = []

    def lazy(self, width=1920, height=1080, frame_id=1, scalable=True):
        def convert():
            self.convert += 1
            return np.full((height, width, 3), 7, np.uint8)

        def scale(w, h):
            self.scale.append((w, h))
            return np.full((h, w, 3), 9, np.uint8)

        return LazyFrame(metadata=_meta(width, height, frame_id), convert=convert,
                         scale=scale if scalable else None)


class Model:
    names = {0: "person"}

    def __init__(self):
        self.inputs = []

    def __call__(self, image, **kwargs):
        self.inputs.append((image, kwargs.get("color_format")))
        return SimpleNamespace(boxes=None)


def _detector(**kwargs):
    kwargs.setdefault("pre_resize", True)
    detector = DFINEDetector(device="cpu", load_model=False, image_size=640, **kwargs)
    detector._model = Model()
    return detector


# -- LazyFrame ---------------------------------------------------------------

def test_scaled_rgb_tidak_mengonversi_dan_di_cache():
    counter = Counter()
    frame = counter.lazy()
    first = frame.scaled_rgb(640, 640)
    second = frame.scaled_rgb(640, 640)
    assert first is second and first.shape == (640, 640, 3)
    assert counter.scale == [(640, 640)]
    assert counter.convert == 0 and not frame.is_converted


def test_scaled_rgb_tanpa_scaler_none():
    frame = Counter().lazy(scalable=False)
    assert frame.scaled_rgb(640, 640) is None


def test_frame_hw_dari_metadata_tanpa_konversi():
    counter = Counter()
    frame = counter.lazy(width=1280, height=720)
    assert frame_hw(frame) == (720, 1280)
    assert counter.convert == 0
    plain = Frame(image=np.zeros((10, 20, 3), np.uint8),
                  metadata=FrameMetadata(frame_id=1, timestamp=0.0, source_id="x"))
    assert frame_hw(plain) == (10, 20)


# -- DFINEDetector.frame_input -------------------------------------------------

def test_swscale_dipakai_untuk_frame_lazy():
    counter = Counter()
    detector = _detector(swscale_resize=True)
    assert detector.wants_lazy_frames
    prepared = detector.frame_input(counter.lazy())
    assert isinstance(prepared, Prepared) and prepared.colour_format == "rgb"
    assert prepared.model_input.shape == (640, 640, 3)
    assert prepared.scale == (1920 / 640, 1080 / 640, 1080, 1920)
    assert counter.convert == 0 and counter.scale == [(640, 640)]


def test_swscale_mati_jalur_lama():
    counter = Counter()
    detector = _detector()
    assert not detector.wants_lazy_frames
    prepared = detector.frame_input(counter.lazy())
    assert counter.convert == 1 and counter.scale == []
    assert prepared.colour_format == "rgb" and prepared.model_input.shape == (640, 640, 3)


def test_swscale_butuh_pre_resize():
    detector = _detector(swscale_resize=True, pre_resize=False)
    assert not detector.wants_lazy_frames


@pytest.mark.parametrize("case", ["sudah-dikonversi", "lebih-kecil", "tanpa-scaler"])
def test_swscale_jatuh_ke_jalur_lama(case):
    counter = Counter()
    detector = _detector(swscale_resize=True)
    if case == "sudah-dikonversi":
        frame = counter.lazy()
        frame.image                                  # misal sudah dipakai pengenalan wajah
    elif case == "lebih-kecil":
        frame = counter.lazy(width=480, height=360)  # upscaling: biarkan LibreYOLO
    else:
        frame = counter.lazy(scalable=False)
    detector.frame_input(frame)
    assert counter.scale == []


def test_predict_dengan_frame_memakai_swscale_dan_rgb():
    counter = Counter()
    detector = _detector(swscale_resize=True)
    detector._predict(counter.lazy())
    image, colour = detector._model.inputs[-1]
    assert image.shape == (640, 640, 3) and colour == "rgb"
    assert counter.convert == 0
    assert [name for name, *_ in detector.last_spans] == ["detector_prepare", "detector_infer"]


# -- pipeline ----------------------------------------------------------------

class Recorder:
    def __init__(self):
        self.spans = []

    def begin_frame(self, camera_id, frame_id, pts):
        pass

    def record_span(self, stage, t_start, t_end, track_uuid=None):
        self.spans.append(stage)

    def record_frame(self):
        pass

    def record_drop(self, reason="unspecified"):
        pass


class LazySource:
    def __init__(self, counter, n=3):
        self.counter = counter
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
        return self.counter.lazy(width=64, height=48, frame_id=self.i)

    def __getattr__(self, name):
        raise AttributeError(name)


class LazyDetector(MockDetector):
    wants_lazy_frames = True

    def detect(self, frame):
        frame.scaled_rgb(32, 32)
        return super().detect(frame)


def test_pipeline_tidak_memaksa_konversi_bila_detector_minta_frame_lazy():
    counter = Counter()
    recorder = Recorder()
    engine = VisionEngine(source=LazySource(counter), detector=LazyDetector(), tracker=MockTracker(),
                          config=EngineConfig(source_type="mock"), recorder=recorder)
    engine.start()
    while engine.step()[0] is not None:
        pass
    engine.stop()
    assert "frame_convert" not in recorder.spans
    assert recorder.spans.count("detector") == 3
    assert len(counter.scale) == 3


# -- scaling_check -------------------------------------------------------------

class Box:
    def __init__(self, xyxy, conf):
        self.xyxy = np.array([xyxy], np.float32)
        self.conf = np.array([conf], np.float32)
        self.cls = np.array([0], np.float32)


def test_scaling_check_deteksi_sama_layak():
    counter = Counter()
    detector = _detector(swscale_resize=False, confidence_threshold=0.5)
    frames = [counter.lazy(frame_id=i) for i in range(3)]
    report = run(detector, frames)
    assert report.frames == 3 and report.mismatched == 0
    assert report.pixel_mean_abs_diff == pytest.approx(2.0)   # 9 (swscale) vs 7 (OpenCV)
    assert len(detector._model.inputs) == 6
    text = format_report(report)
    assert "KESIMPULAN" in text


def test_vonis_scaling():
    same = ScalingReport(frames=10, opencv_ms=21.0, swscale_ms=4.0, threshold=0.5)
    assert "layak dipakai" in same.verdict
    tiny = ScalingReport(frames=10, opencv_ms=4.5, swscale_ms=4.0, threshold=0.5)
    assert "tidak perlu" in tiny.verdict
    changed = ScalingReport(frames=10, opencv_ms=21.0, swscale_ms=4.0, mismatched=2, threshold=0.5)
    assert "DETEKSI BERUBAH di 2/10" in changed.verdict
