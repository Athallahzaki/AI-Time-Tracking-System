from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict
from ..ports.frame import Frame
from ..ports.tracking import Track


@dataclass(frozen=True)
class CoreEvent:
    """Base event emitted by the Vision Engine."""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class EngineStartedEvent(CoreEvent):
    source_id: str = ""


@dataclass(frozen=True)
class EngineStoppedEvent(CoreEvent):
    total_frames: int = 0
    uptime_seconds: float = 0.0


@dataclass(frozen=True)
class TrackCreatedEvent(CoreEvent):
    track: Track = None  # type: ignore


@dataclass(frozen=True)
class TrackUpdatedEvent(CoreEvent):
    track: Track = None  # type: ignore


@dataclass(frozen=True)
class TrackLostEvent(CoreEvent):
    track: Track = None  # type: ignore


@dataclass(frozen=True)
class TrackRemovedEvent(CoreEvent):
    track_id: int = 0
    dwell_time: float = 0.0
