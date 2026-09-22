from __future__ import annotations

import collections
import logging
import threading
import time

from dataclasses import dataclass, field
from datetime import datetime, time as datetime_time, timedelta
from typing import Any, Dict, List, Optional, Union
from zoneinfo import ZoneInfo

from backend.core.database import add_free_time_usage, get_free_time_usage, save_event
from backend.services.break_policy import break_policy

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
    track_id: Union[int, str]
    identity: Optional[str] = None
    similarity: float = 0.0
    presence_status: str = "PASSING"
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    dwell_time: float = 0.0
    session_elapsed: float = 0.0

    @property
    def key(self) -> str:
        return f"{self.camera_id}_{self.track_id}"

    def elapsed_at(self, now: float) -> float:
        """Return a monotonic live duration even between incoming frames."""
        return max(self.session_elapsed, now - self.first_seen)


class SystemState:
    """Thread-safe global state store aggregating runtime metrics and events."""

    def __init__(self, max_event_history: int = 100, persist_usage: bool = False) -> None:
        self._lock = threading.Lock()
        self._active_sessions: Dict[str, ActivePersonSession] = {}
        self._event_history = collections.deque(maxlen=max_event_history)
        self._completed_session_durations: List[float] = []
        self._camera_activity: Dict[str, Dict[str, Any]] = {}
        self._persist_usage = persist_usage
        stored_usage = get_free_time_usage() if persist_usage else {}
        self._completed_daily_usage: Dict[tuple[str, str], float] = collections.defaultdict(
            float, stored_usage
        )
        self._timezone = ZoneInfo(break_policy.timezone_name)
        self._qualification_seconds = float(break_policy.qualification_seconds)
        self._allowance_seconds = float(break_policy.daily_allowance_minutes) * 60
        self._warning_seconds = float(break_policy.warning_remaining_minutes) * 60

    def _countable_by_date(self, start: float, end: float) -> Dict[str, float]:
        """Split presence by local day, excluding the official 12:00-13:00 break."""
        if end <= start:
            return {}
        start_dt = datetime.fromtimestamp(start, self._timezone)
        end_dt = datetime.fromtimestamp(end, self._timezone)
        cursor = start_dt
        result: Dict[str, float] = collections.defaultdict(float)
        while cursor < end_dt:
            next_day = datetime.combine(
                cursor.date() + timedelta(days=1), datetime_time.min, self._timezone
            )
            segment_end = min(end_dt, next_day)
            break_start = datetime.combine(
                cursor.date(), datetime_time(break_policy.break_start_hour), self._timezone
            )
            break_end = datetime.combine(
                cursor.date(), datetime_time(break_policy.break_end_hour), self._timezone
            )
            total = (segment_end - cursor).total_seconds()
            overlap = max(
                0.0,
                (min(segment_end, break_end) - max(cursor, break_start)).total_seconds(),
            )
            result[cursor.date().isoformat()] += max(0.0, total - overlap)
            cursor = segment_end
        return dict(result)

    def _visit_charge_by_date(self, sess: ActivePersonSession, now: float) -> Dict[str, float]:
        countable = self._countable_by_date(sess.first_seen, now)
        grace = self._qualification_seconds
        charged: Dict[str, float] = {}
        for local_date, seconds in countable.items():
            ignored = min(grace, seconds)
            grace -= ignored
            charged[local_date] = max(0.0, seconds - ignored)
        return charged

    def _timer_fields(self, sess: ActivePersonSession, now: float) -> Dict[str, Any]:
        local_now = datetime.fromtimestamp(now, self._timezone)
        in_break = break_policy.break_start_hour <= local_now.hour < break_policy.break_end_hour
        countable = sum(self._countable_by_date(sess.first_seen, now).values())
        remaining_qualification = max(0.0, self._qualification_seconds - countable)
        qualified = remaining_qualification <= 0
        visit_by_date = self._visit_charge_by_date(sess, now)
        today = local_now.date().isoformat()
        visit_used = sum(visit_by_date.values())
        daily_used = (
            self._completed_daily_usage.get((sess.identity, today), 0.0)
            + visit_by_date.get(today, 0.0)
            if sess.identity else visit_by_date.get(today, 0.0)
        )
        remaining = max(0.0, self._allowance_seconds - daily_used)
        if in_break:
            status = "OFFICIAL_BREAK"
        elif not qualified:
            status = "VERIFYING"
        elif not sess.identity:
            status = "UNIDENTIFIED"
        elif daily_used >= self._allowance_seconds:
            status = "LIMIT"
        elif remaining <= self._warning_seconds:
            status = "WARNING"
        else:
            status = "CONFIRMED"
        return {
            "presence_status": status,
            "is_official_break": in_break,
            "is_qualified": qualified,
            "qualification_seconds": self._qualification_seconds,
            "qualification_remaining_seconds": remaining_qualification,
            "visit_free_time_seconds": visit_used,
            "daily_used_seconds": daily_used,
            "remaining_seconds": remaining,
            "allowance_seconds": self._allowance_seconds,
        }

    def update_camera_status(
        self,
        camera_id: str,
        fps: float,
        people_count: int,
        tracking_ids: List[Union[int, str]],
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
        track_id: Union[int, str],
        identity: Optional[str],
        similarity: float,
        presence_status: str,
        dwell_time: float = 0.0,
        session_elapsed: Optional[float] = None,
        observed_at: Optional[float] = None,
    ) -> float:
        now = observed_at if observed_at is not None else time.time()
        reported_elapsed = max(0.0, float(session_elapsed or 0.0))
        session_key = f"{camera_id}_{track_id}"
        with self._lock:
            if session_key in self._active_sessions:
                sess = self._active_sessions[session_key]
                sess.last_seen = now
                sess.dwell_time = dwell_time
                sess.session_elapsed = max(
                    sess.session_elapsed,
                    reported_elapsed,
                    now - sess.first_seen,
                )
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
                    first_seen=now - reported_elapsed,
                    last_seen=now,
                    dwell_time=dwell_time,
                    session_elapsed=reported_elapsed,
                )
                sess = self._active_sessions[session_key]
            return sess.elapsed_at(now)

    def update_view_frame(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Update live sessions from the real engine and add timer fields to SSE."""
        camera_id = str(message.get("camera_id") or "")
        if not camera_id:
            raise ValueError("view.frame must contain camera_id")

        now = time.time()
        boxes = message.get("boxes") if isinstance(message.get("boxes"), list) else []
        enriched_boxes: List[Dict[str, Any]] = []
        tracking_ids: List[Union[int, str]] = []

        for index, raw_box in enumerate(boxes):
            if not isinstance(raw_box, dict):
                continue
            box = dict(raw_box)
            track_id = box.get("track_uuid") or box.get("track_id") or f"unknown-{index + 1}"
            tracking_ids.append(track_id)
            person_id = box.get("person_id")
            elapsed = self.update_track(
                camera_id=camera_id,
                track_id=track_id,
                identity=str(person_id) if person_id is not None else None,
                similarity=float(box.get("similarity") or box.get("confidence") or 0.0),
                presence_status="CONFIRMED" if person_id else "TRACKED",
                dwell_time=float(box.get("dwell_time") or 0.0),
                session_elapsed=(
                    float(box["session_elapsed"])
                    if box.get("session_elapsed") is not None
                    else None
                ),
                observed_at=now,
            )
            box["session_elapsed"] = round(elapsed, 3)
            box["dwell_time"] = round(elapsed, 3)
            session_key = f"{camera_id}_{track_id}"
            with self._lock:
                timer_fields = self._timer_fields(self._active_sessions[session_key], now)
            box.update({key: round(value, 3) if isinstance(value, float) else value
                        for key, value in timer_fields.items()})
            enriched_boxes.append(box)

        self.update_camera_status(
            camera_id=camera_id,
            fps=float(message.get("fps") or 0.0),
            people_count=len(enriched_boxes),
            tracking_ids=tracking_ids,
            stream_status="Online & Streaming",
        )
        enriched = dict(message)
        enriched["boxes"] = enriched_boxes
        return enriched

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
                if sess.identity:
                    for local_date, seconds in self._visit_charge_by_date(sess, sess.last_seen).items():
                        self._completed_daily_usage[(sess.identity, local_date)] += seconds
                        if self._persist_usage:
                            add_free_time_usage(sess.identity, local_date, seconds)
                self._completed_session_durations.append(
                    max(sess.session_elapsed, sess.last_seen - sess.first_seen)
                )

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

    def get_camera_activity(self, camera_id: str) -> Dict[str, Any]:
        with self._lock:
            return dict(self._camera_activity.get(camera_id, {}))

    def get_active_sessions(self) -> List[Dict[str, Any]]:
        self.prune_stale_sessions()
        now = time.time()
        with self._lock:
            result = []
            for sess in self._active_sessions.values():
                timer_fields = self._timer_fields(sess, now)
                result.append({
                    "camera_id": sess.camera_id,
                    "track_id": sess.track_id,
                    "identity": sess.identity,
                    "similarity": sess.similarity,
                    "presence_status": timer_fields["presence_status"],
                    "first_seen": sess.first_seen,
                    "last_seen": sess.last_seen,
                    "dwell_time": sess.dwell_time,
                    "session_elapsed": sess.elapsed_at(now),
                    "duration_seconds": sess.elapsed_at(now),
                    "formatted_duration": format_duration(sess.elapsed_at(now)),
                    **timer_fields,
                })
            return result

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

            # Dashboard usage follows chargeable free time, not passers-by or lunch.
            total_active_seconds = sum(
                sum(self._visit_charge_by_date(s, now).values())
                for s in self._active_sessions.values()
            )
            total_past_seconds = sum(self._completed_daily_usage.values())
            total_usage_seconds = total_active_seconds + total_past_seconds

            # Average session
            all_sessions = [
                sum(self._visit_charge_by_date(s, now).values())
                for s in self._active_sessions.values()
            ] + self._completed_session_durations
            avg_seconds = (sum(all_sessions) / len(all_sessions)) if all_sessions else 0.0

            # Exceeded limit count (LIMIT or WARNING status)
            exceeded_count = sum(
                1
                for s in self._active_sessions.values()
                if self._timer_fields(s, now)["presence_status"] in ("LIMIT", "WARNING")
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
system_state = SystemState(persist_usage=True)
