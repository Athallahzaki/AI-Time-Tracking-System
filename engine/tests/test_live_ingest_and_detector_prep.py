"""
Perbaikan jalur live (stream MediaMTX) dan persiapan input detector.

1. Frame yang dibuang decimation tidak pernah dikonversi ke BGR (LazyFrame).
2. `live_buffer: latest`: reader thread menguras stream dan hanya menyimpan
   frame terbaru; pipeline yang lambat melewatkan frame utuh, bukan membuat
   server membuang paket.
3. `pre_resize`: frame diperkecil di engine, kotak dipetakan balik ke koordinat
   frame pada objek Results yang juga dimakan ByteTrack.
4. ByteTrack menerima kotak skor rendah; `detect()` tetap memfilter di
   confidence_threshold.
5. Konfigurasi baru terbaca, divalidasi, dan profil runtime aman untuk RTSP.
"""

from __future__ import annotations

import threading
import time
from fractions import Fraction
from types import SimpleNamespace

import numpy as np
import pytest

from engine.config import EngineConfig, load_config
from engine.config.schema import DetectorConfig, IngestConfig, TrackerConfig
from engine.pipeline.engine import VisionEngine
from engine.tests.test_b4_ingest import FakeAv, FakeContainer, FakeStream, _ticks_at


class CountingFrame:
    """A decoded frame that counts how often it is turned into pixels."""

    conversions = 0

    def __init__(self, pts, width=64, height=48):
        self.pts = pts
        self.width = width
        self.height = height
        self.time = None

    def to_ndarray(self, format="bgr24"):
        CountingFrame.conversions += 1
        return np.zeros((self.height, self.width, 3), dtype=np.uint8)


class CountingContainer(FakeContainer):
    def decode(self, stream):
        for tick in self._stream.pts_ticks:
            yield CountingFrame(tick, stream.width, stream.height)


def _pyav(av, uri, **kwargs):
    from engine.ingest.pyav_source import PyAVSource

    return PyAVSource(uri=uri, av_module=av, **kwargs)


# ---------------------------------------------------------------------------
# 1. Lazy conversion
# ---------------------------------------------------------------------------

def test_decimated_frames_are_never_converted():
    CountingFrame.conversions = 0
    av = FakeAv([CountingContainer(FakeStream(_ticks_at(30.0, 300)))])
    source = _pyav(av, "room.mp4")
    source.start()
    engine = VisionEngine(
        source=source, detector=None, tracker=None,
        config=EngineConfig(source_type="mock", target_fps=12.0),
    )
    kept = []
    while True:
        frame = engine._read_due_frame()
        if frame is None:
            break
        _ = frame.image                      # what the detector would do
        kept.append(frame)
    source.stop()

    assert 115 <= len(kept) <= 125           # 10 s at 12 fps
    assert engine.decimated_frames == 300 - len(kept)
    # The point of the change: one conversion per analysed frame, not per decoded one.
    assert CountingFrame.conversions == len(kept)
    # And the timeline still saw every decoded frame.
    assert source._frame_count == 300


def test_lazy_frame_converts_once_and_keeps_frame_contract():
    from engine.ingest.pyav_source import LazyFrame
    from engine.ports.frame import Frame, FrameMetadata

    calls = []

    def convert():
        calls.append(1)
        return np.ones((4, 6, 3), dtype=np.uint8)

    frame = LazyFrame(FrameMetadata(frame_id=7, pts=1.5), convert)
    assert isinstance(frame, Frame)
    assert frame.is_converted is False
    assert frame.frame_id == 7 and frame.pts == 1.5     # no conversion needed
    assert calls == []
    assert frame.shape == (4, 6, 3)
    assert frame.image is frame.image
    assert calls == [1]

    replaced = np.zeros((2, 2, 3), dtype=np.uint8)
    frame.image = replaced
    assert frame.image is replaced


# ---------------------------------------------------------------------------
# 2. Live reader thread
# ---------------------------------------------------------------------------

class SlowCameraContainer(FakeContainer):
    """Frames arrive at camera rate, like RTSP, not as fast as they are read."""

    def __init__(self, stream, interval):
        super().__init__(stream)
        self._interval = interval

    def decode(self, stream):
        for tick in self._stream.pts_ticks:
            time.sleep(self._interval)
            yield CountingFrame(tick, stream.width, stream.height)


