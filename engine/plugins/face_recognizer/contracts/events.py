from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional
from ....vision_core.contracts.tracking import Track
from .identity import RecognitionStatus


@dataclass(frozen=True)
class PluginEvent:
    """Base event for face recognition plugin."""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class FaceRecognizedEvent(PluginEvent):
    track_id: int = 0
    employee_id: str = ""
    similarity: float = 0.0
    track: Optional[Track] = None


@dataclass(frozen=True)
class PersonUnknownEvent(PluginEvent):
    track_id: int = 0
    similarity: float = 0.0
    track: Optional[Track] = None


@dataclass(frozen=True)
class IdentityChangedEvent(PluginEvent):
    track_id: int = 0
    old_identity: Optional[str] = None
    new_identity: Optional[str] = None
    similarity: float = 0.0


@dataclass(frozen=True)
class RecognitionExpiredEvent(PluginEvent):
    track_id: int = 0
    identity: str = ""
