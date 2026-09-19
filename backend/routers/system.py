from fastapi import APIRouter

from backend.services.camera_manager import camera_manager


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
    active_workers = camera_manager.get_active_workers()

    return {
        "backend": "online",
        "active_workers": len(active_workers),
        "active_camera_ids": [
            worker.camera_id
            for worker in active_workers
        ],
    }