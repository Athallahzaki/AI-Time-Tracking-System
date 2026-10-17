from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    Query,
    Request,
)

from sse_starlette.sse import EventSourceResponse

from backend.core.database import (
    get_notifications,
    get_notification,
    mark_notification_read,
)
from backend.core.security import require_stream_user, require_user, scoped_person_id
from fastapi import HTTPException
from backend.services.notification_service import (
    notification_service,
)


router = APIRouter(
    prefix="/api/notifications",
    tags=["Notifications"],
)


@router.get("")
def list_notifications(
    person_id: Optional[str] = None,
    unread_only: bool = False,
    limit: int = Query(
        default=200,
        ge=1,
        le=1000,
    ),
    user=Depends(require_user),
):
    person_id = scoped_person_id(user, person_id)
    notifications = get_notifications(
        person_id=person_id,
        unread_only=unread_only,
        limit=limit,
    )

    return {
        "status": "success",
        "count": len(notifications),
        "notifications": notifications,
    }


@router.get("/stream")
async def notification_stream(
    request: Request,
    user=Depends(require_stream_user),
):
    queue = notification_service.subscribe_async()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break

                try:
                    notification = await asyncio.wait_for(
                        queue.get(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    continue

                own = scoped_person_id(user)
                if own and str(notification.get("person_id") or "") != own:
                    continue

                yield {
                    "event": "notification",
                    "data": json.dumps(
                        notification
                    ),
                }

        finally:
            notification_service.unsubscribe_async(
                queue
            )

    return EventSourceResponse(
        event_generator()
    )


@router.patch(
    "/{notification_id}/read",
)
def read_notification(
    notification_id: int,
    user=Depends(require_user),
):
    notification = get_notification(notification_id)
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    scoped_person_id(user, str(notification.get("person_id") or ""))
    changed = mark_notification_read(
        notification_id
    )

    return {
        "status": "success",
        "notification_id": notification_id,
        "changed": changed,
    }
