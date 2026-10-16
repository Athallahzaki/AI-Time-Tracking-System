"""Pydantic schemas for Employee CRUD endpoints."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class EmployeeCreateRequest(BaseModel):
    employee_id: str = Field(
        min_length=1,
        max_length=50,
        description="Editable employee ID / NIP.",
    )
    name: str = Field(
        min_length=1,
        max_length=200,
    )
    email: Optional[str] = Field(
        default=None,
        max_length=254,
    )
    status: Literal["active", "inactive"] = "active"


class EmployeeUpdateRequest(BaseModel):
    employee_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=50,
    )
    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=200,
    )
    email: Optional[str] = Field(
        default=...,
        max_length=254,
        description="Set to null to clear email.",
    )
    status: Optional[Literal["active", "inactive"]] = None
