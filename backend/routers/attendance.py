from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
import time


from fastapi import APIRouter, HTTPException, Query

from backend.core.database import get_protocol_events
from backend.core.state import system_state
from backend.schemas.attendance import GapClassification
from backend.schemas.corrections import CorrectionCreate
from backend.services.break_policy import break_policy
from backend.services.session_deriver import session_deriver


router = APIRouter(
    prefix="/api/attendance",
    tags=["Attendance"],
)


@router.get("/active")
def get_active_sessions():
    """Returns all currently active person presence sessions across all cameras."""

    sessions = system_state.get_active_sessions()

    return {
        "status": "success",
        "count": len(sessions),
        "sessions": sessions,
    }


@router.post("/corrections")
def create_manual_correction(req: CorrectionCreate):
    """
    Records a manual correction as a new event.

    Corrections are append-only and do not overwrite
    the original attendance data.
    """

    # Validate gap classification when supplied.
    if req.new_classification is not None:
        valid_classifications = {
            item.value
            for item in GapClassification
        }

        if req.new_classification not in valid_classifications:
            raise HTTPException(
                status_code=400,
                detail="Invalid gap classification",
            )

    correction_id = f"cor_{uuid4().hex}"

    corrected_at = (
        datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )

    payload = {
        "correction_id": correction_id,
        "session_id": req.session_id,
        "gap_id": req.gap_id,
        "corrected_by": req.corrected_by,
        "corrected_at": corrected_at,
        "reason": req.reason,
        "new_classification": req.new_classification,
        "adjustment_minutes": req.adjustment_minutes,
        "notes": req.notes,
    }

    # Append-only:
    # original event/session is not deleted or overwritten.
    system_state.record_event(
        "ManualCorrectionEvent",
        payload,
    )

    return {
        "status": "success",
        "message": "Manual correction recorded",
        "correction": payload,
    }


@router.get("/derived")
def get_derived_attendance(person_id: str | None = None):
    intervals = [item["payload"] for item in get_protocol_events("presence.interval")]
    if person_id is not None:
        intervals = [item for item in intervals if item.get("person_id") == person_id]
    grouped: dict[str, list[dict]] = {}
    for interval in intervals:
        grouped.setdefault(interval["person_id"], []).append(interval)
    people = {}
    for current_person_id, person_intervals in grouped.items():
        person_intervals.sort(key=lambda item: item["start_at"])
        people[current_person_id] = session_deriver.classify_gaps(person_intervals, break_policy)
    return {"status": "success", "people": people, "interval_count": len(intervals)}


@router.get("/events")
def get_recent_events(
    limit: int = Query(
        50,
        ge=1,
        le=200,
    ),
):
    """Returns recent attendance and identity events log."""

    events = system_state.get_recent_events(
        limit=limit,
    )

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
        status = sess.get(
            "presence_status",
            "PASSING",
        )

        if status in breakdown:
            breakdown[status] += 1
        else:
            breakdown[status] = 1

    return {
        "status": "success",
        "total_active": len(sessions),
        "breakdown": breakdown,
    }
