from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.core.database import get_employee_by_employee_id
from backend.core.security import require_user, scoped_person_id
from backend.services.break_policy import break_policy
from backend.services.free_time import free_time_ledger

router = APIRouter(prefix="/api/me", tags=["My Account"])


@router.get("/usage-today")
def usage_today(user=Depends(require_user)):
    person_id = scoped_person_id(user)
    if person_id is None:
        raise HTTPException(status_code=400, detail="Admin account has no employee usage scope")
    employee = get_employee_by_employee_id(person_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Linked employee not found")
    usage = free_time_ledger.usage(person_id)
    locations = {}
    first_seen = None
    for visit in usage["visits"]:
        for camera in visit.get("cameras", []):
            locations[camera] = locations.get(camera, 0) + visit["charged_seconds"] / max(1, len(visit.get("cameras", [])))
        if first_seen is None or visit["start_ts"] < first_seen:
            first_seen = visit["start_ts"]
    from datetime import datetime, timezone
    return {
        "date": usage["date"], "employee_id": employee["employee_id"], "name": employee["name"],
        "used_seconds": usage["used_seconds"], "allowance_seconds": usage["allowance_seconds"],
        "remaining_seconds": usage["remaining_seconds"],
        "status": "safe" if usage["status"] == "ok" else usage["status"],
        "by_location": [{"location": key, "seconds": round(value, 3)} for key, value in locations.items()],
        "visits": len(usage["visits"]),
        "first_seen_at": datetime.fromtimestamp(first_seen, timezone.utc).isoformat().replace("+00:00", "Z") if first_seen else None,
    }
