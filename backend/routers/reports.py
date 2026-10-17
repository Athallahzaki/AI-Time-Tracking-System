from __future__ import annotations

from datetime import date, timedelta, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from backend.core.database import get_employees, get_hr_reviews, get_presence_intervals
from backend.core.security import require_admin, require_user, scoped_person_id
from backend.services.break_policy import break_policy
from backend.services.free_time import free_time_ledger
from backend.services.report_service import _xlsx, report_service

router = APIRouter(prefix="/api/reports", tags=["Reports"], dependencies=[Depends(require_user)])


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date must use YYYY-MM-DD") from exc


def _range(start: str, end: str):
    first, last = _date(start), _date(end)
    if last < first or (last - first).days >= 31:
        raise HTTPException(status_code=400, detail="report range must be 1-31 days")
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def _segments(employee, report_date):
    start, end = break_policy.day_bounds(report_date)
    result = []
    for item in get_presence_intervals(start, end, str(employee["employee_id"])):
        start_at = item.get("start_at")
        end_at = item.get("end_at")
        start_ts = datetime.fromisoformat(start_at.replace("Z", "+00:00")).timestamp() if start_at else start
        end_ts = datetime.fromisoformat(end_at.replace("Z", "+00:00")).timestamp() if end_at else min(end, datetime.now(timezone.utc).timestamp())
        result.append({
            "visit_id": item.get("visit_id") or f"{item.get('track_uuid', 'track')}:{start_ts}",
            "camera_id": item.get("camera_id") or "unknown", "location": item.get("camera_id") or "Unknown",
            "start": start_at, "end": end_at, "seconds": max(0, end_ts - start_ts),
            "identity_source": item.get("identity_source") or "tracking",
        })
    return result


def _rows(start, end, user, division=None, employee_uid=None, status=None):
    own = scoped_person_id(user)
    review_employee_ids = {item.get("employee_internal_id") for item in get_hr_reviews(unresolved_only=True)}
    rows = []
    for employee in get_employees():
        if own and str(employee["employee_id"]) != own:
            continue
        if division and employee.get("division") != division:
            continue
        if employee_uid and str(employee["id"]) != str(employee_uid):
            continue
        for report_date in _range(start, end):
            usage = free_time_ledger.usage(str(employee["employee_id"]), report_date)
            segments = _segments(employee, report_date)
            if not usage["visits"] and not segments:
                continue
            by_location = {}
            reid_seconds = 0.0
            first_seen = None
            for segment in segments:
                by_location[segment["location"]] = by_location.get(segment["location"], 0) + segment["seconds"]
                if str(segment["identity_source"]).startswith("reid"):
                    reid_seconds += segment["seconds"]
                if segment["start"] and (first_seen is None or segment["start"] < first_seen):
                    first_seen = segment["start"]
            row = {
                "date": report_date, "employee_uid": str(employee["id"]), "employee_id": employee["employee_id"],
                "name": employee["name"], "division": employee.get("division"), "used_seconds": usage["used_seconds"],
                "allowance_seconds": usage["allowance_seconds"], "remaining_seconds": usage["remaining_seconds"],
                "visits": len(usage["visits"]), "status": "safe" if usage["status"] == "ok" else usage["status"],
                "reid_seconds": round(reid_seconds, 3),
                "needs_review": employee["id"] in review_employee_ids, "first_seen_at": first_seen,
                "by_location": [{"location": key, "seconds": round(value, 3)} for key, value in by_location.items()],
            }
            if status and row["status"] != status:
                continue
            rows.append(row)
    rows.sort(key=lambda item: (item["date"], item["employee_id"]), reverse=True)
    return rows


@router.get("")
def list_reports(_user=Depends(require_user)):
    return {"status": "success", "runs": report_service.list_runs()}


@router.get("/daily")
def daily_report(from_: str = Query(..., alias="from"), to: str = Query(...), division: str | None = None,
                 employee_uid: str | None = None, status: str | None = None,
                 page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=100000),
                 user=Depends(require_user)):
    rows = _rows(from_, to, user, division, employee_uid, status)
    used = sum(item["used_seconds"] for item in rows)
    summary = {"employees": len({item["employee_uid"] for item in rows}), "rows": len(rows),
               "exceeded": sum(item["status"] == "exceeded" for item in rows),
               "warning": sum(item["status"] == "warning" for item in rows),
               "avg_used_seconds": used / len(rows) if rows else 0,
               "needs_review": sum(bool(item["needs_review"]) for item in rows)}
    return {"summary": summary, "items": rows[(page - 1) * size:page * size], "total": len(rows)}


@router.get("/daily/{employee_uid}/{report_date}/visits")
def daily_visits(employee_uid: str, report_date: str, user=Depends(require_user)):
    employee = next((item for item in get_employees() if str(item["id"]) == employee_uid), None)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    scoped_person_id(user, str(employee["employee_id"]))
    return {"items": _segments(employee, _date(report_date).isoformat())}


@router.get("/daily.xlsx")
def daily_xlsx(from_: str = Query(..., alias="from"), to: str = Query(...), division: str | None = None,
               employee_uid: str | None = None, status: str | None = None, user=Depends(require_user)):
    rows = _rows(from_, to, user, division, employee_uid, status)
    columns = ["date", "employee_id", "name", "division", "used_seconds", "remaining_seconds",
               "visits", "status", "reid_seconds", "needs_review", "first_seen_at"]
    detail = [["date", "employee_id", "name", "location", "seconds"]]
    for row in rows:
        for location in row["by_location"]:
            detail.append([row["date"], row["employee_id"], row["name"], location["location"], location["seconds"]])
    summary = [["Metric", "Value"], ["Rows", len(rows)],
               ["Employees", len({row["employee_uid"] for row in rows})],
               ["Exceeded", sum(row["status"] == "exceeded" for row in rows)],
               ["Needs HR Review", sum(bool(row["needs_review"]) for row in rows)]]
    violations = [["date", "employee_id", "name", "used_seconds", "allowance_seconds"]] + [
        [row["date"], row["employee_id"], row["name"], row["used_seconds"], row["allowance_seconds"]]
        for row in rows if row["status"] == "exceeded"
    ]
    reviews = [columns] + [[row.get(key) for key in columns] for row in rows if row["needs_review"]]
    content = _xlsx([("Summary", summary),
                     ("Attendance", [columns] + [[row.get(key) for key in columns] for row in rows]),
                     ("Free Time", detail), ("Violations", violations),
                     ("Needs HR Review", reviews)])
    filename = f"report-free-time_{from_}_{to}.xlsx"
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/daily/send")
def send_daily(date: str = Query(...), revision: int = Query(1, ge=1), _admin=Depends(require_admin)):
    try:
        sent = report_service.generate_and_send(_date(date).isoformat(), revision)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not sent:
        raise HTTPException(status_code=409, detail="This report revision was already claimed")
    return {"status": "success", "sent": True}