def test_slow_pipeline_skips_whole_frames_instead_of_stalling_the_stream():
    ticks = _ticks_at(100.0, 60)
    av = FakeAv([SlowCameraContainer(FakeStream(ticks), interval=0.005)])
    source = _pyav(av, "rtsp://camera/stream", live_buffer="latest")
    source.start()
    assert source.uses_reader_thread

    taken = []
    while True:
        frame = source.read()
        if frame is None:
            break
        taken.append(frame)
        time.sleep(0.03)                     # a pipeline six times slower than the camera
    described = source.describe()["live_reader"]
    source.stop()

    # Every frame was decoded (the stream was drained at camera rate) ...
    assert source._frame_count == 60
    # ... the pipeline saw far fewer, in order, never twice ...
    assert 3 <= len(taken) < 30
    pts = [frame.metadata.pts for frame in taken]
    assert pts == sorted(pts) and len(set(pts)) == len(pts)
    # ... and the skip is counted, not silent.
    assert described["frames_replaced_before_taken"] > 0
    # Every decoded frame was either handed over or replaced by a newer one.
    assert described["frames_decoded"] == (
        described["frames_taken"] + described["frames_replaced_before_taken"]
    )


def test_reader_thread_reconnects_and_bumps_the_epoch():
    first = SlowCameraContainer(FakeStream([0, 90000]), interval=0.001)
    second = SlowCameraContainer(FakeStream([4_000_000_000, 4_000_090_000]), interval=0.001)
    av = FakeAv([first, second])
    source = _pyav(av, "rtsp://camera/stream", live_buffer="latest",
                   reconnect_attempts=1, reconnect_backoff_seconds=0.0)
    source.start()
    epochs = []
    while True:
        frame = source.read()
        if frame is None:
            break
        epochs.append(frame.metadata.stream_epoch)
        time.sleep(0.01)
    source.stop()

    assert epochs and epochs[-1] == 1
    assert av.opens == 3                     # initial, reconnect, refused retry
    assert first.closed and second.closed    # the reader closed what it opened


def test_stop_ends_a_blocked_read():
    av = FakeAv([SlowCameraContainer(FakeStream(_ticks_at(10.0, 1000)), interval=0.05)])
    source = _pyav(av, "rtsp://camera/stream", live_buffer="latest")
    source.start()
    assert source.read() is not None

    stopper = threading.Timer(0.1, source.stop)
    stopper.start()
    started = time.perf_counter()
    while source.read() is not None:
        pass
    assert time.perf_counter() - started < 5.0
    stopper.join()


def test_files_never_use_the_reader_thread():
    CountingFrame.conversions = 0
    av = FakeAv([CountingContainer(FakeStream(_ticks_at(25.0, 10)))])
    source = _pyav(av, "room.mp4", live_buffer="latest")
    source.start()
    assert source.uses_reader_thread is False
    frames = []
    while True:
        frame = source.read()
        if frame is None:
            break
        frames.append(frame)
    source.stop()
    assert len(frames) == 10                 # a file is pulled, nothing skipped


def test_unknown_live_buffer_is_rejected():
    with pytest.raises(ValueError):
        IngestConfig(live_buffer="ring")
    with pytest.raises(ValueError):
        _pyav(FakeAv([]), "rtsp://x", live_buffer="ring")


# ---------------------------------------------------------------------------
# 3 + 4. Detector input preparation and the low-score floor
# ---------------------------------------------------------------------------

class FakeBoxes:
    def __init__(self, boxes, conf, cls, id=None, orig_shape=None):
        self._boxes, self._conf, self._cls, self._id = boxes, conf, cls, id
        self.orig_shape = orig_shape

    xyxy = property(lambda self: self._boxes)
    conf = property(lambda self: self._conf)
    cls = property(lambda self: self._cls)
    id = property(lambda self: self._id)

    def __len__(self):
        return len(self._boxes)


class FakeModel:
    """Stands in for LibreYOLO: records what it was given, returns fixed boxes."""

    names = {0: "person"}

    def __init__(self, boxes, conf):
        self.calls = []
        self._boxes = np.asarray(boxes, dtype=np.float32)
        self._conf = np.asarray(conf, dtype=np.float32)

    def __call__(self, image, **kwargs):
        self.calls.append((image.shape, kwargs))
        keep = self._conf >= kwargs["conf"]
        return SimpleNamespace(
            boxes=FakeBoxes(self._boxes[keep], self._conf[keep],
                            np.zeros(int(keep.sum()), dtype=np.float32)),
            orig_shape=image.shape[:2],
            names=self.names,
        )


