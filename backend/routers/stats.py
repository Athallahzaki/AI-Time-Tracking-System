from __future__ import annotations

from fastapi import APIRouter
from backend.core.state import system_state
from backend.services.camera_manager import camera_manager

router = APIRouter(prefix="/api/stats", tags=["Stats"])


@router.get("")
def get_dashboard_stats():
    """Returns aggregated real-time statistics for the dashboard StatsRow component."""
    total_cameras = len(camera_manager.get_camera_list())
    stats = system_state.get_dashboard_stats(total_facilities=total_cameras)
    return {
        "status": "success",
        "data": stats,
    }
