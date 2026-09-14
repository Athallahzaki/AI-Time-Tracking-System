import pytest
import numpy as np

from engine.vision_core.sources.mock_source import MockFrameSource
from engine.vision_core.detectors.mock_detector import MockDetector
from engine.vision_core.trackers.iou_tracker import IoUTracker
from engine.vision_core.pipeline.engine import VisionEngine
from engine.vision_core.pipeline.config import VisionCoreConfig
from engine.plugins.face_recognizer.pipeline.plugin import FaceRecognizerPlugin
from engine.plugins.face_recognizer.detector.mock_detector import MockFaceDetector
from engine.plugins.face_recognizer.embedding.mock_embedder import MockFaceEmbedder
from engine.plugins.face_recognizer.matching.matcher import FaceMatcher
from engine.app.attendance_tracker import AttendanceTracker, AttendanceConfig, PresenceStatus


def test_end_to_end_composition_and_execution():
    """
    Tests the complete application graph composed of:
    vision_core (source -> detector -> tracker)
      + plugins.face_recognizer (crop -> detect -> align -> embed -> match -> cache)
      + app.attendance_tracker (presence state machine & timers)
    """
    # 1. Vision Core components
    source = MockFrameSource(width=640, height=480, max_frames=15)
    detector = MockDetector()
    tracker = IoUTracker()
    core_config = VisionCoreConfig(auto_warmup=False)
    engine = VisionEngine(source=source, detector=detector, tracker=tracker, config=core_config)

    # 2. Face Recognizer Plugin
    face_det = MockFaceDetector(return_detection=True)
    face_emb = MockFaceEmbedder(dimension=512)
    matcher = FaceMatcher(threshold=0.30)
    face_plugin = FaceRecognizerPlugin(
        detector=face_det,
        embedder=face_emb,
        matcher=matcher,
    )
    # Register test employee
    dummy_face = np.ones((112, 112, 3), dtype=np.uint8) * 120
    test_vec = face_emb.embed(dummy_face).vector
    face_plugin.repository.register_employee("EMP_007", "James Bond", [test_vec])

    # 3. Attendance Tracker
    attendance_config = AttendanceConfig(min_present_seconds=0.2, warning_minutes=1.0, max_session_minutes=2.0)
    attendance = AttendanceTracker(config=attendance_config)

    # 4. Attach listeners to engine
    engine.add_listener(face_plugin)
    engine.add_listener(attendance)

    # 5. Run execution loop for 15 frames
    engine.start()
    processed_count = 0
    for _ in range(15):
        frame, tracks = engine.step()
        if frame is None:
            break
        processed_count += 1
        assert len(tracks) > 0
        active_track = tracks[0]

        # Verify face recognition plugin decorated track
        assert active_track.attributes.get("identity") == "EMP_007"
        assert active_track.attributes.get("recognition_status") == "RECOGNIZED"

        # Verify attendance tracker decorated track
        assert "presence_status" in active_track.attributes
        assert "session_elapsed" in active_track.attributes

    engine.stop()

    # 6. Verify end metrics and session status
    assert processed_count == 15
    session = attendance.get_session("EMP_007")
    assert session is not None
    assert session.employee_id == "EMP_007"
    assert session.active_track_id == 1
    assert session.status in (PresenceStatus.PASSING, PresenceStatus.CONFIRMED)