def _detector(model, **kwargs):
    from engine.perception.dfine_detector import DFINEDetector

    detector = DFINEDetector(device="cpu", load_model=False, **kwargs)
    detector._model = model
    return detector


def _frame(height=1080, width=1920):
    from engine.ports.frame import Frame, FrameMetadata

    return Frame(image=np.zeros((height, width, 3), dtype=np.uint8),
                 metadata=FrameMetadata(frame_id=1))


def test_pre_resize_hands_the_model_a_square_and_maps_boxes_back():
    # A box at (64, 64)-(320, 320) on the 640 square is (192, 108)-(960, 540) on 1080p.
    model = FakeModel([[64, 64, 320, 320]], [0.9])
    detector = _detector(model, pre_resize=True, image_size=640)
    detections = detector.detect(_frame())

    shape, kwargs = model.calls[0]
    assert shape == (640, 640, 3)
    assert kwargs["color_format"] == "rgb"
    assert "half" not in kwargs and "verbose" not in kwargs
    bbox = detections[0].bbox
    assert (bbox.x1, bbox.y1, bbox.x2, bbox.y2) == pytest.approx((192, 108, 960, 540))
    # ByteTrack eats last_result: it must be in frame coordinates too.
    native = detector.last_result
    assert native.orig_shape == (1080, 1920)
    assert np.asarray(native.boxes.xyxy)[0] == pytest.approx([192, 108, 960, 540])
    assert native.boxes.orig_shape == (1080, 1920)


def test_pre_resize_leaves_small_frames_to_the_library():
    model = FakeModel([[10, 10, 50, 50]], [0.9])
    detector = _detector(model, pre_resize=True, image_size=640)
    detections = detector.detect(_frame(height=478, width=848))
    shape, kwargs = model.calls[0]
    assert shape == (478, 848, 3) and kwargs["color_format"] == "bgr"
    assert (detections[0].bbox.x1, detections[0].bbox.x2) == pytest.approx((10, 50))


def test_without_pre_resize_the_frame_goes_in_untouched():
    model = FakeModel([[10, 10, 50, 50]], [0.9])
    detector = _detector(model, pre_resize=False)
    detector.detect(_frame())
    assert model.calls[0][0] == (1080, 1920, 3)


def test_bytetrack_gets_low_score_boxes_but_detect_still_filters():
    model = FakeModel([[0, 0, 10, 10], [20, 20, 40, 40], [50, 50, 90, 90]],
                      [0.9, 0.3, 0.12])
    detector = _detector(model, confidence_threshold=0.5, raw_confidence=0.1)
    detections = detector.detect(_frame())

    assert model.calls[0][1]["conf"] == pytest.approx(0.1)
    assert len(detector.last_result.boxes) == 3      # what ByteTrack sees
    assert [round(d.confidence, 2) for d in detections] == [0.9]


def test_raw_confidence_never_exceeds_the_detection_threshold():
    model = FakeModel([[0, 0, 10, 10]], [0.6])
    detector = _detector(model, confidence_threshold=0.5, raw_confidence=0.8)
    assert len(detector.detect(_frame())) == 1
    assert model.calls[0][1]["conf"] == pytest.approx(0.5)


def test_factory_asks_for_the_bytetrack_floor_only_with_bytetrack(monkeypatch):
    from engine import factory, perception

    seen = {}

    class Recorder:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(perception, "DFINEDetector", Recorder)
    base = dict(source_type="video_file", detector=DetectorConfig(pre_resize=True))

    factory.build_detector(EngineConfig(tracker=TrackerConfig(backend="bytetrack"), **base))
    assert seen["raw_confidence"] == pytest.approx(0.1)
    assert seen["pre_resize"] is True

    factory.build_detector(EngineConfig(tracker=TrackerConfig(backend="iou"), **base))
    assert seen["raw_confidence"] is None


# ---------------------------------------------------------------------------
# 5. Config profiles
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["dfine-m.yaml", "dfine-s.yaml", "dfine-m-bytetrack.yaml"])
def test_runtime_profiles_are_safe_for_a_live_stream(name):
    config = load_config(f"engine/config/{name}")
    assert config.ingest.live_buffer == "latest"
    assert config.ingest.reconnect_attempts > 0
    assert config.detector.pre_resize is True
    assert config.target_fps is not None and config.target_fps <= 15


def test_baseline_config_keeps_library_preprocessing():
    config = load_config("engine/config/default_config.yaml")
    assert config.detector.pre_resize is False
    assert config.ingest.live_buffer == "latest"     # network-only; bench files unaffected
