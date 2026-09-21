from __future__ import annotations

from typing import Dict, List, Optional
from ..ports.detection import Detection
from ..ports.tracking import Track, TrackState
from ..ports.frame import Frame


class MockTracker:
    """Mock tracker for unit testing."""

    def __init__(self) -> None:
        self._next_id = 1
        self._tracks: Dict[int, Track] = {}

    def reset(self) -> None:
        self._tracks.clear()
        self._next_id = 1

    def update(self, detections: List[Detection], frame: Frame) -> List[Track]:
        now = frame.timestamp
        current_tracks = []
        for i, det in enumerate(detections):
            tid = i + 1
            if tid in self._tracks:
                track = self._tracks[tid]
                track.bbox = det.bbox
                track.last_seen_timestamp = now
                track.hits += 1
                track.age += 1
                track.state = TrackState.TRACKED
            else:
                track = Track(
                    track_id=tid,
                    bbox=det.bbox,
                    state=TrackState.TRACKED,
                    class_id=det.class_id,
                    class_name=det.class_name,
                    confidence=det.confidence,
                    first_seen_timestamp=now,
                    last_seen_timestamp=now,
                    age=1,
                    hits=1,
                )
                self._tracks[tid] = track
            current_tracks.append(track)
        return current_tracks
