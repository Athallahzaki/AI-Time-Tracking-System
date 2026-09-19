"""
Acceptance tests for B0.

These do not test that the engine is *good* — B0 deliberately ports bugs
forward, because the baseline B1 measures has to be the old behaviour. They
test that the port did not change meaning, and that the four zero-effect fixes
that rode along actually hold.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from engine.config import (
    EngineConfig,
    PolicyLeakError,
    TrackerConfig,
    load_config,
    seconds_to_frames,
)
from engine.ports import BoundingBox, NormalizedBox, Track, TrackState

ENGINE_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# Geometry and the boundary type
# --------------------------------------------------------------------------

def test_bounding_box_rejects_inverted_coordinates():
    with pytest.raises(ValueError):
        BoundingBox(x1=10.0, y1=10.0, x2=5.0, y2=20.0)


def test_bounding_box_iou_of_identical_boxes_is_one():
    box = BoundingBox(0.0, 0.0, 10.0, 10.0)
    assert box.iou(box) == pytest.approx(1.0)


def test_normalized_box_round_trip_is_lossless():
    """
    The whole point of keeping two types: conversion must be exact enough that
    nobody is tempted to normalise the tracker's coordinates instead.
    """
    for width, height in ((640, 480), (1920, 1080), (704, 576)):
        original = BoundingBox(x1=12.0, y1=34.0, x2=567.0, y2=400.0).clip(width, height)
        normalized = NormalizedBox.from_pixels(original, width, height)
        restored = normalized.to_pixels(width, height)
        assert restored.x1 == pytest.approx(original.x1)
        assert restored.y1 == pytest.approx(original.y1)
        assert restored.x2 == pytest.approx(original.x2)
        assert restored.y2 == pytest.approx(original.y2)


def test_normalized_box_is_resolution_independent():
    """
    A door_region defined once must mean the same region whether the engine
    reads the mainstream or the browser draws on the substream.
    ENGINE_PROTOCOL.md §5.
    """
    door = NormalizedBox(0.62, 0.10, 0.95, 0.55)
    main = door.to_pixels(1920, 1080)
    sub = door.to_pixels(640, 360)
    assert main.width / 1920 == pytest.approx(sub.width / 640)
    assert main.height / 1080 == pytest.approx(sub.height / 360)


def test_normalized_box_rejects_out_of_range():
    with pytest.raises(ValueError):
        NormalizedBox(0.0, 0.0, 1.2, 0.5)


def test_zone_membership_uses_box_centre():
    door = NormalizedBox(0.5, 0.0, 1.0, 1.0)
    inside = BoundingBox(600.0, 100.0, 700.0, 300.0)
    outside = BoundingBox(10.0, 100.0, 110.0, 300.0)
    assert door.contains_center_of(inside, 1000, 1000) is True
    assert door.contains_center_of(outside, 1000, 1000) is False


# --------------------------------------------------------------------------
# Zero-effect fix 1: crop returns a copy, not a view
# --------------------------------------------------------------------------

def test_person_crop_does_not_alias_the_frame_buffer():
    """
    ARCHITECTURE.md §9 item 10. A view into the capture buffer is harmless
    while everything is synchronous and silently corrupting the moment a crop
    is queued. This test fails against the pre-B0 code.
    """
    from engine.perception import BoundingBoxPersonCropper

    frame_buffer = np.full((100, 100, 3), 7, dtype=np.uint8)
    track = Track(track_id=1, bbox=BoundingBox(10.0, 10.0, 50.0, 50.0))

    crop = BoundingBoxPersonCropper().crop(frame_buffer, track)
    assert crop is not None

    # Simulate the capture thread overwriting the buffer before a worker reads
    # the crop it was handed.
    frame_buffer[:] = 200

    assert crop.max() == 7, "crop aliases the frame buffer — it is a view, not a copy"


# --------------------------------------------------------------------------
# Zero-effect fix 2: temporal constants are seconds, converted with real fps
# --------------------------------------------------------------------------

def test_seconds_to_frames_is_identity_at_the_old_hardcoded_rate():
    """
    The old code hardcoded track_buffer=30 frames at frame_rate=30. Expressing
    it as 1.0 second must reproduce exactly that at 30 fps — otherwise the
    conversion is not behaviour-preserving and does not belong in B0.
    """
    assert seconds_to_frames(1.0, fps=30.0) == 30


def test_seconds_to_frames_tracks_the_frame_rate():
    tracker = TrackerConfig(track_buffer_seconds=1.0)
    assert tracker.track_buffer_frames(30.0) == 30
    assert tracker.track_buffer_frames(10.0) == 10


def test_seconds_to_frames_never_returns_zero():
    assert seconds_to_frames(0.01, fps=10.0) == 1


def test_effective_fps_caps_but_never_raises():
    config = EngineConfig(target_fps=10.0)
    assert config.effective_fps(30.0) == 10.0
    assert config.effective_fps(5.0) == 5.0


# --------------------------------------------------------------------------
# Zero-effect fix 3: strict mode, no silent degradation
# --------------------------------------------------------------------------

def test_strict_tracker_refuses_to_swap_backend_silently(monkeypatch):
    """
    Falling back from ByteTrack to IoUTracker without failing means a benchmark
    silently measures a different tracker and still reports tidy numbers.
    Same family as ARCHITECTURE.md §9 item 9.
    """
    from engine.perception import ByteTrackTracker

    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

    def deny_ultralytics(name, *args, **kwargs):
        if name.startswith("ultralytics"):
            raise ImportError("ultralytics is not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", deny_ultralytics)

    with pytest.raises(RuntimeError, match="bytetrack"):
        ByteTrackTracker(strict=True)


def test_non_strict_tracker_still_falls_back(monkeypatch):
    """Opting out must remain possible — it just has to be explicit."""
    from engine.perception import ByteTrackTracker

    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

    def deny_ultralytics(name, *args, **kwargs):
        if name.startswith("ultralytics"):
            raise ImportError("ultralytics is not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", deny_ultralytics)

    tracker = ByteTrackTracker(strict=False)
    assert tracker is not None


def test_unknown_tracker_backend_is_rejected():
    with pytest.raises(ValueError, match="Unknown tracker backend"):
        TrackerConfig(backend="deepsort")


# --------------------------------------------------------------------------
# The boundary: no company policy in the engine
# --------------------------------------------------------------------------

def test_shipped_config_loads_and_carries_no_policy():
    config = load_config()
    assert config.detection_interval >= 1
    assert config.tracker.backend in ("bytetrack", "iou")


def test_config_with_attendance_block_is_rejected(tmp_path):
    """
    The old configs/default_config.yaml had break_start_hour: 12 and
    max_session_minutes: 30. Porting it verbatim would put company policy back
    inside the engine. ARCHITECTURE.md §16.
    """
    leaky = tmp_path / "leaky.yaml"
    leaky.write_text(
        "core:\n"
        "  source_uri: '0'\n"
        "attendance:\n"
        "  max_session_minutes: 30.0\n"
        "  break_start_hour: 12\n",
        encoding="utf-8",
    )
    with pytest.raises(PolicyLeakError, match="attendance"):
        load_config(leaky)


def test_no_policy_constants_in_engine_source():
    """
    The cheap grep from ARCHITECTURE.md §16, run against our own tree so the
    check exists even before CI wires up contracts/tools/policy_grep.py.
    """
    forbidden = ("break_start_hour", "break_end_hour", "max_session_minutes", "warning_minutes")
    offenders = []
    for path in ENGINE_ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            # config/loader.py names these in order to reject them.
            if needle in text and "FORBIDDEN" not in text:
                offenders.append(f"{path.name}:{needle}")
    assert not offenders, f"policy constants found in engine/: {offenders}"


def test_engine_never_imports_the_backend():
    """ARCHITECTURE.md §6.8. Ten lines, catches every violation."""
    offenders = []
    for path in ENGINE_ROOT.rglob("*.py"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("import backend", "from backend")):
                offenders.append(f"{path.name}:{lineno}")
    assert not offenders, f"engine imports backend in: {offenders}"


# --------------------------------------------------------------------------
# The pipeline still runs
# --------------------------------------------------------------------------

def test_pipeline_produces_tracks_on_mocks():
    from engine.ingest import MockFrameSource
    from engine.perception import MockDetector, MockTracker
    from engine.pipeline.engine import VisionEngine

    engine = VisionEngine(
        source=MockFrameSource(max_frames=10),
        detector=MockDetector(),
        tracker=MockTracker(),
        config=EngineConfig(source_type="mock"),
    )
    engine.start()

    frames, track_ids = 0, set()
    while True:
        frame, tracks = engine.step()
        if frame is None:
            break
        frames += 1
        track_ids.update(t.track_id for t in tracks)
    engine.stop()

    assert frames == 10
    assert track_ids


def test_track_lifecycle_events_fire_once_per_transition():
    from engine.ingest import MockFrameSource
    from engine.perception import MockDetector, MockTracker
    from engine.pipeline.engine import VisionEngine
    from engine.pipeline.events import TrackCreatedEvent

    created = []

    engine = VisionEngine(
        source=MockFrameSource(max_frames=5),
        detector=MockDetector(),
        tracker=MockTracker(),
        config=EngineConfig(source_type="mock"),
    )
    engine.add_event_handler(
        lambda event: created.append(event) if isinstance(event, TrackCreatedEvent) else None
    )
    engine.start()
    while engine.step()[0] is not None:
        pass
    engine.stop()

    assert len(created) == 1, "a track must be announced once, not once per frame"


def test_mock_path_needs_neither_torch_nor_ultralytics():
    """
    The mock path is what lets B1's benchmark run in CI. If importing the
    pipeline drags in torch, that stops being true.
    """
    script = (
        "import sys;"
        "import engine.ingest, engine.perception, engine.pipeline.engine;"
        "from engine.perception import MockDetector, MockTracker;"
        "assert 'torch' not in sys.modules, 'torch imported eagerly';"
        "assert 'ultralytics' not in sys.modules, 'ultralytics imported eagerly';"
        "print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ENGINE_ROOT.parent,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


# --------------------------------------------------------------------------
# The bug that must NOT be fixed yet
# --------------------------------------------------------------------------

def test_stale_detection_bug_is_still_present():
    """
    ARCHITECTURE.md §9 item 7: when a frame is skipped, the engine feeds the
    tracker detections from an older frame instead of letting it predict.

    This test asserts the BUG, on purpose. B0's baseline must be the old
    behaviour, and step 5 is where it gets fixed — at which point this test is
    inverted and the benchmark shows what changed. If it starts failing during
    B0, someone fixed something they were not supposed to fix yet.
    """
    from engine.ingest import MockFrameSource
    from engine.perception import MockDetector
    from engine.pipeline.engine import VisionEngine

    seen_batches = []

    class RecordingTracker:
        def update(self, detections, frame):
            seen_batches.append([d.bbox.to_xyxy() for d in detections])
            return []

    engine = VisionEngine(
        source=MockFrameSource(max_frames=4),
        detector=MockDetector(),
        tracker=RecordingTracker(),
        config=EngineConfig(source_type="mock", detection_interval=2),
    )
    engine.start()
    while engine.step()[0] is not None:
        pass
    engine.stop()

    assert len(seen_batches) == 4
    # Frames where detection was skipped receive the previous frame's boxes.
    assert seen_batches[1] == seen_batches[2], (
        "stale-detection behaviour changed during B0 — the baseline is no "
        "longer the old engine. Fix belongs to step 5, not here."
    )


# --------------------------------------------------------------------------
# Regressions found when B0 first met real hardware
# --------------------------------------------------------------------------

def test_tracker_is_configured_from_the_file_not_the_placeholder_fps():
    """
    VideoFileSource sets self._fps = 30.0 in __init__ and only learns the real
    rate in start(). Reading fps before opening the file configures every
    seconds-based constant against 30 fps whatever the source actually is —
    which defeats the point of expressing them in seconds at all.

    Found on a 24.8 fps file that produced "track_buffer 1.00s -> 30 frames at
    30.0 fps".
    """
    from engine.tools.run import build_tracker
    from engine.ingest import VideoFileSource

    clip = ENGINE_ROOT / "samples" / "synthetic_24fps.mp4"
    source = VideoFileSource(filepath=str(clip), realtime_pacing=False)

    assert source.fps == 30.0, "placeholder assumption changed; this test is stale"
    source.start()
    assert source.fps == pytest.approx(24.0, rel=0.05)

    config = EngineConfig(
        source_type="video_file",
        tracker=TrackerConfig(backend="iou", track_buffer_seconds=1.0),
    )
    tracker = build_tracker(config, source_fps=source.fps)
    source.stop()

    assert tracker._max_missing_frames == 24, (
        "tracker buffer was derived from the placeholder fps, not the file"
    )


def test_short_read_is_an_error_not_a_finished_run(tmp_path, monkeypatch):
    """
    cv2.VideoCapture.read() returns None both at end-of-stream and on a decode
    failure, and VideoFileSource logs both as "Reached end of video". A run that
    covers 6% of a file must not be reported as a completed run — every number
    derived from it would describe a fraction of the source.
    """
    from engine.tools import run as run_module

    class TruncatedSource:
        total_frames = 100
        fps = 30.0
        is_running = True

        def __init__(self):
            self._n = 0

        def start(self):
            return None

        def stop(self):
            self.is_running = False

        def read(self):
            self._n += 1
            if self._n > 5:       # decoder gives up at 5%
                return None
            from engine.ports import Frame, FrameMetadata

            return Frame(
                image=np.zeros((48, 64, 3), dtype=np.uint8),
                metadata=FrameMetadata(frame_id=self._n, width=64, height=48),
            )

    source = TruncatedSource()

    def fake_build_engine(config, max_frames=None):
        from engine.perception import MockDetector, MockTracker
        from engine.pipeline.engine import VisionEngine

        return (
            VisionEngine(
                source=source,
                detector=MockDetector(),
                tracker=MockTracker(),
                config=config,
            ),
            source,
        )

    monkeypatch.setattr("engine.tools.run.build_engine", fake_build_engine)

    with pytest.raises(RuntimeError, match="decode failure"):
        run_module.main(["--quiet"])


# --------------------------------------------------------------------------
# Regression: the builder must never invent an fps
# --------------------------------------------------------------------------

def test_builder_reads_fps_only_from_an_opened_source(tmp_path):
    """
    VideoFileSource reports 30.0 until cv2 has opened the file. A builder that
    reads .fps before start() gets that placeholder, and every seconds-to-frames
    conversion downstream is quietly miscalibrated — reintroducing the very
    hardcoded frame_rate=30 this step removes.

    Found on real hardware: a 24.8 fps recording logged "30 frames at 30.0 fps".
    """
    from engine.ingest.video_file import VideoFileSource

    unopened = VideoFileSource(filepath="does-not-matter.mp4")
    assert unopened.fps == 30.0, "placeholder changed; this test needs updating"
    assert unopened.is_running is False, (
        "a source that has not been started must not be trusted for its fps"
    )


def test_source_with_unknown_fps_is_refused_not_guessed():
    from engine.config import EngineConfig
    from engine.tools.run import build_engine

    class FpsLessSource:
        fps = 0.0
        is_running = False

        def start(self):
            self.is_running = True

        def read(self):
            return None

        def stop(self):
            self.is_running = False

    import engine.tools.run as run_module

    original = run_module.build_source
    run_module.build_source = lambda config, max_frames=None: FpsLessSource()
    try:
        with pytest.raises(RuntimeError, match="fps"):
            build_engine(EngineConfig(source_type="video_file"))
    finally:
        run_module.build_source = original
