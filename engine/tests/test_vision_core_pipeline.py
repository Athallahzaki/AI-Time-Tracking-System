import pytest
import numpy as np

from engine.vision_core.contracts.geometry import BoundingBox
from engine.vision_core.contracts.detection import Detection
from engine.vision_core.contracts.tracking import TrackState
from engine.vision_core.contracts.frame import Frame, FrameMetadata
from engine.vision_core.sources.mock_source import MockFrameSource
from engine.vision_core.detectors.mock_detector import MockDetector
from engine.vision_core.trackers.iou_tracker import IoUTracker
from engine.vision_core.pipeline.engine import VisionEngine
from engine.vision_core.pipeline.config import VisionCoreConfig

from engine.vision_core.contracts.tracking import (
    Track,
    TrackState,
)


def test_iou_tracker_lifecycle():
    tracker = IoUTracker(min_hits_to_confirm=2, max_missing_frames=2)
    dummy_img = np.zeros((480, 640, 3), dtype=np.uint8)

    # Frame 1: New detection -> TrackState.NEW
    frame1 = Frame(image=dummy_img, metadata=FrameMetadata(frame_id=1, timestamp=100.0))
    det1 = [Detection(bbox=BoundingBox(x1=50, y1=50, x2=100, y2=150), confidence=0.9, class_id=0)]
    tracks1 = tracker.update(det1, frame1)
    assert len(tracks1) == 1
    assert tracks1[0].track_id == 1
    assert tracks1[0].state == TrackState.NEW

    # Frame 2: Matched detection -> TrackState.TRACKED (after 2 hits)
    frame2 = Frame(image=dummy_img, metadata=FrameMetadata(frame_id=2, timestamp=100.033))
    det2 = [Detection(bbox=BoundingBox(x1=52, y1=51, x2=102, y2=151), confidence=0.9, class_id=0)]
    tracks2 = tracker.update(det2, frame2)
    assert len(tracks2) == 1
    assert tracks2[0].track_id == 1
    assert tracks2[0].state == TrackState.TRACKED
    assert tracks2[0].hits == 2

    # Frame 3: Missing detection -> TrackState.LOST
    frame3 = Frame(image=dummy_img, metadata=FrameMetadata(frame_id=3, timestamp=100.066))
    tracks3 = tracker.update([], frame3)
    assert len(tracks3) == 1
    assert tracks3[0].state == TrackState.LOST
    assert tracks3[0].lost_frames == 1

    # Frame 4: Second missing frame -> TrackState.LOST
    frame4 = Frame(image=dummy_img, metadata=FrameMetadata(frame_id=4, timestamp=100.100))
    tracks4 = tracker.update([], frame4)
    assert len(tracks4) == 1
    assert tracks4[0].state == TrackState.LOST
    assert tracks4[0].lost_frames == 2

    # Frame 5: Third missing frame -> exceeds max_missing_frames(2) -> REMOVED & evicted
    frame5 = Frame(image=dummy_img, metadata=FrameMetadata(frame_id=5, timestamp=100.133))
    tracks5 = tracker.update([], frame5)
    assert len(tracks5) == 0


def test_vision_core_standalone_execution():
    """Verifies that vision_core executes completely standalone without any plugins."""
    source = MockFrameSource(width=320, height=240, max_frames=10)
    detector = MockDetector()
    tracker = IoUTracker()
    config = VisionCoreConfig(detection_interval=2, auto_warmup=False)

    engine = VisionEngine(source=source, detector=detector, tracker=tracker, config=config)

    engine.start()
    assert engine.is_running is True

    processed_frames = 0
    while True:
        frame, tracks = engine.step()
        if frame is None:
            break
        processed_frames += 1
        assert len(tracks) > 0
        assert tracks[0].track_id == 1

    engine.stop()
    assert processed_frames == 10
    assert engine.metrics.total_frames == 10
    assert "source_ingest" in engine.metrics.average_latencies
    assert "detector" in engine.metrics.average_latencies
    assert "tracker" in engine.metrics.average_latencies

class RecordingListener:
    def __init__(self):
        self.updated = []
        self.lost = []
        self.removed = []

    def on_tracks_updated(
        self,
        tracks,
        frame,
    ):
        self.updated.append(
            [track.track_id for track in tracks]
        )

    def on_track_lost(
        self,
        track,
    ):
        self.lost.append(
            track.track_id
        )

    def on_track_removed(
        self,
        track,
    ):
        self.removed.append(
            track.track_id
        )


def test_vision_engine_distinguishes_lost_from_removed():
    source = MockFrameSource(
        width=320,
        height=240,
        max_frames=3,
    )

    detector = MockDetector()

    class SequenceTracker:
        def __init__(self):
            self.calls = 0

        def update(
            self,
            detections,
            frame,
        ):
            self.calls += 1

            track = Track(
                track_id=1,
                bbox=BoundingBox(
                    50,
                    50,
                    100,
                    150,
                ),
                state=(
                    TrackState.TRACKED
                    if self.calls == 1
                    else TrackState.LOST
                ),
                first_seen_timestamp=100.0,
                last_seen_timestamp=frame.timestamp,
            )

            return (
                [track]
                if self.calls <= 2
                else []
            )

    tracker = SequenceTracker()
    listener = RecordingListener()

    engine = VisionEngine(
        source=source,
        detector=detector,
        tracker=tracker,
        config=VisionCoreConfig(
            auto_warmup=False,
        ),
    )

    engine.add_listener(listener)
    engine.start()

    frame1, _ = engine.step()
    frame2, _ = engine.step()
    frame3, _ = engine.step()

    engine.stop()

    assert frame1 is not None
    assert frame2 is not None
    assert frame3 is not None

    assert listener.lost == [1]
    assert listener.removed == [1]
