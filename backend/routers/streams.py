from __future__ import annotations

import asyncio
import json
import logging
import queue
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from backend.services.camera_manager import camera_manager


logger = logging.getLogger(__name__)

router = APIRouter(tags=["Streams"])


@router.get("/api/detections/stream")
async def detections_sse_stream(
    request: Request,
    camera_id: Optional[str] = Query(
        None,
        description=(
            "Camera ID to stream from "
            "(default: primary camera or all active)"
        ),
    ),
):
    """
    SSE stream for real-time detection data.
    """

    worker = None

    if camera_id:
        worker = camera_manager.get_worker(camera_id)

        if not worker:
            camera_manager.start_worker(camera_id)
            worker = camera_manager.get_worker(camera_id)

    else:
        active_workers = camera_manager.get_active_workers()

        if active_workers:
            worker = active_workers[0]

        else:
            configured = camera_manager.get_configured_cameras()

            first_cam_id = next(
                iter(configured.keys()),
                "cam-01",
            )

            camera_manager.start_worker(first_cam_id)
            worker = camera_manager.get_worker(first_cam_id)

    if not worker:
        raise HTTPException(
            status_code=503,
            detail="No active AI Vision Engine worker available.",
        )

    client_queue = worker.subscribe()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break

                try:
                    data = await asyncio.to_thread(
                        client_queue.get,
                        True,
                        1.0,
                    )

                    yield {
                        "event": "detection",
                        "data": json.dumps(data),
                    }

                except queue.Empty:
                    continue

        finally:
            worker.unsubscribe(client_queue)

    return EventSourceResponse(event_generator())