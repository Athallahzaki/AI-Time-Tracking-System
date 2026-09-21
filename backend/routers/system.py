from fastapi import APIRouter

from backend.services.engine_client import engine_client


router = APIRouter(
    prefix="/api/system",
    tags=["System"],
)


@router.get("/")
def system_info():
    """
    Basic backend information.
    """
    return {
        "name": "AI Time Tracking System API",
        "version": "2.0.0",
        "status": "online",
    }


@router.get("/status")
def system_status():
    """
    Current backend worker status.
    """
    return {
        "backend": "online",
        "engine": "connected" if engine_client.connected else "disconnected",
        "last_event_seq": engine_client.last_event_seq,
    }
