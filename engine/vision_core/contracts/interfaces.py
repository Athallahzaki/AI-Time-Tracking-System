from __future__ import annotations

from typing import Protocol, Sequence

from .detection import Detection, DetectionBatch
from .frame import Frame
from .tracking import Track


class FrameSource(Protocol):
    """
    Provides frames to the vision engine.
    """

    def read(self) -> Frame | None:
        ...


class ObjectDetector(Protocol):
    """
    Detects objects in a frame.

    Implementations may internally resize, normalize, or otherwise
    preprocess the image, but returned bounding boxes must be expressed
    in the original frame coordinate space.
    """

    def detect(self, frame: Frame) -> DetectionBatch:
        ...


class ObjectTracker(Protocol):
    """
    Maintains object tracks from frame detections.
    """

    def update(
        self,
        detections: DetectionBatch,
        frame: Frame,
    ) -> Sequence[Track]:
        ...


class TrackListener(Protocol):
    """
    Receives updated tracks from the vision pipeline.
    """

    def on_tracks_updated(
        self,
        tracks: Sequence[Track],
        frame: Frame,
    ) -> None:
        ...