from __future__ import annotations

from pydantic import BaseModel, Field


class FreeTimePolicyUpdate(BaseModel):
    daily_free_time_allowance_minutes: float = Field(ge=0)
    warning_remaining_minutes: float = Field(ge=0)