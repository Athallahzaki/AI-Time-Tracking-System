from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Optional


class RecognitionState(str, enum.Enum):
    """
    Runtime lifecycle state for recognition associated with a track.
    """

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    RETRY = "RETRY"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class IdentityMatch:
    """
    Result of vector matching against registered identity references.
    """

    identity: Optional[str]
    similarity: float

    @property
    def is_match(self) -> bool:
        return self.identity is not None


@dataclass
class TrackIdentityState:
    """
    Cached recognition state associated with a temporary tracker ID.

    Track ID is a temporary association, not a permanent identity.
    """

    track_id: int

    identity: Optional[str] = None
    similarity: float = 0.0

    state: RecognitionState = RecognitionState.PENDING

    first_recognized_time: Optional[float] = None
    last_attempt_time: float = field(default_factory=time.time)

    retry_count: int = 0
    consecutive_matches: int = 0

    @property
    def is_recognized(self) -> bool:
        return (
            self.state == RecognitionState.CONFIRMED
            and self.identity is not None
        )