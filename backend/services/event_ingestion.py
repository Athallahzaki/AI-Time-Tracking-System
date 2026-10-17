from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict

from backend.services.violation_service import violation_service
from backend.core.database import (
    get_track_history, mark_report_dirty, save_attribution, save_protocol_event,
)
from backend.core.database import get_employee_by_employee_id
from backend.services.break_policy import break_policy
from backend.core.state import system_state
from backend.services.free_time import free_time_ledger
from backend.services.protocol_adapter import protocol_adapter

logger = logging.getLogger(__name__)


def _timestamp(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


class EventIngestionService:
    def ingest(self, message: Dict[str, Any], outbox_id: str = "") -> bool:
        validated = protocol_adapter.validate(message, expected_channel="events")

        seq = validated.get("seq")
        if not isinstance(seq, int):
            raise ValueError("Protocol event must contain integer seq")
        event_type = validated.get("type")
        if not isinstance(event_type, str):
            raise ValueError("Protocol event must contain type")

        event_time = validated.get("at")
        if not isinstance(event_time, str):
            event_time = validated.get("ts")
        if not isinstance(event_time, str):
            raise ValueError("Protocol event must contain at or ts")

        inserted = save_protocol_event(
            timestamp=_timestamp(event_time),
            event_type=event_type,
            payload=validated,
            seq=seq,
            outbox_id=outbox_id,
        )
        if inserted:
            local_date = datetime.fromtimestamp(_timestamp(event_time), break_policy.timezone).date().isoformat()
            mark_report_dirty(local_date)
            if event_type == "track.identity_changed":
                target = validated.get("to_person_id")
                employee = get_employee_by_employee_id(str(target or ""))
                track_uuid = str(validated.get("track_uuid") or "")
                history = get_track_history(track_uuid, _timestamp(event_time)) if track_uuid else []
                cameras = {item["payload"].get("camera_id") for item in history if item["payload"].get("camera_id")}
                previous = validated.get("from_person_id")
                conflicting = previous not in (None, "", target)
                ambiguous_camera = len(cameras) > 1
                review_reason = None
                if employee is None:
                    review_reason = "missing_employee"
                elif conflicting:
                    review_reason = "conflicting_identity"
                elif ambiguous_camera:
                    review_reason = "ambiguous_reid"
                elif not history:
                    review_reason = "insufficient_evidence"
                needs_review = review_reason is not None
                window_start = min((item["timestamp"] for item in history), default=_timestamp(event_time))
                save_attribution({
                    "event_outbox_id": outbox_id,
                    "event_seq": seq,
                    "original_person_id": validated.get("from_person_id"),
                    "employee_internal_id": employee.get("id") if employee else None,
                    "attribution_source": "identity_changed",
                    "attribution_confidence": 1.0 if not needs_review else 0.5,
                    "needs_hr_review": needs_review,
                    "review_reason": review_reason,
                    "track_uuid": track_uuid or None,
                    "camera_id": next(iter(cameras)) if len(cameras) == 1 else validated.get("camera_id"),
                    "window_start": window_start,
                    "window_end": _timestamp(event_time),
                    "evidence": [
                        {"type": item["type"], "timestamp": item["timestamp"]}
                        for item in history
                    ] + [{"type": "track.identity_changed", "seq": seq}],
                })
                if employee is not None:
                    mark_report_dirty(datetime.fromtimestamp(window_start, break_policy.timezone).date().isoformat())
            free_time_ledger.apply_event(validated)

            # Event sudah tersimpan dan sudah masuk ledger. Kegagalan menilai
            # pelanggaran (DB, notifikasi) tidak boleh membuat event itu
            # dicatat sebagai dead letter oleh engine_client, dan tidak boleh
            # melewatkan record_event di bawah.
            try:
                violation_service.evaluate_event(validated)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Evaluasi pelanggaran gagal untuk %s seq=%s", event_type, seq
                )

            system_state.record_event(
                event_type,
                validated,
            )
        return inserted

event_ingestion_service = EventIngestionService()
