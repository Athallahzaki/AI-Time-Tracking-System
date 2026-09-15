from engine.app.engine_service import EngineService
from engine.vision_core.pipeline.config import VisionCoreConfig
from engine.vision_core.pipeline.engine import VisionEngine
from engine.vision_core.detectors.mock_detector import MockDetector
from engine.vision_core.sources.mock_source import MockFrameSource
from engine.vision_core.trackers.iou_tracker import IoUTracker


def test_engine_service_smoke():
    source = MockFrameSource(
        width=640,
        height=480,
        max_frames=3,
    )

    detector = MockDetector()
    tracker = IoUTracker()

    engine = VisionEngine(
        source=source,
        detector=detector,
        tracker=tracker,
        config=VisionCoreConfig(
            auto_warmup=False,
        ),
    )

    service = EngineService(engine)

    print("\n=== ENGINE SMOKE TEST ===")

    print("Initial status:")
    print(service.get_status())

    service.start()

    print("After start:")
    print(service.get_status())

    result = service.process_frame()

    assert result is not None

    print("\nEngineResult:")
    print(f"frame_id : {result.frame_id}")
    print(f"timestamp: {result.timestamp}")
    print(f"tracks   : {len(result.tracks)}")

    for track in result.tracks:
        print(
            f"  track_id={track.track_id}, "
            f"identity={track.identity_id}, "
            f"status={track.recognition_status}, "
            f"similarity={track.similarity:.4f}, "
            f"bbox=({track.bbox.x1}, "
            f"{track.bbox.y1}, "
            f"{track.bbox.x2}, "
            f"{track.bbox.y2})",
        )

    assert len(result.tracks) > 0

    status = service.get_status()

    print("\nCurrent status:")
    print(status)

    assert status.running is True
    assert status.frame_count == 1

    service.stop()

    print("\nAfter stop:")
    print(service.get_status())

    assert service.get_status().running is False

    print("\n=== SMOKE TEST PASSED ===")