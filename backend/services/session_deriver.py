from __future__ import annotations

from datetime import datetime
from typing import Any, Dict
from backend.services.break_policy import BreakPolicy

def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class SessionDeriver:
    """
    Mengubah presence.interval dari engine menjadi representasi
    session milik backend.

    Engine menentukan interval observasi.
    Backend menentukan bagaimana interval menjadi attendance session.
    """

    def derive_interval(
        self,
        interval: Dict[str, Any],
    ) -> Dict[str, Any]:

        if interval.get("type") != "presence.interval":
            raise ValueError(
                "SessionDeriver only accepts presence.interval"
            )

        start_at = _parse_utc(interval["start_at"])
        end_at = _parse_utc(interval["end_at"])

        duration_seconds = (
            end_at - start_at
        ).total_seconds()

        if duration_seconds < 0:
            raise ValueError(
                "presence.interval end_at cannot be before start_at"
            )

        return {
            "person_id": interval["person_id"],
            "camera_id": interval["camera_id"],

            "interval_ids": [
                interval["interval_id"]
            ],

            "started_at": interval["start_at"],
            "ended_at": interval["end_at"],

            "duration_seconds": duration_seconds,

            "start_zone": interval["start_zone"],
            "end_zone": interval["end_zone"],

            "end_reason": interval["end_reason"],

            "identity_confidence": interval[
                "identity_confidence"
            ],

            "evidence_count": interval[
                "evidence_count"
            ],

            "stream_epochs": [
                interval["stream_epoch"]
            ],
        }

    def calculate_gap(
        self,
        previous_interval: Dict[str, Any],
        next_interval: Dict[str, Any],
    ) -> Dict[str, Any]:

        if previous_interval.get("type") != "presence.interval":
            raise ValueError(
                "Previous message must be presence.interval"
            )

        if next_interval.get("type") != "presence.interval":
            raise ValueError(
                "Next message must be presence.interval"
            )

        if (
            previous_interval["person_id"]
            != next_interval["person_id"]
        ):
            raise ValueError(
                "Cannot calculate gap for different person"
            )

        previous_end = _parse_utc(
            previous_interval["end_at"]
        )

        next_start = _parse_utc(
            next_interval["start_at"]
        )

        gap_seconds = (
            next_start - previous_end
        ).total_seconds()

        if gap_seconds < 0:
            raise ValueError(
                "Presence intervals overlap"
            )

        return {
            "person_id": previous_interval["person_id"],

            "previous_interval_id": previous_interval[
                "interval_id"
            ],

            "next_interval_id": next_interval[
                "interval_id"
            ],

            "gap_started_at": previous_interval["end_at"],
            "gap_ended_at": next_interval["start_at"],

            "gap_seconds": gap_seconds,

            # Nilai awal; classify_gaps() menggantinya memakai kebijakan backend.
            "classification": "unknown",
        }

    def derive_sessions(
        self,
        intervals: list[Dict[str, Any]],
    ) -> Dict[str, Any]:

        if not intervals:
            return {
                "sessions": [],
                "gaps": [],
            }

        sessions = []
        gaps = []

        current_session = self.derive_interval(
            intervals[0]
        )

        previous_interval = intervals[0]

        for interval in intervals[1:]:

            # Engine sudah menyatakan bahwa interval ini
            # adalah kelanjutan langsung.
            if (
                interval.get("prev_interval_id")
                == previous_interval["interval_id"]
            ):
                current_session = (
                    self.merge_chained_interval(
                        current_session,
                        interval,
                    )
                )

            else:
                # Tidak ada chain resmi dari engine.
                # Tutup session sebelumnya.
                sessions.append(current_session)

                # Hitung gap jika masih orang yang sama.
                if (
                    previous_interval["person_id"]
                    == interval["person_id"]
                ):
                    gaps.append(
                        self.calculate_gap(
                            previous_interval,
                            interval,
                        )
                    )

                # Interval baru menjadi session baru.
                current_session = self.derive_interval(
                    interval
                )

            previous_interval = interval

        sessions.append(current_session)

        return {
            "sessions": sessions,
            "gaps": gaps,
        }
    def merge_chained_interval(
        self,
        session: Dict[str, Any],
        interval: Dict[str, Any],
    ) -> Dict[str, Any]:

        if interval.get("type") != "presence.interval":
            raise ValueError(
                "SessionDeriver only accepts presence.interval"
            )

        prev_interval_id = interval.get("prev_interval_id")

        if not prev_interval_id:
            raise ValueError(
                "Interval is not chained"
            )

        if prev_interval_id != session["interval_ids"][-1]:
            raise ValueError(
                "prev_interval_id does not match current session"
            )

        if interval["person_id"] != session["person_id"]:
            raise ValueError(
                "Cannot merge interval from different person"
            )

        start_at = _parse_utc(session["started_at"])
        end_at = _parse_utc(interval["end_at"])

        duration_seconds = (
            end_at - start_at
        ).total_seconds()

        if duration_seconds < 0:
            raise ValueError(
                "Merged session has invalid duration"
            )

        return {
            **session,

            "interval_ids": [
                *session["interval_ids"],
                interval["interval_id"],
            ],

            "ended_at": interval["end_at"],
            "duration_seconds": duration_seconds,

            "end_zone": interval["end_zone"],
            "end_reason": interval["end_reason"],

            "identity_confidence": interval[
                "identity_confidence"
            ],

            "evidence_count": (
                session["evidence_count"]
                + interval["evidence_count"]
            ),

            "stream_epochs": list(
                dict.fromkeys([
                    *session["stream_epochs"],
                    interval["stream_epoch"],
                ])
            ),
        }
    def classify_gaps(
        self,
        intervals: list[Dict[str, Any]],
        policy: BreakPolicy,
    ) -> Dict[str, Any]:

        result = self.derive_sessions(intervals)

        if not result["gaps"]:
            return result

        interval_by_id = {
            interval["interval_id"]: interval
            for interval in intervals
        }

        for gap in result["gaps"]:
            previous_interval = interval_by_id[
                gap["previous_interval_id"]
            ]

            next_interval = interval_by_id[
                gap["next_interval_id"]
            ]

            classification = policy.classify(
                gap,
                previous_interval,
                next_interval,
            )

            gap["classification"] = classification.value

        return result
session_deriver = SessionDeriver()
