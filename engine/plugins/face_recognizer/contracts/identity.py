from __future__ import annotations

import numpy as np

import enum
import time
from dataclasses import dataclass, field
from typing import Optional

from .recognition import RecognitionStatus


class RecognitionState(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    RETRY = "RETRY"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class IdentityMatch:
    identity: Optional[str]
    similarity: float

    @property
    def is_match(self) -> bool:
        return self.identity is not None


@dataclass
class TrackIdentityState:
    track_id: int
    identity: Optional[str] = None
    similarity: float = 0.0
    state: RecognitionState = RecognitionState.PENDING

    first_recognized_time: Optional[float] = None
    last_attempt_time: float = field(default_factory=time.time)

    retry_count: int = 0
    consecutive_matches: int = 0

    last_status: Optional[RecognitionStatus] = None

    @property
    def is_recognized(self) -> bool:
        return (
            self.state == RecognitionState.CONFIRMED
            and self.identity is not None
        )

@dataclass(frozen=True)
class Identity:
    employee_id: str
    name: str
    active: bool = True


@dataclass(frozen=True)
class EnrollmentRequest:
    employee_id: str
    name: str
    images: list[np.ndarray]
    active: bool = True


@dataclass(frozen=True)
class EnrollmentResult:
    employee_id: str
    name: str
    reference_count: int
    active: bool