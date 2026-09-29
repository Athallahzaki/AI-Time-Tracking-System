import pytest

pytest.importorskip("libreyolo")

from engine.perception.bytetrack_tracker import ByteTrackTracker


@pytest.mark.parametrize("fps", [10, 12, 25, 30])
def test_library_max_time_lost_matches_configured_buffer(fps):
    buffer_frames = fps  # track_buffer_seconds = 1.0
    tracker = ByteTrackTracker(track_buffer=buffer_frames, frame_rate=fps, strict=True)
    cfg = tracker._tracker.cfg if hasattr(tracker._tracker, "cfg") else tracker._tracker.config
    assert int(cfg.track_buffer * cfg.frame_rate / 30) == buffer_frames