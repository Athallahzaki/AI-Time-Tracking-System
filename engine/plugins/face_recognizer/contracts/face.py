from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple
import numpy as np
from ....vision_core.contracts.geometry import BoundingBox


@dataclass(frozen=True)
class FaceLandmarks:
    """Five facial landmarks (left_eye, right_eye, nose, left_mouth, right_mouth)."""
    points: np.ndarray  # Shape (5, 2) in float32

    def __post_init__(self) -> None:
        if not isinstance(self.points, np.ndarray):
            raise TypeError("Landmarks points must be a numpy.ndarray.")
        if self.points.shape != (5, 2):
            raise ValueError(f"Expected landmarks shape (5, 2), got {self.points.shape}")

    def to_numpy(self) -> np.ndarray:
        return self.points.copy()


@dataclass(frozen=True)
class FaceDetection:
    """Normalized output from a face detector."""
    bbox: BoundingBox
    confidence: float
    landmarks: FaceLandmarks

    @property
    def width(self) -> float:
        return self.bbox.width

    @property
    def height(self) -> float:
        return self.bbox.height

    @property
    def area(self) -> float:
        return self.bbox.area


@dataclass(frozen=True)
class FaceEmbedding:
    """Normalized facial feature embedding vector."""
    vector: np.ndarray  # 1D float32 vector
    dimension: int = 512

    def __post_init__(self) -> None:
        if self.vector.ndim != 1:
            raise ValueError(f"Embedding vector must be 1D, got {self.vector.ndim}D")
        if self.vector.size != self.dimension:
            raise ValueError(f"Expected {self.dimension}-D embedding, got {self.vector.size}-D")
