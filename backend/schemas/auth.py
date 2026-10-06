from __future__ import annotations

from typing import Literal

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