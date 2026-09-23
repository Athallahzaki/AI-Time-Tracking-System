from __future__ import annotations

from datetime import date as date_type, datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.core.database import get_corrections, save_correction
from backend.core.security import require_api_key
from backend.core.state import system_state
from backend.schemas.corrections import CorrectionCreate
from backend.services.break_policy import break_policy
from backend.services.free_time import free_time_ledger

router = APIRouter(prefix="/api/attendance", tags=["Attendance"])

# new_classification values that mean "this visit was not free time".
EXCLUDING_CLASSIFICATIONS = {
    "tracking_loss", "camera_failure", "system_event", "official_break",
    "not_free_time", "misidentified",
}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def _target_date(value: Optional[str]) -> str:
    target = value or datetime.now(break_policy.timezone).date().isoformat()
    try:
        date_type.fromisoformat(target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date must use YYYY-MM-DD") from exc
    return target


def _usage_payload(person_id: str, target_date: str) -> Dict[str, Any]:
    """Frontend `BreakUsage` shape. `breaks` now lists facility VISITS."""
    usage = free_time_ledger.usage(person_id, target_date)
    used_minutes = usage["used_seconds"] / 60.0
    entries = [
        {
            "gap_id": visit["visit_id"],
            "start_at": _iso(visit["start_ts"]),
            "end_at": _iso(visit["end_ts"]),
            "duration_seconds": visit["charged_seconds"],
            "countable_seconds": visit["countable_seconds"],
            "camera_id": ",".join(visit["cameras"]),
            "end_zone": "",
            "end_reason": "open" if visit["open"] else "closed",
            "corrected": visit["excluded"],
            "original_duration_seconds": (
                visit["original_charged_seconds"] if visit["excluded"] else None
            ),
        }
        for visit in usage["visits"]
    ]
    return {
        "person_id": person_id,
        "date": target_date,
        "timezone": break_policy.timezone_name,
        "allowance_minutes": break_policy.daily_allowance_minutes,
        "used_minutes": round(used_minutes, 2),
        "remaining_minutes": round(usage["remaining_seconds"] / 60.0, 2),
        "adjustment_minutes": round(usage["adjustment_seconds"] / 60.0, 2),
        "break_count": sum(1 for visit in usage["visits"] if visit["charged_seconds"] > 0),
        "breaks": entries,
        "suspicious_gap_count": 0,
        "present": usage["present"],
        "status": usage["status"],
    }


@router.get("/active")
def get_active_sessions():
    """Live tracks on screen (display), with allowance fields from the ledger."""
    sessions = system_state.get_active_sessions()
    return {"status": "success", "count": len(sessions), "sessions": sessions}


@router.post("/corrections", dependencies=[Depends(require_api_key)])
def create_manual_correction(req: CorrectionCreate):
    """Append-only. Recorded AND applied to the allowance calculation."""
    if req.new_classification is not None and req.new_classification not in EXCLUDING_CLASSIFICATIONS:
        raise HTTPException(status_code=400, detail="Invalid classification")
    exclude_visit = req.gap_id is not None and req.new_classification is not None
    if (exclude_visit or req.adjustment_minutes is not None) and not req.person_id:
        raise HTTPException(status_code=400, detail="person_id is required to change the allowance")
    target_date = _target_date(req.date) if req.person_id else req.date
    if exclude_visit:
        visits = free_time_ledger.usage(req.person_id, target_date)["visits"]
        if not any(v["visit_id"] == req.gap_id for v in visits):
            raise HTTPException(status_code=404, detail="Visit not found for that person/date")

    payload = {
        "correction_id": f"cor_{uuid4().hex}",
        "person_id": req.person_id,
        "date": target_date,
        "session_id": req.session_id,
        "gap_id": req.gap_id,
        "corrected_by": req.corrected_by,
        "corrected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reason": req.reason,
        "new_classification": req.new_classification,
        "adjustment_minutes": req.adjustment_minutes,
        "adjustment_seconds": (req.adjustment_minutes * 60.0) if req.adjustment_minutes else None,
        "exclude_visit": exclude_visit,
        "notes": req.notes or "",
    }
    save_correction(payload)
    free_time_ledger.invalidate()
    system_state.record_event("ManualCorrectionEvent", payload)
    return {"status": "success", "message": "Manual correction recorded", "correction": payload}


@router.get("/corrections")
def list_corrections(person_id: Optional[str] = None, date: Optional[str] = None,
                     limit: int = Query(200, ge=1, le=1000)):
    return {"status": "success", "corrections": get_corrections(person_id, date, limit)}


@router.get("/derived")
def get_derived_attendance(person_id: Optional[str] = None, date: Optional[str] = None):
    """Per-person facility visits for one local date (merged across cameras)."""
    target_date = _target_date(date)
    person_ids = [person_id] if person_id else sorted(free_time_ledger.known_person_ids())
    people = {pid: free_time_ledger.usage(pid, target_date) for pid in person_ids}
    return {"status": "success", "date": target_date, "people": people}


@router.get("/break-usage")
def get_break_usage(person_id: str, date: Optional[str] = None):
    """Daily free-time usage for one person (time present in the facility)."""
    return _usage_payload(person_id, _target_date(date))


@router.get("/breaks")
def get_all_break_usage(date: Optional[str] = None):
    """Daily free-time usage for every known person."""
    target_date = _target_date(date)
    data = [_usage_payload(pid, target_date) for pid in sorted(free_time_ledger.known_person_ids())]
    return {"status": "success", "data": data}


@router.get("/events")
def get_recent_events(limit: int = Query(50, ge=1, le=200)):
    """Recent events; manual corrections are read from the database so the
    audit log survives backend restarts."""
    events = [e for e in system_state.get_recent_events(limit=limit)
              if e["type"] != "ManualCorrectionEvent"]
    for correction in get_corrections(limit=limit):
        events.append({
            "timestamp": correction.pop("_created_at", 0.0),
            "type": "ManualCorrectionEvent",
            "payload": correction,
        })
    events.sort(key=lambda e: e["timestamp"])
    events = events[-limit:]
    return {"status": "success", "count": len(events), "events": events}


@router.get("/summary")
def get_attendance_summary():
    sessions = system_state.get_active_sessions()
    breakdown: Dict[str, int] = {"VERIFYING": 0, "CONFIRMED": 0, "WARNING": 0, "LIMIT": 0}
    for sess in sessions:
        status = sess.get("presence_status", "VERIFYING")
        breakdown[status] = breakdown.get(status, 0) + 1
    return {"status": "success", "total_active": len(sessions), "breakdown": breakdown}
