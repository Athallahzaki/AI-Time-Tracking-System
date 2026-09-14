from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class AppEvent:
    """Base event for application business logic."""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class PersonEnteredEvent(AppEvent):
    employee_id: Optional[str] = None
    track_id: int = 0


@dataclass(frozen=True)
class PersonConfirmedEvent(AppEvent):
    employee_id: Optional[str] = None
    track_id: int = 0
    duration_seconds: float = 0.0


@dataclass(frozen=True)
class SessionWarningEvent(AppEvent):
    employee_id: Optional[str] = None
    track_id: int = 0
    duration_minutes: float = 0.0


@dataclass(frozen=True)
class SessionLimitReachedEvent(AppEvent):
    employee_id: Optional[str] = None
    track_id: int = 0
    duration_minutes: float = 0.0


@dataclass(frozen=True)
class PersonDepartedEvent(AppEvent):
    employee_id: Optional[str] = None
    track_id: int = 0
    total_session_seconds: float = 0.0
