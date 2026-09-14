from __future__ import annotations

from typing import List, Optional
import numpy as np

from ....vision_core.contracts.geometry import BoundingBox
from ..contracts.face import FaceDetection, FaceLandmarks


class MockFaceDetector:
    """Mock face detector for tests and simulations."""

    def __init__(self, return_detection: bool = True) -> None:
        self.return_detection = return_detection

    def detect(self, image: np.ndarray) -> List[FaceDetection]:
        if not self.return_detection or image is None or image.size == 0:
            return []

        h, w = image.shape[:2]
        # Return face roughly in top 40% of the crop
        box = BoundingBox(
            x1=float(w * 0.2),
            y1=float(h * 0.1),
            x2=float(w * 0.8),
            y2=float(h * 0.45),
        )

        # 5 dummy landmarks: left eye, right eye, nose, left mouth, right mouth
        landmarks_pts = np.array(
            [
                [w * 0.35, h * 0.22],
                [w * 0.65, h * 0.22],
                [w * 0.50, h * 0.30],
                [w * 0.38, h * 0.38],
                [w * 0.62, h * 0.38],
            ],
            dtype=np.float32,
        )

        return [
            FaceDetection(
                bbox=box,
                confidence=0.98,
                landmarks=FaceLandmarks(points=landmarks_pts),
            )
        ]
