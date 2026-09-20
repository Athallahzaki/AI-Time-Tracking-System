from __future__ import annotations

import asyncio
import json
import queue
from typing import Optional

from fastapi import APIRouter, Query, Request
from sse_starlette.sse import EventSourceResponse

from backend.services.view_stream import (
    view_stream_service,
)


router = APIRouter(tags=["Streams"])


@router.get("/api/detections/stream")
async def detections_sse_stream(
    request: Request,
    camera_id: Optional[str] = Query(
        "cam-01",
        description="Camera ID to stream from",
    ),
):
    """
    SSE stream for engine view.frame messages.
    """

    selected_camera = (
        camera_id or "cam-01"
    )

    client_queue = (
        view_stream_service.subscribe(
            selected_camera
        )
    )

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break

                try:
                    frame = await asyncio.to_thread(
                        client_queue.get,
                        True,
                        1.0,
                    )

                except queue.Empty:
                    continue

                yield {
                    "event": "detection",
                    "data": json.dumps(frame),
                }

        finally:
            view_stream_service.unsubscribe(
                selected_camera,
                client_queue,
            )

    return EventSourceResponse(
        event_generator()
    )