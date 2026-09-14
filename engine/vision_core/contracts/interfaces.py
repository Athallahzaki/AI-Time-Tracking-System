from __future__ import annotations

from typing import List, Optional, Protocol, Sequence, Tuple, runtime_checkable

from .detection import DetectionBatch
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
    Receives track updates and lifecycle transitions from the vision pipeline.
    """

    def on_tracks_updated(
        self,
        tracks: Sequence[Track],
        frame: Frame,
    ) -> None:
        ...

    def on_track_lost(self, track: Track) -> None:
        """
        Called once when a known track transitions into LOST.

        LOST means the tracker temporarily lost the object. The track may
        reappear later with the same ID.
        """
        ...

    def on_track_removed(self, track: Track) -> None:
        """
        Called once when a known track disappears completely from tracker
        output and is considered permanently removed.
        """
        ...


@runtime_checkable
class FrameSink(Protocol):
    """Interface for visual outputs, video writers, or streaming sinks."""

    def write(
        self,
        frame: Frame,
        tracks: List[Track],
    ) -> None:
        """Processes or writes the annotated frame."""
        ...

    def close(self) -> None:
        """Closes the sink."""
        ...