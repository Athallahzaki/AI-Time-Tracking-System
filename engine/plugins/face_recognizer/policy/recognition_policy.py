from __future__ import annotations

import time
from typing import Optional

from ....vision_core.contracts.tracking import Track
from ..contracts.identity import RecognitionState, TrackIdentityState


class StandardRecognitionPolicy:
    """
    Determines when face recognition should be executed for a tracked person.

    The policy controls recognition frequency and retry behavior.
    It does not perform recognition itself.
    """

    def __init__(
        self,
        min_person_width: int = 40,
        min_person_height: int = 80,
        min_confirmations: int = 2,
        unknown_retry_interval_sec: float = 1.0,
        max_unknown_retries: int = 5,
        backoff_retry_interval_sec: float = 5.0,
        recognition_ttl_sec: float = 60.0,
    ) -> None:
        self._min_width = min_person_width
        self._min_height = min_person_height
        self._min_confirmations = min_confirmations
        self._unknown_retry_interval = unknown_retry_interval_sec
        self._max_unknown_retries = max_unknown_retries
        self._backoff_retry_interval = backoff_retry_interval_sec
        self._ttl_sec = recognition_ttl_sec

    def should_recognize(
        self,
        track: Track,
        state: Optional[TrackIdentityState],
        current_time: Optional[float] = None,
    ) -> bool:
        now = current_time if current_time is not None else time.time()

        # Recognition is pointless when the person crop is too small.
        if (
            track.bbox.width < self._min_width
            or track.bbox.height < self._min_height
        ):
            return False

        # New track.
        if state is None:
            return True

        # Newly created cache state.
        if state.state == RecognitionState.PENDING:
            return True

        # A successful recognition is re-run only when:
        # 1. confirmation has not reached the configured threshold, or
        # 2. the cached recognition has expired.
        if state.state == RecognitionState.CONFIRMED:
            if state.consecutive_matches < self._min_confirmations:
                return (
                    now - state.last_attempt_time
                ) >= 0.1

            return (
                now - state.last_attempt_time
            ) >= self._ttl_sec

        # Failed recognition attempts use retry/backoff intervals.
        if state.state == RecognitionState.RETRY:
            time_since_attempt = (
                now - state.last_attempt_time
            )

            if state.retry_count <= self._max_unknown_retries:
                return time_since_attempt >= self._unknown_retry_interval

            return time_since_attempt >= self._backoff_retry_interval

        # EXPIRED should immediately trigger a fresh recognition.
        if state.state == RecognitionState.EXPIRED:
            return True

        return False