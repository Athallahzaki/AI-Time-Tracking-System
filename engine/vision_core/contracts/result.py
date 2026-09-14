from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .geometry import BoundingBox
from ...plugins.face_recognizer.contracts.recognition import RecognitionStatus


@dataclass(frozen=True)
class TrackResult:
    """
    Public representation of one tracked object.

    Bounding box is always expressed in the original frame coordinate space.
    """

    track_id: int
    bbox: BoundingBox

    identity_id: str | None = None

    recognition_status: RecognitionStatus = RecognitionStatus.NO_FACE
    similarity: float = 0.0


@dataclass(frozen=True)
class EngineResult:
    """
    Public result returned by engine.process_frame().
    """

    frame_id: int
    timestamp: float
    tracks: List[TrackResult] = field(default_factory=list)