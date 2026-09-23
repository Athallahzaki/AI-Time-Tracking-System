from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Any, Dict

from backend.core.database import (
    prune_detection_history,
    save_detection_frame,
    set_integration_state,
)
from backend.core.state import system_state
from backend.services.engine_client import EngineClient, engine_client
from backend.services.enrollment_service import enrollment_service
from backend.services.event_ingestion import EventIngestionService, event_ingestion_service
from backend.services.free_time import free_time_ledger
from backend.services.view_stream import ViewStreamService, view_stream_service

logger = logging.getLogger(__name__)


class DetectionWriter:
    """Persists view frames OFF the receiver thread.

    The receiver thread also carries durable events; making it wait on SQLite
    for every overlay frame put backpressure on the channel that must not lag.
    View persistence is best-effort by contract, so a full queue drops frames.
    """

    PRUNE_EVERY_SECONDS = 3600.0

    def __init__(self, max_queue: int = 2000) -> None:
        self._queue: "queue.Queue[tuple[Dict[str, Any], float]]" = queue.Queue(maxsize=max_queue)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.dropped = 0
        self._last_prune = 0.0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="detection-writer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def submit(self, message: Dict[str, Any], observed_at: float) -> None:
        try:
            self._queue.put_nowait((message, observed_at))
        except queue.Full:
            self.dropped += 1

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                message, observed_at = self._queue.get(timeout=0.5)
            except queue.Empty:
                message = None
            if message is not None:
                try:
                    save_detection_frame(message, observed_at=observed_at)
                except Exception:  # noqa: BLE001
                    logger.warning("Failed to persist view frame", exc_info=True)
            now = time.time()
            if now - self._last_prune >= self.PRUNE_EVERY_SECONDS:
                self._last_prune = now
                try:
                    removed = prune_detection_history()
                    if removed:
                        logger.info("Pruned %s old detection frames", removed)
                except Exception:  # noqa: BLE001
                    logger.warning("Detection retention pruning failed", exc_info=True)


detection_writer = DetectionWriter()


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

    def handle_control(self, message: Dict[str, Any]) -> None:
        message_type = message.get("type")
        if message_type == "enroll_result":
            outcome = enrollment_service.handle_protocol_result(message)
            if outcome.get("accepted"):
                from backend.services.engine_connection_manager import engine_connection_manager
                # A new reference exists: tell the engine the roster changed.
                engine_connection_manager.sync_roster()
            return
        if message_type == "ack" and message.get("in_reply_to") == "enroll":
            enrollment_service.handle_rejection_ack(message)
            return
        if message_type == "ack" and message.get("accepted") is False:
            logger.warning("Engine rejected %s: %s", message.get("in_reply_to"), message.get("reason"))

    def handle_replay_gap(self, message: Dict[str, Any]) -> None:
        set_integration_state("engine_replay_gap", json.dumps(message))

    def handle_view(self, message: Dict[str, Any]) -> None:
        enriched = system_state.update_view_frame(message)
        self.view_stream.publish(enriched)
        detection_writer.submit(enriched, observed_at=time.time())

    def handle_event(self, message: Dict[str, Any]) -> None:
        self.ingestion.ingest(message, outbox_id=self.client.outbox_id)

    def configure(self) -> None:
        self.client.set_event_handler(self.handle_event)
        self.client.set_view_handler(self.handle_view)
        self.client.set_control_handler(self.handle_control)
        self.client.set_replay_gap_handler(self.handle_replay_gap)
        self.client.set_outbox_changed_handler(
            lambda _old, _new: free_time_ledger.reset_open_presence()
        )
        free_time_ledger.rebuild_from_database()
        detection_writer.start()


engine_integration = EngineIntegration(
    client=engine_client,
    ingestion=event_ingestion_service,
    view_stream=view_stream_service,
)
