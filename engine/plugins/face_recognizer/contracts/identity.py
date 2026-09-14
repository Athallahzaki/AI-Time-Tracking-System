from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Optional


class RecognitionStatus(str, enum.Enum):
    """Lifecycle status of identity recognition for a given track."""
    PENDING = "PENDING"          # Track is new and awaiting initial recognition
    RECOGNIZED = "RECOGNIZED"    # Confirmed matched employee identity
    UNKNOWN = "UNKNOWN"          # Face detected but not matched to any registered employee
    EXPIRED = "EXPIRED"          # Cached identity expired; scheduled for refresh
    NO_FACE = "NO_FACE"          # Person crop did not contain a valid face detection


@dataclass(frozen=True)
class IdentityMatch:
    """Result of vector matching against registered employee references."""
    identity: Optional[str]      # Employee ID or None if unknown
    similarity: float            # Cosine similarity score [-1.0, 1.0]

    @property
    def is_match(self) -> bool:
        return self.identity is not None


@dataclass
class TrackIdentityState:
    """
    Cached recognition state associated with a temporary tracker ID.
    The tracker ID is strictly a temporary association, not permanent identity.
    """
    track_id: int
    identity: Optional[str] = None
    similarity: float = 0.0
    status: RecognitionStatus = RecognitionStatus.PENDING
    first_recognized_time: Optional[float] = None
    last_attempt_time: float = field(default_factory=time.time)
    retry_count: int = 0
    consecutive_matches: int = 0

    @property
    def is_recognized(self) -> bool:
        return self.status == RecognitionStatus.RECOGNIZED and self.identity is not None
