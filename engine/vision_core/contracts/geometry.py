from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Point:
    """Represents a 2D Cartesian coordinate."""
    x: float
    y: float

    def distance_to(self, other: Point) -> float:
        """Euclidean distance to another point."""
        return math.sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2)


@dataclass(frozen=True)
class BoundingBox:
    """
    Bounding box in frame coordinate space.

    Coordinates:
        - origin: top-left
        - x increases to the right
        - y increases downward
        - format: (x1, y1, x2, y2)

    Contract:
        Bounding boxes exposed by the engine are expressed in the
        original frame coordinate space, never model-internal coordinates.
    """
    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self) -> None:
        if self.x1 > self.x2 or self.y1 > self.y2:
            raise ValueError(
                f"Invalid bounding box dimensions: ({self.x1}, {self.y1}, {self.x2}, {self.y2}). "
                f"Must satisfy x1 <= x2 and y1 <= y2."
            )

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def aspect_ratio(self) -> float:
        """Width / Height ratio."""
        return self.width / max(1e-6, self.height)

    @property
    def center(self) -> Point:
        return Point(
            x=(self.x1 + self.x2) / 2.0,
            y=(self.y1 + self.y2) / 2.0,
        )

    def to_xyxy(self) -> Tuple[float, float, float, float]:
        """Returns (x1, y1, x2, y2) tuple."""
        return (self.x1, self.y1, self.x2, self.y2)

    def to_xywh(self) -> Tuple[float, float, float, float]:
        """Returns (x1, y1, width, height) tuple."""
        return (self.x1, self.y1, self.width, self.height)

    def to_int_xyxy(self) -> Tuple[int, int, int, int]:
        """Returns integer (x1, y1, x2, y2) tuple for OpenCV drawing and cropping."""
        return (int(round(self.x1)), int(round(self.y1)), int(round(self.x2)), int(round(self.y2)))

    def clip(self, max_width: int, max_height: int) -> BoundingBox:
        """Clips bounding box to image boundaries [0, max_width] and [0, max_height]."""
        cx1 = max(0.0, min(float(max_width), self.x1))
        cy1 = max(0.0, min(float(max_height), self.y1))
        cx2 = max(cx1, min(float(max_width), self.x2))
        cy2 = max(cy1, min(float(max_height), self.y2))
        return BoundingBox(x1=cx1, y1=cy1, x2=cx2, y2=cy2)

    def iou(self, other: BoundingBox) -> float:
        """Calculates Intersection over Union (IoU) with another box."""
        inter_x1 = max(self.x1, other.x1)
        inter_y1 = max(self.y1, other.y1)
        inter_x2 = min(self.x2, other.x2)
        inter_y2 = min(self.y2, other.y2)

        inter_w = max(0.0, inter_x2 - inter_x1)
        inter_h = max(0.0, inter_y2 - inter_y1)
        intersection = inter_w * inter_h

        union = self.area + other.area - intersection
        if union <= 0.0:
            return 0.0
        return intersection / union

    def normalized_center_distance(self, other: BoundingBox) -> float:
        """
        Calculates center distance normalized by the average dimension of both boxes.
        More scale-invariant than raw Euclidean pixel distance.
        """
        dist = self.center.distance_to(other.center)
        reference_size = max(1.0, (self.width + self.height + other.width + other.height) / 4.0)
        return dist / reference_size

    def size_similarity(self, other: BoundingBox) -> float:
        """
        Computes scale similarity in range [0.0, 1.0].
        1.0 means identical width and height; lower values indicate scale mismatch.
        """
        w1, h1 = max(1.0, self.width), max(1.0, self.height)
        w2, h2 = max(1.0, other.width), max(1.0, other.height)

        w_sim = min(w1, w2) / max(w1, w2)
        h_sim = min(h1, h2) / max(h1, h2)
        return (w_sim + h_sim) / 2.0
