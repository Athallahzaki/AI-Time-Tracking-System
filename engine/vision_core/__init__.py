"""
vision_core: A fully generic, reusable Computer Vision engine package
for video ingestion, object detection, and multi-object tracking.
Has zero dependencies on face recognition or specific application business logic.
"""

from .contracts import (
    Point,
    BoundingBox,
    Frame,
    FrameMetadata,
    Detection,
    DetectionBatch,
    Track,
    TrackState,
    FrameSource,
    ObjectDetector,
    ObjectTracker,
    TrackListener,
    FrameSink,
)
from .sources import (
    BaseFrameSource,
    OpenCVStreamSource,
    VideoFileSource,
    MockFrameSource,
)
from .detectors import (
    YOLODetector,
    MockDetector,
)
from .trackers import (
    IoUTracker,
    ByteTrackTracker,
    MockTracker,
)
from .metrics import PerformanceMetrics
from .pipeline import (
    VisionCoreConfig,
    VisionEngine,
    CoreEvent,
    EngineStartedEvent,
    EngineStoppedEvent,
    TrackCreatedEvent,
    TrackUpdatedEvent,
    TrackLostEvent,
    TrackRemovedEvent,
)

__all__ = [
    # Contracts
    "Point",
    "BoundingBox",
    "Frame",
    "FrameMetadata",
    "Detection",
    "DetectionBatch",
    "Track",
    "TrackState",
    "FrameSource",
    "ObjectDetector",
    "ObjectTracker",
    "TrackListener",
    "FrameSink",
    # Sources
    "BaseFrameSource",
    "OpenCVStreamSource",
    "VideoFileSource",
    "MockFrameSource",
    # Detectors
    "YOLODetector",
    "MockDetector",
    # Trackers
    "IoUTracker",
    "ByteTrackTracker",
    "MockTracker",
    # Metrics
    "PerformanceMetrics",
    # Pipeline
    "VisionCoreConfig",
    "VisionEngine",
    "CoreEvent",
    "EngineStartedEvent",
    "EngineStoppedEvent",
    "TrackCreatedEvent",
    "TrackUpdatedEvent",
    "TrackLostEvent",
    "TrackRemovedEvent",
]
