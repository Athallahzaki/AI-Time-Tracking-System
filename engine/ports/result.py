from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .geometry import BoundingBox


@dataclass(frozen=True)
class TrackResult:
    """
    Public representation of one tracked object.

    The bounding box is always expressed in original frame
    coordinate space.

    Domain-specific information such as face identity is represented
    as optional generic fields so vision_core does not depend on
    a specific plugin.
    """

    track_id: int
    bbox: BoundingBox

    identity_id: str | None = None
    recognition_status: str | None = None
    similarity: float = 0.0


@dataclass(frozen=True)
class EngineResult:
    """
    Public result returned by VisionEngine.process_frame().
    """

    frame_id: int
    timestamp: float
    tracks: List[TrackResult] = field(default_factory=list)