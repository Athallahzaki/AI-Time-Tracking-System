from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from backend.core.database import save_protocol_event
from backend.core.state import system_state
from backend.services.free_time import free_time_ledger
from backend.services.protocol_adapter import protocol_adapter


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
            system_state.record_event(event_type, validated)
        return inserted


event_ingestion_service = EventIngestionService()
