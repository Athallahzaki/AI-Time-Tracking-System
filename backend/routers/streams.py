from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

from backend.services.camera_manager import camera_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Streams"])


@router.get("/api/detections/stream")
async def detections_sse_stream(
    request: Request,
    camera_id: Optional[str] = Query(None, description="Camera ID to stream from (default: primary camera or all active)"),
):
    """Server-Sent Events (SSE) streaming real-time bounding boxes, identities, and presence status."""
    # Find target camera worker or default to first available
    worker = None
    if camera_id:
        worker = camera_manager.get_worker(camera_id)
        if not worker:
            # Auto-start worker if configured
            camera_manager.start_worker(camera_id)
            worker = camera_manager.get_worker(camera_id)
    else:
        active_workers = camera_manager.get_active_workers()
        if active_workers:
            worker = active_workers[0]
        else:
            # Start primary camera
            camera_manager.start_worker("cam-01")
            worker = camera_manager.get_worker("cam-01")

    if not worker:
        raise HTTPException(status_code=503, detail="No active AI Vision Engine worker available.")

    client_queue = worker.subscribe()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break

                try:
                    data = await asyncio.to_thread(client_queue.get, True, 1.0)
                    yield {
                        "event": "detection",
                        "data": json.dumps(data),
                    }
                except Exception:
                    # Timeout / empty queue heartbeat
                    continue
        finally:
            worker.unsubscribe(client_queue)

    return EventSourceResponse(event_generator())


@router.get("/api/cameras/{camera_id}/snapshot")
def get_camera_snapshot(camera_id: str):
    """Returns the latest processed frame as a JPEG image."""
    worker = camera_manager.get_worker(camera_id)
    if not worker:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' is not active.")

    jpeg_bytes = worker.get_latest_jpeg()
    if not jpeg_bytes:
        raise HTTPException(status_code=503, detail="No frame captured yet.")

    return Response(content=jpeg_bytes, media_type="image/jpeg")


@router.get("/api/cameras/{camera_id}/live-feed")
async def get_camera_mjpeg_stream(request: Request, camera_id: str):
    """Multipart MJPEG video stream from the AI Vision Engine."""
    worker = camera_manager.get_worker(camera_id)
    if not worker:
        camera_manager.start_worker(camera_id)
        worker = camera_manager.get_worker(camera_id)

    if not worker:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found.")

    async def mjpeg_generator():
        last_frame = None
        while True:
            if await request.is_disconnected():
                break

            frame_bytes = worker.get_latest_jpeg()
            if frame_bytes and frame_bytes != last_frame:
                last_frame = frame_bytes
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
                )
            await asyncio.sleep(0.033)  # ~30 FPS throttling

    return StreamingResponse(
        mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
