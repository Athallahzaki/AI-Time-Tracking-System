from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List, Optional, Set, Tuple


from ..contracts.recognition import RecognitionStatus


from ..contracts.identity import (
    IdentityMatch,
    RecognitionState,
    TrackIdentityState,
)


logger = logging.getLogger(__name__)


class RecognitionCache:
    """
    Thread-safe cache for recognition state associated with active tracks.

    Track IDs are temporary associations. They must never be treated as
    permanent identity identifiers.
    """

    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self._ttl_seconds = ttl_seconds
        self._states: Dict[int, TrackIdentityState] = {}
        self._lock = threading.RLock()

    def get(self, track_id: int) -> Optional[TrackIdentityState]:
        """Return cached recognition state for a track."""
        with self._lock:
            return self._states.get(track_id)

    def get_or_create(
        self,
        track_id: int,
        current_time: Optional[float] = None,
    ) -> TrackIdentityState:
        """Return existing state or create a new pending state."""
        with self._lock:
            if track_id not in self._states:
                self._states[track_id] = TrackIdentityState(
                    track_id=track_id,
                    state=RecognitionState.PENDING,
                    last_attempt_time=0.0,
                )

            return self._states[track_id]

    def update_with_match(
        self,
        track_id: int,
        match: IdentityMatch,
        current_time: Optional[float] = None,
    ) -> Tuple[TrackIdentityState, bool]:
        """
        Update cached state with the result of identity matching.

        Returns:
            (state, identity_changed)
        """
        now = current_time if current_time is not None else time.time()

        with self._lock:
            state = self.get_or_create(
                track_id,
                current_time=now,
            )

            old_identity = state.identity
            identity_changed = (
                old_identity is not None
                and old_identity != match.identity
            )

            if match.is_match:
                if identity_changed:
                    logger.info(
                        "Identity changed for track %s: %s -> %s",
                        track_id,
                        old_identity,
                        match.identity,
                    )
                    state.consecutive_matches = 1
                else:
                    state.consecutive_matches += 1

                state.identity = match.identity
                state.similarity = match.similarity
                state.state = RecognitionState.CONFIRMED
                state.last_status = RecognitionStatus.RECOGNIZED

                if state.first_recognized_time is None:
                    state.first_recognized_time = now

                state.last_attempt_time = now
                state.retry_count = 0

            else:
                state.similarity = match.similarity
                state.state = RecognitionState.RETRY
                state.last_attempt_time = now
                state.retry_count += 1

                # Preserve an already known identity during a temporary
                # failed recognition attempt.
                if old_identity is None:
                    state.identity = None

            return state, identity_changed

    def record_no_face(
        self,
        track_id: int,
        current_time: Optional[float] = None,
    ) -> TrackIdentityState:
        """Record that no usable face was detected."""
        now = current_time if current_time is not None else time.time()

        with self._lock:
            state = self.get_or_create(
                track_id,
                current_time=now,
            )

            state.state = RecognitionState.RETRY
            state.last_attempt_time = now
            state.retry_count += 1

            return state

    def expire(
        self,
        track_id: int,
        current_time: Optional[float] = None,
    ) -> Optional[TrackIdentityState]:
        """
        Mark a recognized state as expired.

        The state is kept so callers can still inspect the previous identity.
        """
        now = current_time if current_time is not None else time.time()

        with self._lock:
            state = self._states.get(track_id)

            if state is None:
                return None

            if state.state != RecognitionState.CONFIRMED:
                return state

            if state.first_recognized_time is None:
                return state

            if (now - state.last_attempt_time) > self._ttl_seconds:
                state.state = RecognitionState.EXPIRED

            return state

    def is_expired(
        self,
        track_id: int,
        current_time: Optional[float] = None,
    ) -> bool:
        """Return whether the cached recognition has exceeded its TTL."""
        state = self.get(track_id)

        if state is None:
            return True

        if state.state != RecognitionState.CONFIRMED:
            return False

        now = current_time if current_time is not None else time.time()

        if state.first_recognized_time is None:
            return True

        return (now - state.last_attempt_time) > self._ttl_seconds

    def evict(
        self,
        track_id: int,
    ) -> Optional[TrackIdentityState]:
        """Remove state when a track leaves the scene."""
        with self._lock:
            return self._states.pop(track_id, None)

    def cleanup_stale_tracks(
        self,
        active_track_ids: Set[int],
    ) -> List[int]:
        """Remove states belonging to tracks that are no longer active."""
        evicted: List[int] = []

        with self._lock:
            for track_id in list(self._states.keys()):
                if track_id not in active_track_ids:
                    self._states.pop(track_id, None)
                    evicted.append(track_id)

        return evicted

    def clear(self) -> None:
        """Clear all cached recognition states."""
        with self._lock:
            self._states.clear()

    def record_unknown(
        self,
        track_id: int,
        similarity: float = 0.0,
        current_time: Optional[float] = None,
    ) -> TrackIdentityState:
        now = current_time if current_time is not None else time.time()

        with self._lock:
            state = self.get_or_create(
                track_id,
                current_time=now,
            )

            state.state = RecognitionState.RETRY
            state.last_status = RecognitionStatus.UNKNOWN
            state.similarity = similarity
            state.last_attempt_time = now
            state.retry_count += 1

            return state


    def record_no_face(
        self,
        track_id: int,
        current_time: Optional[float] = None,
    ) -> TrackIdentityState:
        now = current_time if current_time is not None else time.time()

        with self._lock:
            state = self.get_or_create(
                track_id,
                current_time=now,
            )

            state.state = RecognitionState.RETRY
            state.last_status = RecognitionStatus.NO_FACE
            state.last_attempt_time = now
            state.retry_count += 1

            return state


    def record_error(
        self,
        track_id: int,
        current_time: Optional[float] = None,
    ) -> TrackIdentityState:
        now = current_time if current_time is not None else time.time()

        with self._lock:
            state = self.get_or_create(
                track_id,
                current_time=now,
            )

            state.state = RecognitionState.RETRY
            state.last_status = RecognitionStatus.ERROR
            state.last_attempt_time = now
            state.retry_count += 1

            return state

    @property
    def size(self) -> int:
        """Number of currently cached track states."""
        with self._lock:
            return len(self._states)