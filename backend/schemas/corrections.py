"""Manual correction schemas — append-only audit trail.

Corrections never overwrite records. Every correction is a new event that
records who changed what, when, and why. The affected session is then
recalculated from the amended data.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class CorrectionCreate(BaseModel):
    """Request to create a manual correction."""
    session_id: str
    gap_id: Optional[str] = None  # if correcting a specific gap
    corrected_by: str
    reason: str  # e.g. "tracking_loss_not_break", "was_actually_present"
    new_classification: Optional[str] = None  # override gap classification
    adjustment_minutes: Optional[float] = None  # manual time adjustment
    notes: str = ""


class CorrectionEntry(BaseModel):
    """A stored correction event."""
    correction_id: str
    session_id: str
    gap_id: Optional[str] = None
    corrected_by: str
    corrected_at: str  # RFC3339
    reason: str
    new_classification: Optional[str] = None
    adjustment_minutes: Optional[float] = None
    notes: str = ""
    # What changed
    old_value: Optional[str] = None
    new_value: Optional[str] = None
