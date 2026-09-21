from __future__ import annotations

import queue
from threading import Lock
from typing import Any, Dict, Optional


class ViewStreamService:
    def __init__(self) -> None:
        self._lock = Lock()

        self._latest: Dict[
            str,
            Dict[str, Any],
        ] = {}

        self._subscribers: Dict[
            str,
            list[queue.Queue],
        ] = {}

    def publish(
        self,
        message: Dict[str, Any],
    ) -> None:
        if message.get("type") != "view.frame":
            raise ValueError(
                "ViewStreamService only accepts view.frame"
            )

        camera_id = message.get("camera_id")

        if not isinstance(camera_id, str) or not camera_id:
            raise ValueError(
                "view.frame must contain camera_id"
            )

        with self._lock:
            self._latest[camera_id] = message

            subscribers = list(
                self._subscribers.get(
                    camera_id,
                    [],
                )
            )

        for subscriber in subscribers:
            try:
                subscriber.put_nowait(message)

            except queue.Full:
                try:
                    subscriber.get_nowait()
                except queue.Empty:
                    pass

                try:
                    subscriber.put_nowait(message)
                except queue.Full:
                    pass

    def latest(
        self,
        camera_id: str,
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            message = self._latest.get(
                camera_id
            )

            if message is None:
                return None

            return dict(message)

    def subscribe(
        self,
        camera_id: str,
    ) -> queue.Queue:
        subscriber = queue.Queue(
            maxsize=1
        )

        with self._lock:
            self._subscribers.setdefault(
                camera_id,
                [],
            ).append(subscriber)

        return subscriber

    def unsubscribe(
        self,
        camera_id: str,
        subscriber: queue.Queue,
    ) -> None:
        with self._lock:
            subscribers = self._subscribers.get(
                camera_id
            )

            if not subscribers:
                return

            try:
                subscribers.remove(
                    subscriber
                )
            except ValueError:
                return

            if not subscribers:
                self._subscribers.pop(
                    camera_id,
                    None,
                )

    def clear(
        self,
        camera_id: Optional[str] = None,
    ) -> None:
        with self._lock:
            if camera_id is None:
                self._latest.clear()
                return

            self._latest.pop(
                camera_id,
                None,
            )


view_stream_service = ViewStreamService()