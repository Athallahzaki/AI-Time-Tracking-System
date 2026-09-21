from __future__ import annotations

from fastapi import APIRouter
from backend.core.config import settings
from backend.core.state import system_state

router = APIRouter(prefix="/api/stats", tags=["Stats"])


@router.get("")
def get_dashboard_stats():
    """Returns aggregated real-time statistics for the dashboard StatsRow component."""
    total_cameras = len(settings.cameras)
    stats = system_state.get_dashboard_stats(total_facilities=total_cameras)
    return {
        "status": "success",
        "data": stats,
    }
