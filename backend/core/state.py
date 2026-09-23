from __future__ import annotations

import collections
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from backend.services.break_policy import break_policy
from backend.services.free_time import FreeTimeLedger, free_time_ledger

logger = logging.getLogger(__name__)

# A displayed track with no new view frame for this long disappears from the
# live list. Display only: nothing is charged from the view channel any more.
STALE_TRACK_SECONDS = 12.0


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
    """What the overlay shows for one track. NOT a billing record."""

    camera_id: str
    track_id: Union[int, str]
    identity: Optional[str] = None
    similarity: float = 0.0
    presence_status: str = "TRACKED"
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    dwell_time: float = 0.0
    session_elapsed: float = 0.0

    @property
    def key(self) -> str:
        return f"{self.camera_id}_{self.track_id}"

    def elapsed_at(self, now: float) -> float:
        # One clock only: wall time since first_seen. No max() over noisy
        # estimates -- that ratchet only ever moves forward and made the
        # dashboard timer run faster than 1 s/s.
        return max(0.0, now - self.first_seen)


class SystemState:
    """Live display state (view channel) + timer fields from the durable ledger.

    The allowance itself is computed by `FreeTimeLedger` from durable events;
    this class only decorates overlay boxes with those numbers.
    """

    def __init__(self, max_event_history: int = 100, ledger: Optional[FreeTimeLedger] = None,
                 **_ignored: Any) -> None:
        self._lock = threading.Lock()
        self._active_sessions: Dict[str, ActivePersonSession] = {}
        self._event_history = collections.deque(maxlen=max_event_history)
        self._camera_activity: Dict[str, Dict[str, Any]] = {}
        self.ledger = ledger or free_time_ledger

    # ---- timer fields ----------------------------------------------------
    def _timer_fields(self, sess: ActivePersonSession, now: float) -> Dict[str, Any]:
        in_break = break_policy.in_official_break(now)
        qualification = float(break_policy.qualification_seconds)
        allowance = break_policy.allowance_seconds

        if sess.identity:
            usage = self.ledger.usage(sess.identity, now=now)
            used = float(usage["used_seconds"])
            remaining = float(usage["remaining_seconds"])
            if usage["present"]:
                qualification_remaining = float(usage["qualification_remaining_seconds"])
            else:
                # Durable identification not in yet: show local verification.
                elapsed = sum(break_policy.countable_by_date(sess.first_seen, now).values())
                qualification_remaining = max(0.0, qualification - elapsed)
            ledger_status = usage["status"]
        else:
            used = 0.0
            remaining = allowance
            elapsed = sum(break_policy.countable_by_date(sess.first_seen, now).values())
            qualification_remaining = max(0.0, qualification - elapsed)
            ledger_status = "ok"

        qualified = qualification_remaining <= 0
        if in_break:
            status = "OFFICIAL_BREAK"
        elif not qualified:
            status = "VERIFYING"
        elif not sess.identity:
            status = "UNIDENTIFIED"
        elif ledger_status == "exceeded":
            status = "LIMIT"
        elif ledger_status == "warning":
            status = "WARNING"
        else:
            status = "CONFIRMED"
        return {
            "presence_status": status,
            "is_official_break": in_break,
            "is_qualified": qualified,
            "qualification_seconds": qualification,
            "qualification_remaining_seconds": qualification_remaining,
            "visit_free_time_seconds": used,
            "daily_used_seconds": used,
            "remaining_seconds": remaining,
            "allowance_seconds": allowance,
        }

    # ---- view channel ----------------------------------------------------
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
            sess = self._active_sessions.get(session_key)
            if sess is not None:
                # first_seen is anchored once, when the track is first seen.
                # The engine's PTS-based elapsed can run faster than wall time
                # (backlog catch-up, file playback), so it must not keep
                # pulling first_seen backwards.
                sess.last_seen = now
                sess.dwell_time = dwell_time
                sess.session_elapsed = reported_elapsed
                sess.presence_status = presence_status
                if identity:
                    sess.identity = identity
                sess.similarity = max(sess.similarity, similarity)
            else:
                sess = ActivePersonSession(
                    camera_id=camera_id, track_id=track_id, identity=identity,
                    similarity=similarity, presence_status=presence_status,
                    first_seen=now - reported_elapsed, last_seen=now,
                    dwell_time=dwell_time, session_elapsed=reported_elapsed,
                )
                self._active_sessions[session_key] = sess
            return sess.elapsed_at(now)

    def update_view_frame(self, message: Dict[str, Any]) -> Dict[str, Any]:
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
                # Face similarity only. The detector score ("confidence") is a
                # different quantity and must not inflate identity similarity.
                similarity=float(box.get("similarity") or 0.0),
                presence_status="CONFIRMED" if person_id else "TRACKED",
                dwell_time=float(box.get("dwell_time") or 0.0),
                session_elapsed=(
                    float(box["session_elapsed"]) if box.get("session_elapsed") is not None else None
                ),
                observed_at=now,
            )
            box["session_elapsed"] = round(elapsed, 3)
            box["dwell_time"] = round(elapsed, 3)
            with self._lock:
                sess = self._active_sessions[f"{camera_id}_{track_id}"]
            timer_fields = self._timer_fields(sess, now)
            box.update({key: round(value, 3) if isinstance(value, float) else value
                        for key, value in timer_fields.items()})
            # Global clock: absolute server timestamps. The browser computes
            # "how long" as server_now - first_seen_at, so every frame, card
            # and browser reads the same clock and nothing accumulates.
            box["first_seen_at"] = round(sess.first_seen, 3)
            box["timer_as_of"] = round(now, 3)
            enriched_boxes.append(box)

        self.update_camera_status(
            camera_id=camera_id,
            fps=float(message.get("fps") or 0.0),
            people_count=len(enriched_boxes),
            tracking_ids=tracking_ids,
            stream_status="Online & Streaming",
        )
        self.prune_stale_sessions(now=now)
        enriched = dict(message)
        enriched["boxes"] = enriched_boxes
        enriched["server_time"] = round(now, 3)
        return enriched

    def prune_stale_sessions(self, max_idle_seconds: float = STALE_TRACK_SECONDS,
                             now: Optional[float] = None) -> None:
        """Display cleanup only. Nothing is charged here any more."""
        now = time.time() if now is None else now
        with self._lock:
            for key in [k for k, s in self._active_sessions.items()
                        if now - s.last_seen > max_idle_seconds]:
                self._active_sessions.pop(key, None)

    # ---- events ----------------------------------------------------------
    def record_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """In-memory recent history for the dashboard.

        Durable engine events already live in `protocol_events`, corrections in
        `corrections`; writing them to the `events` table too was a duplicate.
        """
        with self._lock:
            self._event_history.append({
                "timestamp": time.time(), "type": event_type, "payload": payload,
            })

    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._event_history)[-limit:]

    def get_camera_activity(self, camera_id: str) -> Dict[str, Any]:
        with self._lock:
            return dict(self._camera_activity.get(camera_id, {}))

    def get_active_sessions(self) -> List[Dict[str, Any]]:
        self.prune_stale_sessions()
        now = time.time()
        with self._lock:
            sessions = list(self._active_sessions.values())
        result = []
        for sess in sessions:
            timer_fields = self._timer_fields(sess, now)
            elapsed = sess.elapsed_at(now)
            result.append({
                "camera_id": sess.camera_id,
                "track_id": sess.track_id,
                "identity": sess.identity,
                "similarity": sess.similarity,
                "first_seen": sess.first_seen,
                "last_seen": sess.last_seen,
                "dwell_time": sess.dwell_time,
                "session_elapsed": elapsed,
                "duration_seconds": elapsed,
                "formatted_duration": format_duration(elapsed),
                **timer_fields,
            })
        return result

    def get_dashboard_stats(self, total_facilities: int = 4) -> Dict[str, Any]:
        self.prune_stale_sessions()
        now = time.time()
        with self._lock:
            active_fac_count = sum(
                1 for info in self._camera_activity.values()
                if info.get("people_count", 0) > 0 and (now - info.get("last_update", 0) < 10)
            )
            active_users = len(self._active_sessions)

        usages = [self.ledger.usage(pid, now=now) for pid in sorted(self.ledger.known_person_ids())]
        total_usage = sum(u["used_seconds"] for u in usages)
        visits = [v["charged_seconds"] for u in usages for v in u["visits"] if v["charged_seconds"] > 0]
        avg_seconds = sum(visits) / len(visits) if visits else 0.0
        exceeded = sum(1 for u in usages if u["status"] in ("warning", "exceeded"))

        return {
            "activeFacilities": active_fac_count,
            "totalFacilities": total_facilities,
            "activeUsers": active_users,
            "totalUsage": format_duration(total_usage) if total_usage > 0 else "0s",
            "avgSession": format_duration(avg_seconds) if avg_seconds > 0 else "0s",
            "exceededDuration": exceeded,
        }


system_state = SystemState()
