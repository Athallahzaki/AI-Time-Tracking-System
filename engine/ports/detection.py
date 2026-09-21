from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List
from .geometry import BoundingBox


@dataclass(frozen=True)
class Detection:
    """
    Normalized, framework-agnostic object detection representation.
    Decouples D-FINE or any future model output from downstream tracking/analytics.
    """
    bbox: BoundingBox
    confidence: float
    class_id: int
    class_name: str = "person"
    attributes: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {self.confidence}")


@dataclass(frozen=True)
class DetectionBatch:
    """Batch of detections for a given frame."""
    frame_id: int
    detections: List[Detection] = field(default_factory=list)

    def filter_by_class(self, class_name: str) -> List[Detection]:
        """Returns detections matching a specific class name."""
        return [d for d in self.detections if d.class_name == class_name]

    def filter_by_confidence(self, min_confidence: float) -> List[Detection]:
        """Returns detections meeting minimum confidence threshold."""
        return [d for d in self.detections if d.confidence >= min_confidence]
