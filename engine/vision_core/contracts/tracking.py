from __future__ import annotations

import enum
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple
from .geometry import BoundingBox, Point


# Maximum number of historical centroid points retained per track.
# At 30 fps this covers ~2 seconds of trajectory.
HISTORY_MAXLEN: int = 60


class TrackState(str, enum.Enum):
    """Lifecycle states of a multi-object tracker track."""
    NEW = "NEW"            # Track newly created in current frame
    TRACKED = "TRACKED"    # Track actively confirmed and tracked
    LOST = "LOST"          # Track temporarily lost/occluded
    REMOVED = "REMOVED"    # Track terminated/expired and marked for eviction


@dataclass
class Track:
    """
    Normalized multi-object tracker track state.
    Independent of ByteTrack, BoT-SORT, DeepSORT, or any tracker internal data structures.
    """
    track_id: int
    bbox: BoundingBox
    state: TrackState = TrackState.NEW
    class_id: int = 0
    class_name: str = "person"
    confidence: float = 1.0
    first_seen_timestamp: float = field(default_factory=time.time)
    last_seen_timestamp: float = field(default_factory=time.time)
    age: int = 1               # Total frames since initialization
    hits: int = 1              # Number of matched detection frames
    lost_frames: int = 0       # Consecutive frames lost
    velocity: Tuple[float, float] = (0.0, 0.0)  # (vx, vy) in pixels/second or pixels/frame
    history: Deque[Point] = field(
        default_factory=lambda: deque(maxlen=HISTORY_MAXLEN)
    )  # Bounded ring-buffer of historical centroids
    attributes: Dict[str, Any] = field(default_factory=dict)

    @property
    def dwell_time(self) -> float:
        """Total duration (seconds) since first seen."""
        return max(0.0, self.last_seen_timestamp - self.first_seen_timestamp)

    @property
    def center(self) -> Point:
        return self.bbox.center

    @property
    def is_active(self) -> bool:
        return self.state in (TrackState.NEW, TrackState.TRACKED)

    @property
    def is_confirmed(self) -> bool:
        return self.state == TrackState.TRACKED
