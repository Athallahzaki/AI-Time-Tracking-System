from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, Optional

from backend.core.database import save_notification
from backend.services.email_service import (
    email_service,
)

class NotificationService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[
            tuple[
                asyncio.AbstractEventLoop,
                asyncio.Queue,
            ]
        ] = []

    def create_violation_notification(
        self,
        violation: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        person_id = str(violation["person_id"])
        local_date = str(violation["date"])

        used_seconds = float(
            violation["used_seconds"]
        )
        allowance_seconds = float(
            violation["allowance_seconds"]
        )

        notification = save_notification(
            dedupe_key=(
                f"free_time_exceeded:"
                f"{person_id}:"
                f"{local_date}"
            ),
            person_id=person_id,
            notification_type="free_time_exceeded",
            title="Batas jatah waktu terlampaui",
            message=(
                f"Person {person_id} telah menggunakan "
                f"{used_seconds / 60.0:.2f} menit "
                f"dari jatah "
                f"{allowance_seconds / 60.0:.2f} menit."
            ),
            event_at=float(
                violation["occurred_at"]
            ),
            payload=violation,
        )

        # Sudah pernah dibuat -> jangan kirim SSE lagi.
        if notification is None:
            return None

        self.publish(notification)

        email_service.enqueue_notification(
            notification
        )

        return notification

    def subscribe_async(
        self,
    ) -> asyncio.Queue:
        loop = asyncio.get_running_loop()

        queue: asyncio.Queue = asyncio.Queue(
            maxsize=100
        )

        with self._lock:
            self._subscribers.append(
                (loop, queue)
            )

        return queue

    def unsubscribe_async(
        self,
        queue: asyncio.Queue,
    ) -> None:
        with self._lock:
            self._subscribers = [
                subscriber
                for subscriber in self._subscribers
                if subscriber[1] is not queue
            ]

    def publish(
        self,
        notification: Dict[str, Any],
    ) -> None:
        with self._lock:
            subscribers = list(
                self._subscribers
            )

        for loop, queue in subscribers:
            loop.call_soon_threadsafe(
                self._offer,
                queue,
                notification,
            )

    @staticmethod
    def _offer(
        queue: asyncio.Queue,
        notification: Dict[str, Any],
    ) -> None:
        # Notification sudah tersimpan di SQLite,
        # jadi jika client sangat lambat kita boleh
        # membuang item SSE paling lama.
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass

        try:
            queue.put_nowait(
                notification
            )
        except asyncio.QueueFull:
            pass


notification_service = NotificationService()