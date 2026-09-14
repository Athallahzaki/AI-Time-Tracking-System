from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List, Optional, Set, Tuple

from ..contracts.identity import IdentityMatch, RecognitionStatus, TrackIdentityState

logger = logging.getLogger(__name__)


class RecognitionCache:
    """
    Thread-safe state cache storing recognition associations for active tracks.
    Ensures heavy face recognition models are not run on every frame.
    Enforces that tracker IDs are temporary and handles retries, expiration, and eviction.
    """

    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self._ttl_seconds = ttl_seconds
        self._states: Dict[int, TrackIdentityState] = {}
        self._lock = threading.RLock()

    def get(self, track_id: int) -> Optional[TrackIdentityState]:
        """Retrieves recognition state for a given track_id."""
        with self._lock:
            return self._states.get(track_id)

    def get_or_create(self, track_id: int, current_time: Optional[float] = None) -> TrackIdentityState:
        """Gets existing state or initializes a new PENDING state."""
        now = current_time if current_time is not None else time.time()
        with self._lock:
            if track_id not in self._states:
                self._states[track_id] = TrackIdentityState(
                    track_id=track_id,
                    status=RecognitionStatus.PENDING,
                    last_attempt_time=0.0,  # Force immediate eligibility
                )
            return self._states[track_id]

    def update_with_match(
        self,
        track_id: int,
        match: IdentityMatch,
        current_time: Optional[float] = None,
    ) -> Tuple[TrackIdentityState, bool]:
        """
        Updates cache with the outcome of an identity match.
        Returns (state, identity_changed).
        """
        now = current_time if current_time is not None else time.time()
        with self._lock:
            state = self.get_or_create(track_id, current_time=now)
            old_identity = state.identity
            identity_changed = False

            if match.is_match:
                if old_identity is not None and old_identity != match.identity:
                    logger.info(
                        f"[Cache] Track #{track_id} identity changed from '{old_identity}' "
                        f"to '{match.identity}' (sim: {match.similarity:.3f})"
                    )
                    identity_changed = True
                    state.consecutive_matches = 1
                else:
                    state.consecutive_matches += 1

                state.identity = match.identity
                state.similarity = match.similarity
                state.status = RecognitionStatus.RECOGNIZED
                if state.first_recognized_time is None:
                    state.first_recognized_time = now
                state.last_attempt_time = now
                state.retry_count = 0
            else:
                # Unrecognized
                state.similarity = match.similarity
                state.status = RecognitionStatus.UNKNOWN
                state.last_attempt_time = now
                state.retry_count += 1
                # If previously recognized person was not matched, don't immediately wipe if similarity is close
                if old_identity is not None:
                    # Keep identity if it was already confirmed, but note retry
                    pass
                else:
                    state.identity = None

            return state, identity_changed

    def record_no_face(self, track_id: int, current_time: Optional[float] = None) -> TrackIdentityState:
        """Records that face detection failed on this person crop."""
        now = current_time if current_time is not None else time.time()
        with self._lock:
            state = self.get_or_create(track_id, current_time=now)
            state.status = RecognitionStatus.NO_FACE if not state.identity else state.status
            state.last_attempt_time = now
            state.retry_count += 1
            return state

    def is_expired(self, track_id: int, current_time: Optional[float] = None) -> bool:
        """Returns True if the cached recognition has exceeded TTL."""
        now = current_time if current_time is not None else time.time()
        with self._lock:
            state = self._states.get(track_id)
            if state is None:
                return True
            if state.status != RecognitionStatus.RECOGNIZED:
                return False
            if state.first_recognized_time is None:
                return True
            return (now - state.last_attempt_time) > self._ttl_seconds

    def evict(self, track_id: int) -> Optional[TrackIdentityState]:
        """Evicts track state when track is removed from scene."""
        with self._lock:
            return self._states.pop(track_id, None)

    def cleanup_stale_tracks(self, active_track_ids: Set[int]) -> List[int]:
        """Removes cache entries for tracks that are no longer active."""
        evicted: List[int] = []
        with self._lock:
            for tid in list(self._states.keys()):
                if tid not in active_track_ids:
                    self._states.pop(tid, None)
                    evicted.append(tid)
        return evicted

    def clear(self) -> None:
        """Clears all cached states."""
        with self._lock:
            self._states.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._states)
