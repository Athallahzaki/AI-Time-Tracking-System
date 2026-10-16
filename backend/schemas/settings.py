from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator
from zoneinfo import ZoneInfo


class FreeTimePolicyUpdate(BaseModel):
    daily_free_time_allowance_minutes: Optional[float] = Field(default=None, ge=0)
    warning_remaining_minutes: Optional[float] = Field(default=None, ge=0)
    qualification_seconds: Optional[float] = Field(default=None, ge=0)
    visit_merge_gap_seconds: Optional[float] = Field(default=None, ge=0)
    open_presence_stale_seconds: Optional[float] = Field(default=None, gt=0)
    timezone: Optional[str] = None
    official_breaks: Optional[Any] = None


class HRRecipientSettings(BaseModel):
    enabled: bool = True
    primary: List[str] = Field(default_factory=list)
    cc: List[str] = Field(default_factory=list)
    fallback: Optional[str] = None

    @field_validator("primary", "cc")
    @classmethod
    def validate_emails(cls, values):
        if any("@" not in value for value in values):
            raise ValueError("invalid email address")
        return values

    @field_validator("fallback")
    @classmethod
    def validate_fallback(cls, value):
        if value is not None and "@" not in value:
            raise ValueError("invalid fallback email address")
        return value


class ReportScheduleSettings(BaseModel):
    enabled: bool = False
    timezone: str = "Asia/Jakarta"
    send_time: str = "18:00"
    recipients: List[str] = Field(default_factory=list)
    cc: List[str] = Field(default_factory=list)

    @field_validator("send_time")
    @classmethod
    def validate_time(cls, value):
        parts = value.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError("send_time must use HH:MM")
        hour, minute = map(int, parts)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("send_time must use HH:MM")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value):
        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError("unknown timezone") from exc
        return value

    @field_validator("recipients", "cc")
    @classmethod
    def validate_recipient_emails(cls, values):
        if any("@" not in value for value in values):
            raise ValueError("invalid email address")
        return values


class ScheduleWindow(BaseModel):
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def validate_clock(cls, value):
        parts = value.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError("schedule time must use HH:MM")
        hour, minute = map(int, parts)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("schedule time must use HH:MM")
        return value


class CameraScheduleSettings(BaseModel):
    timezone: str = "Asia/Jakarta"
    cameras: Dict[str, Dict[str, List[ScheduleWindow]]] = Field(default_factory=dict)

    @field_validator("timezone")
    @classmethod
    def validate_schedule_timezone(cls, value):
        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError("unknown timezone") from exc
        return value
