from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.core.database import (
    get_employee_by_id, get_hr_reviews, get_review_decision, save_review_decision,
    apply_attribution_review, mark_report_dirty,
)
from backend.core.security import require_admin
from backend.services.break_policy import break_policy
from backend.services.free_time import free_time_ledger
from backend.routers.reports import _segments

router = APIRouter(prefix="/api/reviews", tags=["HR Review"], dependencies=[Depends(require_admin)])


class DecisionRequest(BaseModel):
    decision: str
    note: str | None = None


def _item(record):
    employee = get_employee_by_id(record["employee_internal_id"]) if record.get("employee_internal_id") else None
    if employee is None:
        return None
    report_date = datetime.fromtimestamp(record["attributed_at"], break_policy.timezone).date().isoformat()
    review_id = f"{employee['id']}:{report_date}"
    usage = free_time_ledger.usage(str(employee["employee_id"]), report_date)
    decision = get_review_decision(review_id)
    return {
        "id": review_id, "date": report_date, "employee_uid": str(employee["id"]),
        "employee_id": employee["employee_id"], "name": employee["name"],
        "used_seconds": usage["used_seconds"], "allowance_seconds": usage["allowance_seconds"],
        "reid_seconds": usage["used_seconds"], "visits": len(usage["visits"]),
        "status": decision["status"] if decision else "pending",
        "decided_by": decision["decided_by"] if decision else None,
        "decided_at": decision["decided_at"] if decision else None,
        "note": decision["note"] if decision else None,
    }


def _items():
    result = {}
    for record in get_hr_reviews(unresolved_only=False):
        item = _item(record)
        if item:
            result[item["id"]] = item
    return list(result.values())


@router.get("")
def list_reviews(status: str = "pending", from_: str | None = Query(None, alias="from"), to: str | None = None):
    items = [item for item in _items() if (status == "all" or item["status"] == status)]
    if from_:
        items = [item for item in items if item["date"] >= from_]
    if to:
        items = [item for item in items if item["date"] <= to]
    return {"items": items}


@router.get("/{review_id}")
def get_review(review_id: str):
    item = next((item for item in _items() if item["id"] == review_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Review not found")
    employee = get_employee_by_id(int(item["employee_uid"]))
    return {**item, "segments": _segments(employee, item["date"])}


@router.post("/{review_id}/decision")
def decide_review(review_id: str, req: DecisionRequest, admin=Depends(require_admin)):
    if req.decision not in {"confirm", "reject"}:
        raise HTTPException(status_code=400, detail="decision must be confirm or reject")
    item = next((item for item in _items() if item["id"] == review_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Review not found")
    save_review_decision(review_id, "confirmed" if req.decision == "confirm" else "rejected",
                         admin["username"], req.note)
    employee_uid, report_date = review_id.split(":", 1)
    start, end = break_policy.day_bounds(report_date)
    apply_attribution_review(int(employee_uid), start, end, req.decision == "confirm", admin["username"])
    free_time_ledger.invalidate()
    mark_report_dirty(report_date)
    return next(item for item in _items() if item["id"] == review_id)
