from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.core.database import get_enrollments
from backend.core.security import require_admin, require_user, scoped_person_id
from backend.schemas.enrollment import EnrollmentRequest
from backend.services.engine_client import EngineConnectionError, engine_client
from backend.services.enrollment_service import enrollment_service

router = APIRouter(prefix="/api/enrollments", tags=["Enrollments"], dependencies=[Depends(require_user)])



@router.get("")
def list_enrollments(user=Depends(require_user)):
    enrollments = get_enrollments()
    own = scoped_person_id(user)
    if own:
        enrollments = [item for item in enrollments if str(item.get("person_id")) == own]
    return {"status": "success", "count": len(enrollments), "enrollments": enrollments}


@router.post("", dependencies=[Depends(require_admin)])
def create_enrollment(req: EnrollmentRequest):
    try:
        message = enrollment_service.create_request(req)
        engine_client.send(message.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EngineConnectionError as exc:
        raise HTTPException(status_code=503, detail="AI Vision Engine is unavailable") from exc
    return {"status": "pending", "request_id": message.request_id, "person_id": message.person_id}


@router.get("/requests/{request_id}")
def enrollment_request_status(request_id: str, _admin=Depends(require_admin)):
    """Poll this after POST: pending -> accepted | rejected (with reason)."""
    status = enrollment_service.status(request_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Unknown enrollment request")
    return status
