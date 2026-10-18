"""Pydantic schemas for Employee CRUD endpoints."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from backend.core.identity import ANON_PREFIX, is_anon_id


def _tolak_anon(value: Optional[str]) -> Optional[str]:
    if is_anon_id(value):
        raise ValueError(f"awalan {ANON_PREFIX} dicadangkan untuk kelompok ReID tanpa wajah")
    return value


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
    division: Optional[str] = Field(default=None, max_length=100)
    email: Optional[str] = Field(
        default=None,
        max_length=254,
    )
    status: Literal["active", "inactive"] = "active"

    _employee_id_bukan_anon = field_validator("employee_id")(_tolak_anon)


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
    division: Optional[str] = Field(default=None, max_length=100)
    email: Optional[str] = Field(
        default=None,
        max_length=254,
        description="Set to null to clear email.",
    )
    status: Optional[Literal["active", "inactive"]] = None

    _employee_id_bukan_anon = field_validator("employee_id")(_tolak_anon)
