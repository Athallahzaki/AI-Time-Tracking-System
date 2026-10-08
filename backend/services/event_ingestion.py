from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict

from backend.services.violation_service import violation_service
from backend.core.database import save_protocol_event
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
