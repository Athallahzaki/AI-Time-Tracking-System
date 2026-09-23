from __future__ import annotations

import asyncio
import queue
import collections
from threading import Lock
from typing import Any, Dict, Optional


class ViewStreamService:
    def __init__(
        self,
        history_camera_ids: Optional[set[str]] = None,
        max_history_frames: int = 20_000,
    ) -> None:
        self._lock = Lock()

        self._latest: Dict[
            str,
            Dict[str, Any],
        ] = {}

        self._subscribers: Dict[
            str,
            list[queue.Queue],
        ] = {}
        self._history_camera_ids = history_camera_ids or set()
        self._max_history_frames = max_history_frames
        self._history: Dict[str, collections.deque] = {}
        # Async subscribers: (event loop, asyncio.Queue). Delivery hops onto
        # the subscriber's loop, so SSE handlers never park a worker thread.
        self._async_subscribers: Dict[str, list] = {}

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
            if camera_id in self._history_camera_ids:
                history = self._history.setdefault(
                    camera_id,
                    collections.deque(maxlen=self._max_history_frames),
                )
                if history:
                    previous = history[-1]
                    if (
                        previous.get("stream_epoch") != message.get("stream_epoch")
                        or float(message.get("pts") or 0) < float(previous.get("pts") or 0)
                    ):
                        history.clear()
                history.append(message)

            subscribers = list(
                self._subscribers.get(
                    camera_id,
                    [],
                )
            )
            async_subscribers = list(self._async_subscribers.get(camera_id, []))

        for loop, async_queue in async_subscribers:
            try:
                loop.call_soon_threadsafe(_put_latest, async_queue, message)
            except RuntimeError:
                pass  # loop closed; unsubscribe will clean up

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
        replay_history: bool = False,
    ) -> queue.Queue:
        with self._lock:
            replay = (
                list(self._history.get(camera_id, ()))
                if replay_history else []
            )
            subscriber = queue.Queue(maxsize=max(1, len(replay) + 128))
            for message in replay:
                subscriber.put_nowait(message)
            self._subscribers.setdefault(
                camera_id,
                [],
            ).append(subscriber)

        return subscriber

    def subscribe_async(self, camera_id: str, replay_history: bool = False) -> "asyncio.Queue":
        loop = asyncio.get_running_loop()
        with self._lock:
            replay = list(self._history.get(camera_id, ())) if replay_history else []
            async_queue: asyncio.Queue = asyncio.Queue(maxsize=max(1, len(replay) + 128))
            for message in replay:
                async_queue.put_nowait(message)
            self._async_subscribers.setdefault(camera_id, []).append((loop, async_queue))
        return async_queue

    def unsubscribe_async(self, camera_id: str, async_queue: "asyncio.Queue") -> None:
        with self._lock:
            items = self._async_subscribers.get(camera_id, [])
            self._async_subscribers[camera_id] = [i for i in items if i[1] is not async_queue]
            if not self._async_subscribers[camera_id]:
                self._async_subscribers.pop(camera_id, None)

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
                self._history.clear()
                return

            self._latest.pop(
                camera_id,
                None,
            )
            self._history.pop(camera_id, None)


def _put_latest(async_queue: "asyncio.Queue", message: Dict[str, Any]) -> None:
    """Drop the oldest frame when a slow browser falls behind."""
    if async_queue.full():
        try:
            async_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    try:
        async_queue.put_nowait(message)
    except asyncio.QueueFull:
        pass


from backend.core.config import settings

view_stream_service = ViewStreamService(
    history_camera_ids={
        camera_id
        for camera_id, camera in settings.cameras.items()
        if camera.stream_url.lower().split("?", 1)[0].endswith(".mp4")
    }
)
