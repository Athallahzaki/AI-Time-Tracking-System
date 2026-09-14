from __future__ import annotations

from typing import List, Optional, Protocol, Tuple, runtime_checkable
from .detection import Detection
from .frame import Frame
from .tracking import Track


@runtime_checkable
class FrameSource(Protocol):
    """Interface for video ingestion sources (RTSP, webcam, video file, test stream)."""

    def start(self) -> None:
        """Initialize and open the stream."""
        ...

    def read(self) -> Optional[Frame]:
        """
        Fetches the next frame.
        For live streams (RTSP/webcam), must return the most recent frame (drop lag).
        Returns None if stream ends or is disconnected.
        """
        ...

    def stop(self) -> None:
        """Releases underlying resources, threads, and connections."""
        ...

    @property
    def is_running(self) -> bool:
        """Returns True if stream is active and operational."""
        ...

    @property
    def fps(self) -> float:
        """Nominal or measured stream FPS."""
        ...

    @property
    def resolution(self) -> Tuple[int, int]:
        """(width, height) of the video feed."""
        ...


@runtime_checkable
class ObjectDetector(Protocol):
    """Interface for object detectors (YOLO, ONNX, TorchScript, Mock)."""

    def detect(self, frame: Frame) -> List[Detection]:
        """Performs inference on frame and returns normalized Detections."""
        ...

    def warmup(self) -> None:
        """Pre-allocates CUDA/CPU tensors to avoid first-frame latency spikes."""
        ...


@runtime_checkable
class ObjectTracker(Protocol):
    """Interface for multi-object trackers (ByteTrack, BoT-SORT, IoU Tracker, Mock)."""

    def update(self, detections: List[Detection], frame: Frame) -> List[Track]:
        """Associates detections with ongoing tracks and returns updated tracks."""
        ...

    def reset(self) -> None:
        """Clears all active and lost tracks."""
        ...


@runtime_checkable
class TrackListener(Protocol):
    """Interface for consumers/plugins observing tracks produced by the core engine."""

    def on_tracks_updated(self, tracks: List[Track], frame: Frame) -> None:
        """Invoked each cycle when tracks are updated."""
        ...

    def on_track_lost(self, track: Track) -> None:
        """Invoked when a track transition to LOST or REMOVED."""
        ...


@runtime_checkable
class FrameSink(Protocol):
    """Interface for visual outputs, video writers, or streaming sinks."""

    def write(self, frame: Frame, tracks: List[Track]) -> None:
        """Processes or writes the annotated frame."""
        ...

    def close(self) -> None:
        """Closes the sink."""
        ...
