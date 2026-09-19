from __future__ import annotations

import collections
import logging
import threading
import time

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.core.database import save_event

logger = logging.getLogger(__name__)


def format_duration(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    m = s // 60
    rem_s = s % 60
    if m < 60:
        return f"{m}m {rem_s}s" if rem_s > 0 else f"{m} min"
    h = m // 60
    rem_m = m % 60
    return f"{h}h {rem_m}m"


@dataclass
class ActivePersonSession:
    camera_id: str
    track_id: int
    identity: Optional[str] = None
    similarity: float = 0.0
    presence_status: str = "PASSING"
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    dwell_time: float = 0.0
    session_elapsed: float = 0.0

    @property
    def key(self) -> str:
        return f"{self.camera_id}_{self.identity or self.track_id}"


class SystemState:
    """Thread-safe global state store aggregating runtime metrics and events."""

    def __init__(self, max_event_history: int = 100) -> None:
        self._lock = threading.Lock()
        self._active_sessions: Dict[str, ActivePersonSession] = {}
        self._event_history = collections.deque(maxlen=max_event_history)
        self._completed_session_durations: List[float] = []
        self._camera_activity: Dict[str, Dict[str, Any]] = {}

    def update_camera_status(
        self,
        camera_id: str,
        fps: float,
        people_count: int,
        tracking_ids: List[int],
        stream_status: str = "Online & Healthy",
    ) -> None:
        with self._lock:
            self._camera_activity[camera_id] = {
                "fps": fps,
                "people_count": people_count,
                "tracking_ids": tracking_ids,
                "stream_status": stream_status,
                "last_update": time.time(),
            }

    def update_track(
        self,
        camera_id: str,
        track_id: int,
        identity: Optional[str],
        similarity: float,
        presence_status: str,
        dwell_time: float,
        session_elapsed: float,
    ) -> None:
        now = time.time()
        session_key = f"{camera_id}_{identity or track_id}"
        with self._lock:
            if session_key in self._active_sessions:
                sess = self._active_sessions[session_key]
                sess.last_seen = now
                sess.dwell_time = dwell_time
                sess.session_elapsed = session_elapsed
                sess.presence_status = presence_status
                if identity:
                    sess.identity = identity
                sess.similarity = max(sess.similarity, similarity)
            else:
                self._active_sessions[session_key] = ActivePersonSession(
                    camera_id=camera_id,
                    track_id=track_id,
                    identity=identity,
                    similarity=similarity,
                    presence_status=presence_status,
                    first_seen=now - session_elapsed,
                    last_seen=now,
                    dwell_time=dwell_time,
                    session_elapsed=session_elapsed,
                )

    def prune_stale_sessions(self, max_idle_seconds: float = 12.0) -> None:
        now = time.time()
        with self._lock:
            stale_keys = [
                key
                for key, sess in self._active_sessions.items()
                if now - sess.last_seen > max_idle_seconds
            ]
            for key in stale_keys:
                sess = self._active_sessions.pop(key)
                self._completed_session_durations.append(sess.session_elapsed)

    def record_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        event_entry = {
            "timestamp": time.time(),
            "type": event_type,
            "payload": payload,
        }

        with self._lock:
            self._event_history.append(event_entry)

        save_event(
            timestamp=event_entry["timestamp"],
            event_type=event_type,
            payload=payload,
        )

    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            events = list(self._event_history)
            return events[-limit:]

    def get_active_sessions(self) -> List[Dict[str, Any]]:
        self.prune_stale_sessions()
        with self._lock:
            return [
                {
                    "camera_id": sess.camera_id,
                    "track_id": sess.track_id,
                    "identity": sess.identity,
                    "similarity": sess.similarity,
                    "presence_status": sess.presence_status,
                    "first_seen": sess.first_seen,
                    "last_seen": sess.last_seen,
                    "dwell_time": sess.dwell_time,
                    "session_elapsed": sess.session_elapsed,
                    "formatted_duration": format_duration(sess.session_elapsed),
                }
                for sess in self._active_sessions.values()
            ]

    def get_dashboard_stats(self, total_facilities: int = 4) -> Dict[str, Any]:
        self.prune_stale_sessions()
        now = time.time()
        with self._lock:
            # Active facilities = cameras with active tracked people or recent activity
            active_fac_count = sum(
                1
                for info in self._camera_activity.values()
                if info.get("people_count", 0) > 0 and (now - info.get("last_update", 0) < 10)
            )
            # Default to at least 1 if active sessions exist
            if active_fac_count == 0 and len(self._active_sessions) > 0:
                active_fac_count = len(set(s.camera_id for s in self._active_sessions.values()))

            active_users = len(self._active_sessions)

            # Total usage = sum of all past completed + active sessions
            total_active_seconds = sum(s.session_elapsed for s in self._active_sessions.values())
            total_past_seconds = sum(self._completed_session_durations)
            total_usage_seconds = total_active_seconds + total_past_seconds

            # Average session
            all_sessions = [s.session_elapsed for s in self._active_sessions.values()] + self._completed_session_durations
            avg_seconds = (sum(all_sessions) / len(all_sessions)) if all_sessions else 0.0

            # Exceeded limit count (LIMIT or WARNING status)
            exceeded_count = sum(
                1
                for s in self._active_sessions.values()
                if s.presence_status in ("LIMIT", "WARNING")
            )

            return {
                "activeFacilities": max(1, active_fac_count) if active_users > 0 else active_fac_count,
                "totalFacilities": total_facilities,
                "activeUsers": active_users,
                "totalUsage": format_duration(total_usage_seconds) if total_usage_seconds > 0 else "0s",
                "avgSession": format_duration(avg_seconds) if avg_seconds > 0 else "0s",
                "exceededDuration": exceeded_count,
            }


# Singleton system state
system_state = SystemState()
