from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.database import get_hr_reviews, resolve_hr_review, save_attribution
from backend.core.security import require_admin

router = APIRouter(prefix="/api/hr-review", tags=["HR Review"], dependencies=[Depends(require_admin)])


class AttributionRequest(BaseModel):
    event_outbox_id: str = ""
    event_seq: int = Field(ge=0)
    original_person_id: str | None = None
    employee_internal_id: int | None = Field(default=None, ge=1)
    attribution_source: str = "manual"
    attribution_confidence: float | None = Field(default=None, ge=0, le=1)
    needs_hr_review: bool = False
    review_reason: str | None = None


class ResolveRequest(BaseModel):
    reviewed_by: str = Field(min_length=1, max_length=100)


@router.get("")
def list_reviews(unresolved_only: bool = True):
    return {"status": "success", "reviews": get_hr_reviews(unresolved_only)}


@router.post("/attributions", status_code=201)
def create_attribution(req: AttributionRequest):
    if not save_attribution(req.model_dump()):
        raise HTTPException(status_code=409, detail="Attribution already exists")
    return {"status": "success"}


@router.post("/{review_id}/resolve")
def resolve(review_id: int, req: ResolveRequest):
    if not resolve_hr_review(review_id, req.reviewed_by):
        raise HTTPException(status_code=404, detail="Unresolved review not found")
    return {"status": "success", "review_id": review_id}
