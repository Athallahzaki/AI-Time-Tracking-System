from __future__ import annotations

import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from ..vision_core.contracts.frame import Frame
from ..vision_core.contracts.tracking import Track, TrackState
from .config import AttendanceConfig
from .events import (
    AppEvent,
    PersonConfirmedEvent,
    PersonDepartedEvent,
    PersonEnteredEvent,
    SessionLimitReachedEvent,
    SessionWarningEvent,
)

logger = logging.getLogger(__name__)


class PresenceStatus(str, enum.Enum):
    PASSING = "PASSING"
    CONFIRMED = "CONFIRMED"
    WARNING = "WARNING"
    LIMIT = "LIMIT"


@dataclass
class EmployeeSession:
    """Represents an active presence session for a person or employee."""
    session_id: str
    employee_id: Optional[str] = None
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    status: PresenceStatus = PresenceStatus.PASSING
    active_track_id: Optional[int] = None
    warning_emitted: bool = False
    limit_emitted: bool = False
    confirmed_emitted: bool = False

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, self.last_seen - self.first_seen)


class AttendanceTracker:
    """
    Application-level attendance and dwell time engine.
    Consumes tracks with attached recognition attributes, evaluates time thresholds,
    and manages employee presence sessions.
    """

    def __init__(self, config: Optional[AttendanceConfig] = None) -> None:
        self._config = config or AttendanceConfig()
        self._sessions: Dict[str, EmployeeSession] = {}  # key: employee_id or "track_{tid}"
        self._track_to_key: Dict[int, str] = {}
        self._event_handlers: List[Callable[[AppEvent], None]] = []

    def add_event_handler(self, handler: Callable[[AppEvent], None]) -> AttendanceTracker:
        if handler not in self._event_handlers:
            self._event_handlers.append(handler)
        return self

    def _emit_event(self, event: AppEvent) -> None:
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Error in attendance event handler: {e}")

    def on_tracks_updated(
        self,
        tracks: List[Track],
        frame: Frame,
    ) -> None:
        """Processes active tracks and updates presence timers."""
        # Use wall-clock time for all session timestamps so that video-file
        # playback at any speed does not cause false-positive departure events.
        wall_now = time.time()
        current_active_keys = set()

        for track in tracks:
            if not track.is_active:
                continue

            emp_id = track.attributes.get("identity")
            session_key = (
                emp_id
                if emp_id
                else f"track_{track.track_id}"
            )

            current_active_keys.add(session_key)

            # Upgrade anonymous track session to employee session
            if (
                emp_id
                and track.track_id in self._track_to_key
            ):
                old_key = self._track_to_key[track.track_id]

                if (
                    old_key != emp_id
                    and old_key in self._sessions
                ):
                    old_sess = self._sessions.pop(old_key)

                    if emp_id not in self._sessions:
                        old_sess.employee_id = emp_id
                        old_sess.session_id = emp_id
                        self._sessions[emp_id] = old_sess
                    else:
                        self._sessions[emp_id].last_seen = wall_now

            self._track_to_key[track.track_id] = session_key

            # Get or create session
            if session_key not in self._sessions:
                sess = EmployeeSession(
                    session_id=session_key,
                    employee_id=emp_id,
                    first_seen=wall_now,
                    last_seen=wall_now,
                    active_track_id=track.track_id,
                )

                self._sessions[session_key] = sess

                self._emit_event(
                    PersonEnteredEvent(
                        employee_id=emp_id,
                        track_id=track.track_id,
                    )
                )
            else:
                sess = self._sessions[session_key]
                sess.last_seen = wall_now
                sess.active_track_id = track.track_id

                if emp_id:
                    sess.employee_id = emp_id

            # Evaluate status
            elapsed = sess.elapsed_seconds
            status = self._compute_status(elapsed)
            sess.status = status

            # Annotate track
            track.attributes["presence_status"] = status.value
            track.attributes["session_elapsed"] = elapsed

            # Emit milestone events
            if (
                status == PresenceStatus.CONFIRMED
                and not sess.confirmed_emitted
            ):
                sess.confirmed_emitted = True

                self._emit_event(
                    PersonConfirmedEvent(
                        employee_id=sess.employee_id,
                        track_id=track.track_id,
                        duration_seconds=elapsed,
                    )
                )

            elif (
                status == PresenceStatus.WARNING
                and not sess.warning_emitted
            ):
                sess.warning_emitted = True

                self._emit_event(
                    SessionWarningEvent(
                        employee_id=sess.employee_id,
                        track_id=track.track_id,
                        duration_minutes=elapsed / 60.0,
                    )
                )

            elif (
                status == PresenceStatus.LIMIT
                and not sess.limit_emitted
            ):
                sess.limit_emitted = True

                self._emit_event(
                    SessionLimitReachedEvent(
                        employee_id=sess.employee_id,
                        track_id=track.track_id,
                        duration_minutes=elapsed / 60.0,
                    )
                )

        # Check for expired/departed sessions (uses wall clock so video-file
        # playback at any speed does not cause false-positive departures)
        to_close = []

        for key, sess in list(self._sessions.items()):
            if (
                wall_now - sess.last_seen
            ) > self._config.max_missing_seconds:
                to_close.append(key)

        for key in to_close:
            closed_sess = self._sessions.pop(key)

            if closed_sess.active_track_id is not None:
                mapped_key = self._track_to_key.get(
                    closed_sess.active_track_id
                )

                if mapped_key == key:
                    self._track_to_key.pop(
                        closed_sess.active_track_id,
                        None,
                    )

            self._emit_event(
                PersonDepartedEvent(
                    employee_id=closed_sess.employee_id,
                    track_id=closed_sess.active_track_id or 0,
                    total_session_seconds=closed_sess.elapsed_seconds,
                )
            )

    def on_track_removed(
        self,
        track: Track,
    ) -> None:
        """
        Called when vision_core determines that a track has been
        permanently removed from tracker output.

        Attendance session is allowed to perform its normal
        missing-timeout logic, so this callback only clears the
        track-to-session mapping when it still points to this track.
        """
        track_id = track.track_id

        session_key = self._track_to_key.get(track_id)

        if session_key is None:
            return

        session = self._sessions.get(session_key)

        if session is not None:
            if session.active_track_id == track_id:
                session.active_track_id = None

        self._track_to_key.pop(track_id, None)

    def _compute_status(
        self,
        elapsed_seconds: float,
    ) -> PresenceStatus:
        if elapsed_seconds >= (
            self._config.max_session_minutes * 60.0
        ):
            return PresenceStatus.LIMIT

        if elapsed_seconds >= (
            self._config.warning_minutes * 60.0
        ):
            return PresenceStatus.WARNING

        if elapsed_seconds >= self._config.min_present_seconds:
            return PresenceStatus.CONFIRMED

        return PresenceStatus.PASSING

    def get_session(
        self,
        employee_or_track_id: str,
    ) -> Optional[EmployeeSession]:
        return self._sessions.get(employee_or_track_id)

    @property
    def active_sessions(
        self,
    ) -> Dict[str, EmployeeSession]:
        return dict(self._sessions)
