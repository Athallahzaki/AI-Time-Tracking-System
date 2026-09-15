from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Query
from backend.core.state import system_state

router = APIRouter(prefix="/api/attendance", tags=["Attendance"])


@router.get("/active")
def get_active_sessions():
    """Returns all currently active person presence sessions across all cameras."""
    sessions = system_state.get_active_sessions()
    return {
        "status": "success",
        "count": len(sessions),
        "sessions": sessions,
    }


@router.get("/events")
def get_recent_events(limit: int = Query(50, ge=1, le=200)):
    """Returns recent attendance and identity events log."""
    events = system_state.get_recent_events(limit=limit)
    return {
        "status": "success",
        "count": len(events),
        "events": events,
    }


@router.get("/summary")
def get_attendance_summary():
    """Returns a presence status breakdown for active persons."""
    sessions = system_state.get_active_sessions()
    breakdown = {
        "PASSING": 0,
        "CONFIRMED": 0,
        "WARNING": 0,
        "LIMIT": 0,
    }
    for sess in sessions:
        status = sess.get("presence_status", "PASSING")
        if status in breakdown:
            breakdown[status] += 1
        else:
            breakdown[status] = 1

    return {
        "status": "success",
        "total_active": len(sessions),
        "breakdown": breakdown,
    }
