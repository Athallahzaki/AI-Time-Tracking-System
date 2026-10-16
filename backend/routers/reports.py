from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from backend.core.security import require_admin, require_user, scoped_person_id
from backend.services.report_service import report_service

router = APIRouter(prefix="/api/reports", tags=["Reports"], dependencies=[Depends(require_user)])


def _date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date must use YYYY-MM-DD") from exc


@router.get("")
def list_reports(_user=Depends(require_user)):
    return {"status": "success", "runs": report_service.list_runs()}


@router.get("/daily")
def daily_report(date: str = Query(...), user=Depends(require_user)):
    return {"status": "success", "report": report_service.daily(_date(date), scoped_person_id(user))}


@router.get("/daily.xlsx")
def daily_xlsx(date: str = Query(...), user=Depends(require_user)):
    target = _date(date)
    content = report_service.xlsx(target, scoped_person_id(user))
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="ai-time-report-{target}.xlsx"'})


@router.post("/daily/send")
def send_daily(date: str = Query(...), revision: int = Query(1, ge=1),
               _admin=Depends(require_admin)):
    try:
        sent = report_service.generate_and_send(_date(date), revision)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not sent:
        raise HTTPException(status_code=409, detail="This report revision was already claimed")
    return {"status": "success", "sent": True}
