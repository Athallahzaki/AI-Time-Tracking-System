"""Ledger jatah free time — dihitung HANYA dari event durabel.

Kenapa bukan dari `view.frame` seperti versi sebelumnya:

- kanal `view` boleh dibuang engine kapan saja (kontrak §6.2), jadi hitungan
  yang dibangun di atasnya bisa kurang tanpa jejak;
- pemakaian lama baru disimpan ketika seseorang membuka dashboard, dan hilang
  saat backend restart;
- orang yang sama di dua kamera dihitung dua kali.

Sekarang sumbernya dua, keduanya durabel:

1. `presence.interval` yang sudah tertutup (tersimpan di `protocol_events`);
2. kehadiran yang MASIH TERBUKA, direkonstruksi dari `track.started`,
   `track.identified`, `track.heartbeat`, `track.identity_changed`,
   `track.ended`, `camera.failed`, dan `snapshot` — yang juga bisa diputar
   ulang dari database saat backend start.

Potongan kehadiran seorang karyawan dari semua kamera digabung (union) lalu
disambung menjadi kunjungan bila jaraknya <= `visit_merge_gap_seconds`. Satu
kunjungan dikenai jatah setelah `qualification_seconds` pertama, dan jam
istirahat resmi tidak pernah dihitung.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set

from backend.core import database
from backend.services.break_policy import BreakPolicy, break_policy

logger = logging.getLogger(__name__)

TRACKED_TYPES = {
    "track.started", "track.identified", "track.heartbeat", "track.resumed",
    "track.identity_changed", "track.ended", "presence.interval",
    "camera.failed", "snapshot",
}


def _ts(value: Any) -> Optional[float]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


@dataclass
class _OpenTrack:
    track_uuid: str
    camera_id: Optional[str]
    start_ts: float
    last_seen_ts: float
    person_id: Optional[str] = None


class OpenPresenceTracker:
    """Which identified tracks are open right now, from durable events only."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tracks: Dict[str, _OpenTrack] = {}

    def clear(self) -> None:
        with self._lock:
            self._tracks.clear()

    def apply(self, event: Dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type not in TRACKED_TYPES:
            return
        at = _ts(event.get("at")) or _ts(event.get("ts")) or time.time()
        uuid = event.get("track_uuid")
        with self._lock:
            if event_type == "track.started" and uuid:
                self._tracks[uuid] = _OpenTrack(uuid, event.get("camera_id"), at, at)
            elif event_type == "track.identified" and uuid:
                track = self._tracks.get(uuid)
                if track is None:
                    # Backend joined late: reconstruct the birth from PTS.
                    started = at - max(0.0, float(event.get("pts", 0.0))
                                       - float(event.get("track_started_pts", 0.0)))
                    track = self._tracks[uuid] = _OpenTrack(uuid, event.get("camera_id"), started, at)
                track.person_id = str(event.get("person_id"))
                track.last_seen_ts = max(track.last_seen_ts, at)
            elif event_type in {"track.heartbeat", "track.resumed"} and uuid:
                track = self._tracks.get(uuid)
                if track is None and event.get("person_id"):
                    track = self._tracks[uuid] = _OpenTrack(uuid, event.get("camera_id"), at, at)
                if track is not None:
                    if event.get("person_id"):
                        track.person_id = str(event["person_id"])
                    track.last_seen_ts = max(track.last_seen_ts, at)
            elif event_type == "track.identity_changed" and uuid:
                track = self._tracks.get(uuid)
                if track is not None:
                    # The part before the change is closed by its own
                    # presence.interval; the open part restarts here.
                    to_person = event.get("to_person_id")
                    track.person_id = str(to_person) if to_person else None
                    track.start_ts = at
                    track.last_seen_ts = max(track.last_seen_ts, at)
            elif event_type == "track.ended" and uuid:
                self._tracks.pop(uuid, None)
            elif event_type == "presence.interval" and uuid:
                track = self._tracks.get(uuid)
                end_ts = _ts(event.get("end_at"))
                if track is not None and end_ts is not None:
                    # identity_released: the closed part is now an interval.
                    track.start_ts = max(track.start_ts, end_ts)
            elif event_type == "camera.failed":
                camera = event.get("camera_id")
                for key in [k for k, t in self._tracks.items() if t.camera_id == camera]:
                    self._tracks.pop(key, None)
            elif event_type == "snapshot":
                cameras = set((event.get("pts_wallclock_offset") or {}).keys())
                live = {item.get("track_uuid") for item in event.get("live") or []}
                for key in [
                    k for k, t in self._tracks.items()
                    if t.camera_id in cameras and k not in live
                ]:
                    self._tracks.pop(key, None)

    def open_segments(
        self, now: float, stale_seconds: float, person_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        with self._lock:
            tracks = list(self._tracks.values())
        segments = []
        for track in tracks:
            if not track.person_id:
                continue
            if person_id is not None and track.person_id != person_id:
                continue
            end = min(now, track.last_seen_ts + stale_seconds)
            if end <= track.start_ts:
                continue
            segments.append({
                "person_id": track.person_id,
                "camera_id": track.camera_id,
                "start_ts": track.start_ts,
                "end_ts": end,
                "segment_id": track.track_uuid,
                "open": end >= now,
            })
        return segments

    def open_person_ids(self) -> Set[str]:
        with self._lock:
            return {t.person_id for t in self._tracks.values() if t.person_id}


@dataclass
class Visit:
    visit_id: str
    start_ts: float
    end_ts: float
    cameras: List[str] = field(default_factory=list)
    open: bool = False
    countable_by_date: Dict[str, float] = field(default_factory=dict)
    charged_by_date: Dict[str, float] = field(default_factory=dict)
    excluded: bool = False


class FreeTimeLedger:
    def __init__(self, policy: BreakPolicy = break_policy) -> None:
        self.policy = policy
        self.tracker = OpenPresenceTracker()
        self._cache_lock = threading.Lock()
        self._cache: Dict[tuple, tuple] = {}

    # ---- feeding ---------------------------------------------------------
    def apply_event(self, event: Dict[str, Any]) -> None:
        self.tracker.apply(event)
        if event.get("type") in TRACKED_TYPES:
            self.invalidate()

    def invalidate(self) -> None:
        with self._cache_lock:
            self._cache.clear()

    def reset_open_presence(self) -> None:
        """Engine outbox changed identity: every open track is from a dead engine."""
        self.tracker.clear()
        self.invalidate()

    def rebuild_from_database(self, lookback_hours: float = 36.0) -> int:
        self.tracker.clear()
        since = time.time() - lookback_hours * 3600.0
        count = 0
        for row in database.get_protocol_events(since_timestamp=since):
            if row["type"] in TRACKED_TYPES:
                self.tracker.apply(row["payload"])
                count += 1
        self.invalidate()
        return count

    # ---- computing -------------------------------------------------------
    def _segments(self, person_id: str, start_ts: float, end_ts: float, now: float) -> List[Dict[str, Any]]:
        segments = []
        for interval in database.get_presence_intervals(start_ts, end_ts, person_id):
            s, e = _ts(interval.get("start_at")), _ts(interval.get("end_at"))
            if s is None or e is None or e < s:
                continue
            segments.append({
                "person_id": person_id, "camera_id": interval.get("camera_id"),
                "start_ts": s, "end_ts": e,
                "segment_id": interval.get("interval_id"), "open": False,
            })
        segments.extend(
            seg for seg in self.tracker.open_segments(
                now, self.policy.open_presence_stale_seconds, person_id
            )
            if seg["end_ts"] >= start_ts and seg["start_ts"] < end_ts
        )
        segments.sort(key=lambda seg: seg["start_ts"])
        return segments

    def _visits(self, segments: Iterable[Dict[str, Any]]) -> List[Visit]:
        visits: List[Visit] = []
        merge_gap = self.policy.visit_merge_gap_seconds
        for seg in segments:
            if visits and seg["start_ts"] - visits[-1].end_ts <= merge_gap:
                current = visits[-1]
                current.end_ts = max(current.end_ts, seg["end_ts"])
                current.open = current.open or seg["open"]
                if seg["camera_id"] and seg["camera_id"] not in current.cameras:
                    current.cameras.append(seg["camera_id"])
            else:
                visits.append(Visit(
                    visit_id=f"visit_{seg['segment_id']}",
                    start_ts=seg["start_ts"], end_ts=seg["end_ts"],
                    cameras=[seg["camera_id"]] if seg["camera_id"] else [],
                    open=seg["open"],
                ))
        for visit in visits:
            visit.countable_by_date = self.policy.countable_by_date(visit.start_ts, visit.end_ts)
            total = sum(visit.countable_by_date.values())
            if total < self.policy.qualification_seconds:
                visit.charged_by_date = {day: 0.0 for day in visit.countable_by_date}
                continue
            grace = self.policy.qualification_seconds
            for day in sorted(visit.countable_by_date):
                seconds = visit.countable_by_date[day]
                free = min(grace, seconds)
                grace -= free
                visit.charged_by_date[day] = seconds - free
        return visits

    def usage(self, person_id: str, local_date: Optional[str] = None,
              now: Optional[float] = None) -> Dict[str, Any]:
        now = time.time() if now is None else now
        local_date = local_date or self.policy.local_date(now)
        cache_key = (person_id, local_date, int(now))
        with self._cache_lock:
            cached = self._cache.get(cache_key)
        if cached is not None:
            return cached[1]

        day_start, day_end = self.policy.day_bounds(local_date)
        # Look back one merge window + a day so a visit crossing midnight or
        # starting just before the window is still merged correctly.
        segments = self._segments(person_id, day_start - 86400.0, day_end, now)
        visits = [
            v for v in self._visits(segments)
            if v.countable_by_date.get(local_date) is not None
        ]

        corrections = database.get_corrections(person_id=person_id, local_date=local_date)
        excluded_ids = {c.get("gap_id") for c in corrections if c.get("exclude_visit")}
        adjustment = sum(float(c.get("adjustment_seconds") or 0.0) for c in corrections)

        used = 0.0
        entries = []
        for visit in visits:
            charged = visit.charged_by_date.get(local_date, 0.0)
            visit.excluded = visit.visit_id in excluded_ids
            if visit.excluded:
                charged_effective = 0.0
            else:
                charged_effective = charged
            used += charged_effective
            entries.append({
                "visit_id": visit.visit_id,
                "start_ts": visit.start_ts,
                "end_ts": visit.end_ts,
                "cameras": visit.cameras,
                "open": visit.open,
                "countable_seconds": round(visit.countable_by_date.get(local_date, 0.0), 3),
                "charged_seconds": round(charged_effective, 3),
                "original_charged_seconds": round(charged, 3),
                "excluded": visit.excluded,
            })
        used = max(0.0, used + adjustment)

        current = next((v for v in reversed(visits) if v.open), None)
        qualification_remaining = 0.0
        if current is not None:
            countable_now = sum(current.countable_by_date.values())
            qualification_remaining = max(0.0, self.policy.qualification_seconds - countable_now)

        result = {
            "person_id": person_id,
            "date": local_date,
            "used_seconds": round(used, 3),
            "allowance_seconds": self.policy.allowance_seconds,
            "remaining_seconds": round(max(0.0, self.policy.allowance_seconds - used), 3),
            "status": self.policy.status_for(used),
            "adjustment_seconds": round(adjustment, 3),
            "visits": entries,
            "present": current is not None,
            "qualification_remaining_seconds": round(qualification_remaining, 3),
            "is_official_break": self.policy.in_official_break(now),
        }
        with self._cache_lock:
            if len(self._cache) > 5000:
                self._cache.clear()
            self._cache[cache_key] = (now, result)
        return result

    def known_person_ids(self) -> Set[str]:
        ids = set(database.get_known_person_ids())
        ids.update(self.tracker.open_person_ids())
        ids.update(str(item["person_id"]) for item in database.get_enrollments())
        return ids


free_time_ledger = FreeTimeLedger()
