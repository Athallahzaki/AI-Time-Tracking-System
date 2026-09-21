from __future__ import annotations

from typing import List, Optional
from ..ports.geometry import BoundingBox
from ..ports.detection import Detection
from ..ports.frame import Frame


class MockDetector:
    """Mock detector for unit tests and headless environments."""

    def __init__(self, predefined_detections: Optional[List[List[Detection]]] = None) -> None:
        self._predefined = predefined_detections or []
        self._call_count = 0

    def warmup(self) -> None:
        pass

    def detect(self, frame: Frame) -> List[Detection]:
        self._call_count += 1
        if self._predefined and (self._call_count - 1) < len(self._predefined):
            return self._predefined[self._call_count - 1]

        # Generate a synthetic moving person detection by default
        h, w = frame.shape[:2]
        x_start = (self._call_count * 10) % max(1, w - 120)
        box = BoundingBox(
            x1=float(x_start),
            y1=50.0,
            x2=float(x_start + 100),
            y2=250.0,
        ).clip(max_width=w, max_height=h)

        return [
            Detection(
                bbox=box,
                confidence=0.92,
                class_id=0,
                class_name="person",
            )
        ]
