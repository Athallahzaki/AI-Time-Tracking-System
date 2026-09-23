from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from backend.core.config import settings
from backend.core.database import get_detection_observations
from backend.services.view_stream import view_stream_service

router = APIRouter(tags=["Streams"])


@router.get("/api/detections/history")
def detections_history(
    camera_id: str | None = None,
    person_id: str | None = None,
    limit: int = Query(500, ge=1, le=5000),
):
    data = get_detection_observations(camera_id, person_id, limit)
    return {"status": "success", "count": len(data), "detections": data}


@router.get("/api/detections/stream")
async def detections_sse_stream(
    request: Request,
    camera_id: Optional[str] = Query(None, description="Camera ID (default: first configured)"),
    replay: bool = Query(False, description="Replay buffered PTS frames for direct MP4 sync"),
):
    """SSE stream for engine view.frame messages (no worker thread per client)."""
    selected_camera = camera_id or next(iter(settings.cameras), None)
    if selected_camera is None or selected_camera not in settings.cameras:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")

    client_queue = view_stream_service.subscribe_async(selected_camera, replay_history=replay)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    frame = await asyncio.wait_for(client_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                yield {"event": "detection", "data": json.dumps(frame)}
        finally:
            view_stream_service.unsubscribe_async(selected_camera, client_queue)

    return EventSourceResponse(event_generator())
