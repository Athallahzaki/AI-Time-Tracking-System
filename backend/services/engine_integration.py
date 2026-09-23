from __future__ import annotations

from backend.services.engine_client import (
    EngineClient,
    engine_client,
)
from backend.services.enrollment_service import (
    enrollment_service,
)
from backend.services.event_ingestion import (
    EventIngestionService,
    event_ingestion_service,
)
from backend.services.view_stream import (
    ViewStreamService,
    view_stream_service,
)

import json
import time

from backend.core.database import save_detection_frame, set_integration_state
from backend.core.state import system_state

class EngineIntegration:
    def __init__(
        self,
        client: EngineClient,
        ingestion: EventIngestionService,
        view_stream: ViewStreamService,
    ) -> None:
        self.client = client
        self.ingestion = ingestion
        self.view_stream = view_stream

    def handle_control(
        self,
        message,
    ) -> None:
        message_type = message.get("type")

        if message_type == "enroll_result":
            enrollment_service.handle_protocol_result(
                message
            )
            return

        if message_type == "replay_gap":
            set_integration_state(
                "engine_replay_gap",
                json.dumps(message),
            )
            return

    def handle_view(self, message) -> None:
        """Feed the same real-engine frame into backend state and browser SSE."""
        enriched = system_state.update_view_frame(message)
        save_detection_frame(enriched, observed_at=time.time())
        self.view_stream.publish(enriched)
        
    def configure(self) -> None:
        self.client.set_event_handler(
            self.ingestion.ingest
        )

        self.client.set_view_handler(self.handle_view)

        # Real EngineClient supports control messages.
        # Older test doubles may not implement this yet.
        set_control_handler = getattr(
            self.client,
            "set_control_handler",
            None,
        )

        if callable(set_control_handler):
            set_control_handler(
                self.handle_control
            )

        set_replay_gap_handler = getattr(self.client, "set_replay_gap_handler", None)
        if callable(set_replay_gap_handler):
            set_replay_gap_handler(self.handle_control)


engine_integration = EngineIntegration(
    client=engine_client,
    ingestion=event_ingestion_service,
    view_stream=view_stream_service,
)
