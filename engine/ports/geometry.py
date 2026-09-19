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


@dataclass(frozen=True)
class NormalizedBox:
    """
    Bounding box in normalized [0, 1] coordinates, relative to frame size.

    This is a BOUNDARY type, not an internal one. It exists because
    ENGINE_PROTOCOL.md §5 requires every bbox on the wire to be normalized
    (the engine sees the mainstream, the browser sees the substream), and
    because `door_region` must not depend on resolution.

    Internal perception and tracking keep using the pixel-space BoundingBox:
    face detection, cropping and the ByteTrack Kalman filter are all
    calibrated in pixels, and normalizing them would silently break the
    motion model.

    Conversion is explicit, in both directions, and covered by a round-trip
    test. Nothing in perception/ or pipeline/ should import this type.
    """

    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self) -> None:
        if self.x1 > self.x2 or self.y1 > self.y2:
            raise ValueError(
                f"Invalid normalized box: ({self.x1}, {self.y1}, {self.x2}, {self.y2}). "
                f"Must satisfy x1 <= x2 and y1 <= y2."
            )
        for name, value in (
            ("x1", self.x1),
            ("y1", self.y1),
            ("x2", self.x2),
            ("y2", self.y2),
        ):
            if not (0.0 <= value <= 1.0):
                raise ValueError(
                    f"Normalized coordinate {name}={value} is outside [0, 1]."
                )

    @classmethod
    def from_pixels(
        cls,
        bbox: BoundingBox,
        frame_width: int,
        frame_height: int,
    ) -> NormalizedBox:
        """Converts a pixel-space box to normalized coordinates."""
        if frame_width <= 0 or frame_height <= 0:
            raise ValueError(
                f"Frame size must be positive, got {frame_width}x{frame_height}."
            )
        clipped = bbox.clip(max_width=frame_width, max_height=frame_height)
        return cls(
            x1=clipped.x1 / frame_width,
            y1=clipped.y1 / frame_height,
            x2=clipped.x2 / frame_width,
            y2=clipped.y2 / frame_height,
        )

    def to_pixels(self, frame_width: int, frame_height: int) -> BoundingBox:
        """Converts back to pixel space for a given frame size."""
        if frame_width <= 0 or frame_height <= 0:
            raise ValueError(
                f"Frame size must be positive, got {frame_width}x{frame_height}."
            )
        return BoundingBox(
            x1=self.x1 * frame_width,
            y1=self.y1 * frame_height,
            x2=self.x2 * frame_width,
            y2=self.y2 * frame_height,
        )

    def to_xyxy(self) -> Tuple[float, float, float, float]:
        return (self.x1, self.y1, self.x2, self.y2)

    def contains_center_of(self, bbox: BoundingBox, frame_width: int, frame_height: int) -> bool:
        """
        True if the centre of a pixel-space box falls inside this region.

        Used for zone labelling (door_region in ARCHITECTURE.md §3.2). Kept here
        rather than in perception/ so that zone logic has exactly one home.
        """
        centre = bbox.center
        nx = centre.x / max(1e-9, float(frame_width))
        ny = centre.y / max(1e-9, float(frame_height))
        return self.x1 <= nx <= self.x2 and self.y1 <= ny <= self.y2
