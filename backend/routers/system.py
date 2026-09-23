from fastapi import APIRouter, Query

from backend.core.database import get_dead_letters, get_integration_state
from backend.services.detection_stats import writer_stats
from backend.services.engine_client import engine_client

router = APIRouter(prefix="/api/system", tags=["System"])


@router.get("/")
def system_info():
    return {"name": "AI Time Tracking System API", "version": "2.1.0", "status": "online"}


@router.get("/status")
def system_status():
    return {
        "backend": "online",
        "engine": "connected" if engine_client.connected else "disconnected",
        "engine_outbox_id": engine_client.outbox_id or None,
        "last_event_seq": engine_client.last_event_seq,
        "last_replay_gap": get_integration_state("engine_replay_gap", "") or None,
        "view_frames_dropped_before_storage": writer_stats()["dropped"],
    }


@router.get("/dead-letters")
def dead_letters(limit: int = Query(100, ge=1, le=1000)):
    """Durable events the backend could not process. Never silently discarded."""
    items = get_dead_letters(limit)
    return {"status": "success", "count": len(items), "dead_letters": items}
