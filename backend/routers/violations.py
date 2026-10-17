from __future__ import annotations

from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.core.database import get_violations
from backend.core.security import require_user, scoped_person_id


router = APIRouter(
    prefix="/api/violations",
    tags=["Violations"],
    dependencies=[Depends(require_user)],
)


@router.get("")
def list_violations(
    person_id: Optional[str] = None,
    date: Optional[str] = None,
    limit: int = Query(
        default=200,
        ge=1,
        le=1000,
    ),
    user=Depends(require_user),
):
    person_id = scoped_person_id(user, person_id)
    if date is not None:
        try:
            date_type.fromisoformat(date)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="date must use YYYY-MM-DD",
            ) from exc

    violations = get_violations(
        person_id=person_id,
        local_date=date,
        limit=limit,
    )

    return {
        "status": "success",
        "count": len(violations),
        "violations": violations,
    }
