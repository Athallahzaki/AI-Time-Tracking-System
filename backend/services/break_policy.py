from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any, Dict
import yaml

from backend.schemas.attendance import GapClassification


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )


class BreakPolicy:
    def __init__(
        self,
        break_start_hour: int = 12,
        break_end_hour: int = 13,
        tracking_loss_threshold: float = 30.0,
        daily_allowance_minutes: float = 30.0,
        warning_remaining_minutes: float = 5.0,
        timezone_name: str = "Asia/Jakarta",
    ) -> None:
        self.break_start_hour = break_start_hour
        self.break_end_hour = break_end_hour
        self.tracking_loss_threshold = (
            tracking_loss_threshold
        )
        self.daily_allowance_minutes = daily_allowance_minutes
        self.warning_remaining_minutes = warning_remaining_minutes
        self.timezone_name = timezone_name
        self.timezone = ZoneInfo(timezone_name)

    def classify(
        self,
        gap: Dict[str, Any],
        previous_interval: Dict[str, Any],
        next_interval: Dict[str, Any],
    ) -> GapClassification:

        gap_seconds = gap["gap_seconds"]

        # 1. Camera/system failure lebih kuat daripada
        #    klasifikasi attendance biasa.
        end_reason = previous_interval.get(
            "end_reason"
        )

        if end_reason == "camera_lost":
            return GapClassification.CAMERA_FAILURE

        if end_reason in {
            "engine_shutdown",
            "system_shutdown",
        }:
            return GapClassification.SYSTEM_EVENT

        # 2. Official break berdasarkan waktu kejadian,
        #    bukan datetime.now().
        gap_start = _parse_utc(
            gap["gap_started_at"]
        ).astimezone(self.timezone)

        if (
            self.break_start_hour
            <= gap_start.hour
            < self.break_end_hour
        ):
            return GapClassification.OFFICIAL_BREAK

        # 3. Gap pendek dari interior kemungkinan
        #    tracking loss.
        if (
            previous_interval.get("end_zone")
            == "interior"
            and gap_seconds
            <= self.tracking_loss_threshold
        ):
            return GapClassification.TRACKING_LOSS

        # 4. Keluar melalui door dan kembali lagi
        #    merupakan break.
        if (
            previous_interval.get("end_zone")
            == "door"
            and next_interval.get("start_zone")
            == "door"
        ):
            return GapClassification.BREAK

        # Belum cukup bukti untuk menentukan departure.
        return GapClassification.UNKNOWN


def _hour(value: str) -> int:
    hour, separator, minute = value.partition(":")
    if not separator or not hour.isdigit() or not minute.isdigit():
        raise ValueError(f"Invalid HH:MM value: {value!r}")
    parsed_hour, parsed_minute = int(hour), int(minute)
    if not 0 <= parsed_hour <= 23 or not 0 <= parsed_minute <= 59:
        raise ValueError(f"Invalid HH:MM value: {value!r}")
    return parsed_hour


def load_break_policy(path: Path) -> BreakPolicy:
    if not path.exists():
        raise FileNotFoundError(f"Policy config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    official = data.get("official_break") or {}
    allowance = float(data.get("daily_break_allowance_minutes", 30))
    warning = float(data.get("warning_remaining_minutes", 5))
    threshold = float(data.get("tracking_loss_threshold_seconds", 30))
    if allowance < 0 or warning < 0 or threshold < 0:
        raise ValueError("Policy durations cannot be negative")
    if warning > allowance:
        raise ValueError("warning_remaining_minutes cannot exceed allowance")
    return BreakPolicy(
        break_start_hour=_hour(str(official.get("start", "12:00"))),
        break_end_hour=_hour(str(official.get("end", "13:00"))),
        tracking_loss_threshold=threshold,
        daily_allowance_minutes=allowance,
        warning_remaining_minutes=warning,
        timezone_name=str(data.get("timezone", "Asia/Jakarta")),
    )


from backend.core.config import settings

break_policy = load_break_policy(settings.policy_yaml_path)
