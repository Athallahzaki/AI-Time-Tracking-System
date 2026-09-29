"""Kebijakan jatah free time — satu-satunya tempat angka bisnis tinggal.

Model yang dipakai (keputusan 23 Sep 2026): kamera memantau RUANG FASILITAS.
Waktu seorang karyawan TERLIHAT di ruang itu memakai jatah hariannya. Hitungan
"gap = istirahat" versi lama sudah dihapus; ia mengukur hal yang berlawanan.

Semua nilai dibaca dari `backend/configs/policy.yaml` (atau `POLICY_CONFIG`).
Engine tidak tahu satu pun angka di sini.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import List, Tuple
from zoneinfo import ZoneInfo

import yaml


def _minutes(value: str) -> int:
    """'HH:MM' -> minutes after midnight. Minutes are kept (12:30 stays 12:30)."""
    hour, separator, minute = str(value).partition(":")
    if not separator or not hour.strip().isdigit() or not minute.strip().isdigit():
        raise ValueError(f"Invalid HH:MM value: {value!r}")
    parsed_hour, parsed_minute = int(hour), int(minute)
    if not 0 <= parsed_hour <= 24 or not 0 <= parsed_minute <= 59 or (
        parsed_hour == 24 and parsed_minute
    ):
        raise ValueError(f"Invalid HH:MM value: {value!r}")
    return parsed_hour * 60 + parsed_minute


@dataclass
class BreakPolicy:
    """Name kept for compatibility; this is the free-time allowance policy."""

    timezone_name: str = "Asia/Jakarta"
    qualification_seconds: float = 20.0
    daily_allowance_minutes: float = 30.0
    warning_remaining_minutes: float = 5.0
    # Pauses in which presence is never charged, as (start_minute, end_minute).
    official_breaks: List[Tuple[int, int]] = field(default_factory=lambda: [(12 * 60, 13 * 60)])
    # Two presence segments of the same person closer than this are ONE visit
    # (occlusion, re-ID, walking between two cameras of the same facility).
    visit_merge_gap_seconds: float = 30.0
    # An identified track with no durable news for this long is no longer
    # charged (engine died without closing it). Heartbeats arrive every 30 s.
    open_presence_stale_seconds: float = 90.0

    def __post_init__(self) -> None:
        self.timezone = ZoneInfo(self.timezone_name)
        for start, end in self.official_breaks:
            if not 0 <= start < end <= 24 * 60:
                raise ValueError("official break must satisfy start < end within one day")

    # --- compatibility accessors (whole hours of the first break) -----------
    @property
    def break_start_hour(self) -> int:
        return self.official_breaks[0][0] // 60 if self.official_breaks else 0

    @property
    def break_end_hour(self) -> int:
        return self.official_breaks[0][1] // 60 if self.official_breaks else 0

    @property
    def allowance_seconds(self) -> float:
        return float(self.daily_allowance_minutes) * 60.0

    @property
    def warning_seconds(self) -> float:
        return float(self.warning_remaining_minutes) * 60.0

    # --- time helpers ------------------------------------------------------
    def local_date(self, timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, self.timezone).date().isoformat()

    def day_bounds(self, local_date: str) -> Tuple[float, float]:
        day = date_type.fromisoformat(local_date)
        start = datetime.combine(day, dt_time.min, self.timezone)
        end = datetime.combine(day + timedelta(days=1), dt_time.min, self.timezone)
        return start.timestamp(), end.timestamp()

    def in_official_break(self, timestamp: float) -> bool:
        local = datetime.fromtimestamp(timestamp, self.timezone)
        minute = local.hour * 60 + local.minute
        return any(start <= minute < end for start, end in self.official_breaks)

    def countable_by_date(self, start: float, end: float) -> dict[str, float]:
        """Seconds of [start, end) per local date, minus official breaks."""
        result: dict[str, float] = {}
        if end <= start:
            return result
        cursor = datetime.fromtimestamp(start, self.timezone)
        end_dt = datetime.fromtimestamp(end, self.timezone)
        while cursor < end_dt:
            day = cursor.date()
            next_day = datetime.combine(day + timedelta(days=1), dt_time.min, self.timezone)
            segment_end = min(end_dt, next_day)
            total = (segment_end - cursor).total_seconds()
            for break_start, break_end in self.official_breaks:
                b0 = datetime.combine(day, dt_time.min, self.timezone) + timedelta(minutes=break_start)
                b1 = datetime.combine(day, dt_time.min, self.timezone) + timedelta(minutes=break_end)
                overlap = (min(segment_end, b1) - max(cursor, b0)).total_seconds()
                if overlap > 0:
                    total -= overlap
            key = day.isoformat()
            result[key] = result.get(key, 0.0) + max(0.0, total)
            cursor = segment_end
        return result

    def status_for(self, used_seconds: float) -> str:
        """'ok' | 'warning' | 'exceeded' — one rule for every endpoint."""
        remaining = self.allowance_seconds - used_seconds
        if used_seconds >= self.allowance_seconds:
            return "exceeded"
        if remaining <= self.warning_seconds:
            return "warning"
        return "ok"


def load_break_policy(path: Path) -> BreakPolicy:
    if not path.exists():
        raise FileNotFoundError(f"Policy config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    allowance = float(data.get(
        "daily_free_time_allowance_minutes",
        data.get("daily_break_allowance_minutes", 30),
    ))
    qualification = float(data.get("qualification_seconds", 20))
    warning = float(data.get("warning_remaining_minutes", 5))
    merge_gap = float(data.get(
        "visit_merge_gap_seconds", data.get("tracking_loss_threshold_seconds", 30)
    ))
    stale = float(data.get("open_presence_stale_seconds", 90))
    if min(allowance, qualification, warning, merge_gap, stale) < 0:
        raise ValueError("Policy durations cannot be negative")
    if warning > allowance:
        raise ValueError("warning_remaining_minutes cannot exceed allowance")

    raw_breaks = data.get("official_breaks")
    if raw_breaks is None:
        single = data.get("official_break") or {"start": "12:00", "end": "13:00"}
        raw_breaks = [single] if single else []
    breaks = [(_minutes(item["start"]), _minutes(item["end"])) for item in raw_breaks]

    return BreakPolicy(
        timezone_name=str(data.get("timezone", "Asia/Jakarta")),
        qualification_seconds=qualification,
        daily_allowance_minutes=allowance,
        warning_remaining_minutes=warning,
        official_breaks=breaks,
        visit_merge_gap_seconds=merge_gap,
        open_presence_stale_seconds=stale,
    )


from backend.core.config import settings  # noqa: E402

break_policy = load_break_policy(settings.policy_yaml_path)
