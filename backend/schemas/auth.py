from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(
        min_length=1,
        max_length=100,
    )

    password: str = Field(
        min_length=1,
        max_length=256,
    )


class UserCreateRequest(BaseModel):
    username: str = Field(
        min_length=1,
        max_length=100,
    )

    password: str = Field(
        min_length=8,
        max_length=256,
    )

    role: Literal[
        "admin",
        "viewer",
    ]

    employee_internal_id: Optional[int] = Field(default=None, ge=1)


class UserUpdateRequest(BaseModel):
    username: Optional[str] = Field(default=None, min_length=1, max_length=100)
    password: Optional[str] = Field(default=None, min_length=8, max_length=256)
    role: Optional[Literal["admin", "viewer"]] = None
    enabled: Optional[bool] = None
    employee_internal_id: Optional[int] = Field(default=None, ge=1)
