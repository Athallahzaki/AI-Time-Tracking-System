from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from backend.core.config import settings
from backend.core.database import get_enrollments
from backend.services.camera_state import set_cameras_message
from backend.services.engine_client import (
    EngineClient,
    EngineConnectionError,
    OutboxChangedError,
    engine_client,
)

logger = logging.getLogger(__name__)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class EngineConnectionManager:
    """Keeps the backend connected and reconciles declarative state."""

    def __init__(self, client: EngineClient = engine_client) -> None:
        self.client = client
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_warning = ""

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="engine-connector", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.client.close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def sync_roster(self) -> None:
        roster = [
            {"person_id": item["person_id"], "enrollment_version": item["enrollment_version"]}
            for item in get_enrollments()
        ]
        self.client.send({"type": "set_roster", "v": 1, "ts": _timestamp(), "persons": roster})

    def sync_desired_state(self) -> None:
        # Operator overrides (persisted) + cameras.yaml, one function for both paths.
        self.client.send(set_cameras_message())
        self.sync_roster()

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self.client.connected:
                try:
                    self.client.connect()
                    self.client.start_receiver()
                    self.sync_desired_state()
                    self._last_warning = ""
                    logger.info("Connected to engine and reconciled cameras/roster")
                except OutboxChangedError:
                    continue  # reconnect right away with the new outbox cursor
                except EngineConnectionError as exc:
                    text = str(exc)
                    if text != self._last_warning:
                        logger.warning("Engine unavailable: %s", text)
                        self._last_warning = text
                except Exception:  # noqa: BLE001
                    logger.exception("Engine connection/reconciliation failed")
                    self.client.close()
            self._stop.wait(settings.engine_reconnect_seconds)


engine_connection_manager = EngineConnectionManager()
