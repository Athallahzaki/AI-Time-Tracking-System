from __future__ import annotations

import enum
from dataclasses import dataclass


class RecognitionStatus(str, enum.Enum):
    """Result of a single face-recognition attempt."""

    RECOGNIZED = "RECOGNIZED"
    UNKNOWN = "UNKNOWN"
    NO_FACE = "NO_FACE"
    ERROR = "ERROR"


@dataclass(frozen=True)
class RecognitionResult:
    """
    Result produced by one face-recognition attempt.

    This object represents the recognition result itself,
    not cache or track lifecycle state.
    """

    status: RecognitionStatus
    identity_id: str | None = None
    similarity: float = 0.0

    @property
    def is_recognized(self) -> bool:
        return (
            self.status == RecognitionStatus.RECOGNIZED
            and self.identity_id is not None
        )