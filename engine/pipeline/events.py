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
    """
    A track the tracker has stopped reporting.

    `exit_zone` was added in B5 and is additive — it defaults to `interior`,
    which is what an unlabelled ending has always implicitly been. It is here
    rather than derived later because by the time anyone handles this event the
    box is gone: the tracker no longer reports the track, so the last position it
    was seen in cannot be recovered. ENGINE_PROTOCOL.md §7 requires every
    `track.ended` to carry an exit zone, and §4.2 is the reason — a track ending
    at the door is a departure, one ending mid-room is a tracking failure, and
    the layer above cannot tell them apart from a track id and a duration.
    """

    track_id: int = 0
    dwell_time: float = 0.0
    exit_zone: str = "interior"
    entry_zone: str = "interior"
    camera_id: str = ""
