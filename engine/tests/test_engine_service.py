from engine.app.engine_service import EngineService
from engine.vision_core.detectors.mock_detector import MockDetector
from engine.vision_core.pipeline.config import VisionCoreConfig
from engine.vision_core.pipeline.engine import VisionEngine
from engine.vision_core.sources.mock_source import MockFrameSource
from engine.vision_core.trackers.iou_tracker import IoUTracker


def build_engine(
    max_frames: int = 2,
) -> VisionEngine:
    source = MockFrameSource(
        width=320,
        height=240,
        max_frames=max_frames,
    )

    detector = MockDetector()
    tracker = IoUTracker()

    config = VisionCoreConfig(
        auto_warmup=False,
    )

    return VisionEngine(
        source=source,
        detector=detector,
        tracker=tracker,
        config=config,
    )


def test_engine_service_start_and_stop():
    engine = build_engine()
    service = EngineService(engine)

    assert service.get_status().running is False

    service.start()

    assert service.get_status().running is True

    service.stop()

    assert service.get_status().running is False


def test_engine_service_process_frame_delegates_to_engine():
    engine = build_engine(max_frames=1)
    service = EngineService(engine)

    service.start()

    result = service.process_frame()

    service.stop()

    assert result is not None
    assert result.frame_id == 1
    assert result.timestamp > 0.0
    assert len(result.tracks) > 0


def test_engine_service_returns_backend_result():
    engine = build_engine(max_frames=1)
    service = EngineService(engine)

    service.start()

    result = service.process_frame()

    service.stop()

    assert result is not None

    track = result.tracks[0]

    assert track.track_id == 1
    assert track.bbox.width > 0
    assert track.bbox.height > 0
    assert track.identity_id is None
    assert track.recognition_status is None
    assert track.similarity == 0.0


def test_engine_service_status_reflects_engine_state():
    engine = build_engine(max_frames=1)
    service = EngineService(engine)

    status_before = service.get_status()

    assert status_before.running is False
    assert status_before.frame_count == 0

    service.start()

    service.process_frame()

    status_after = service.get_status()

    service.stop()

    assert status_after.running is True
    assert status_after.frame_count == 1


def test_engine_service_returns_none_when_source_is_exhausted():
    engine = build_engine(max_frames=1)
    service = EngineService(engine)

    service.start()

    first_result = service.process_frame()
    second_result = service.process_frame()

    service.stop()

    assert first_result is not None
    assert second_result is None