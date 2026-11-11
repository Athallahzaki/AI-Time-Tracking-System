from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, Optional

from backend.core.database import get_employee_by_employee_id, save_notification
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
        return self._create_usage_notification(
            violation, "free_time_exceeded", "Batas jatah waktu terlampaui", email=True,
        )

    def create_warning_notification(
        self,
        usage: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Peringatan dini (JAT-05): sekali per karyawan per hari, tanpa email."""
        return self._create_usage_notification(
            usage, "free_time_warning", "Jatah waktu hampir habis", email=False,
        )

    def _create_usage_notification(
        self,
        data: Dict[str, Any],
        notification_type: str,
        title: str,
        email: bool,
    ) -> Optional[Dict[str, Any]]:
        person_id = str(data["person_id"])
        local_date = str(data["date"])
        employee = get_employee_by_employee_id(person_id)
        who = f"{employee['name']} ({person_id})" if employee else person_id

        notification = save_notification(
            # Kunci unik di DB: kejadian yang sama tidak pernah tercatat dua kali.
            dedupe_key=f"{notification_type}:{person_id}:{local_date}",
            person_id=person_id,
            notification_type=notification_type,
            title=title,
            message=(
                f"{who} telah menggunakan "
                f"{float(data['used_seconds']) / 60.0:.2f} menit "
                f"dari jatah "
                f"{float(data['allowance_seconds']) / 60.0:.2f} menit."
            ),
            event_at=float(data["occurred_at"]),
            payload=data,
        )

        # Sudah pernah dibuat -> jangan kirim SSE lagi.
        if notification is None:
            return None

        self.publish(notification)
        if email:
            email_service.enqueue_notification(notification)
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