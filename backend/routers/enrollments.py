from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.services.engine_client import (
    EngineConnectionError,
    engine_client,
)

from backend.core.database import get_enrollments
from backend.schemas.enrollment import EnrollmentRequest
from backend.services.enrollment_service import enrollment_service


router = APIRouter(
    prefix="/api/enrollments",
    tags=["Enrollments"],
)


@router.get("")
def list_enrollments():
    enrollments = get_enrollments()

    return {
        "status": "success",
        "count": len(enrollments),
        "enrollments": enrollments,
    }


@router.post("")
def create_enrollment(req: EnrollmentRequest):
    try:
        message = enrollment_service.create_request(
            req
        )

        engine_client.send(
            message.model_dump(
                exclude_none=True
            )
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except EngineConnectionError as exc:
        raise HTTPException(
            status_code=503,
            detail="AI Vision Engine is unavailable",
        ) from exc

    return {
        "status": "pending",
        "request_id": message.request_id,
        "person_id": message.person_id,
    }