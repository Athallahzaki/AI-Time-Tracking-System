"""Manual correction schemas — append-only audit trail.

Corrections never overwrite records. A correction either excludes one visit
from the allowance (`gap_id` = visit_id + `new_classification`) or adds a
signed time adjustment to one person's day (`adjustment_minutes`, negative =
give time back). The allowance is recalculated from the amended data.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class CorrectionCreate(BaseModel):
    person_id: Optional[str] = None
    date: Optional[str] = None  # YYYY-MM-DD, local policy timezone
    session_id: Optional[str] = None
    gap_id: Optional[str] = None  # visit_id from /api/attendance/breaks
    corrected_by: str
    reason: str
    new_classification: Optional[str] = None
    adjustment_minutes: Optional[float] = None
    notes: Optional[str] = ""


class CorrectionEntry(BaseModel):
    correction_id: str
    person_id: Optional[str] = None
    date: Optional[str] = None
    session_id: Optional[str] = None
    gap_id: Optional[str] = None
    corrected_by: str
    corrected_at: str
    reason: str
    new_classification: Optional[str] = None
    adjustment_minutes: Optional[float] = None
    notes: str = ""
    old_value: Optional[str] = None
    new_value: Optional[str] = None
