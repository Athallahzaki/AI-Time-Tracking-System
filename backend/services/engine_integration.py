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

from backend.core.database import set_integration_state

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
        
    def configure(self) -> None:
        self.client.set_event_handler(
            self.ingestion.ingest
        )

        self.client.set_view_handler(
            self.view_stream.publish
        )

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


engine_integration = EngineIntegration(
    client=engine_client,
    ingestion=event_ingestion_service,
    view_stream=view_stream_service,
)