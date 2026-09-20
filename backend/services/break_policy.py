from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

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
    ) -> None:
        self.break_start_hour = break_start_hour
        self.break_end_hour = break_end_hour
        self.tracking_loss_threshold = (
            tracking_loss_threshold
        )

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
        )

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


break_policy = BreakPolicy()