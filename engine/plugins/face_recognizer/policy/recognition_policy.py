from __future__ import annotations

import logging
import time
from typing import Optional

from ....vision_core.contracts.tracking import Track, TrackState
from ..contracts.identity import RecognitionStatus, TrackIdentityState

logger = logging.getLogger(__name__)


class StandardRecognitionPolicy:
    """
    Decoupled policy engine that determines whether a track should undergo face recognition.
    Balances recognition accuracy, computational efficiency, and latency.
    """

    def __init__(
        self,
        min_person_width: int = 40,
        min_person_height: int = 80,
        min_confirmations: int = 2,            # Number of consecutive matches for high confidence
        unknown_retry_interval_sec: float = 1.0,  # Interval between retries for unrecognized person
        max_unknown_retries: int = 5,           # Max rapid retries before backing off
        backoff_retry_interval_sec: float = 5.0,  # Slower retry interval after max rapid retries
        recognition_ttl_sec: float = 60.0,      # TTL after which confirmed identity is refreshed
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
        """
        Evaluates whether face recognition should be executed for this track on the current frame.
        """
        now = current_time if current_time is not None else time.time()

        # 1. Quality / Geometry check: Bounding box must be large enough to contain a face
        if track.bbox.width < self._min_width or track.bbox.height < self._min_height:
            return False

        # 2. If track is newly created or has no state yet -> Recognize immediately
        if state is None or state.status == RecognitionStatus.PENDING:
            return True

        # 3. If track is recognized
        if state.status == RecognitionStatus.RECOGNIZED:
            # If we haven't reached min_confirmations, keep confirming on next frames
            if state.consecutive_matches < self._min_confirmations:
                # Fast confirmation (throttle slightly to 0.1s to allow track to stabilize)
                return (now - state.last_attempt_time) >= 0.1

            # If already confirmed, check if cached state expired (TTL)
            if (now - state.last_attempt_time) >= self._ttl_sec:
                return True

            # Otherwise, use existing cached identity without running inference
            return False

        # 4. If track is UNKNOWN or NO_FACE
        if state.status in (RecognitionStatus.UNKNOWN, RecognitionStatus.NO_FACE):
            time_since_attempt = now - state.last_attempt_time
            if state.retry_count <= self._max_unknown_retries:
                return time_since_attempt >= self._unknown_retry_interval
            else:
                return time_since_attempt >= self._backoff_retry_interval

        return False
