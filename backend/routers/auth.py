from __future__ import annotations

import sqlite3

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
)

from backend.core.database import (
    get_users,
)
from backend.core.security import (
    require_admin,
    require_user,
)
from backend.schemas.auth import (
    LoginRequest,
    UserCreateRequest,
)
from backend.services.auth_service import (
    AuthenticationError,
    auth_service,
)


router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"],
)


@router.post("/login")
def login(req: LoginRequest):
    try:
        return auth_service.login(
            req.username,
            req.password,
        )

    except AuthenticationError as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
        ) from exc


@router.get("/me")
def me(
    user=Depends(require_user),
):
    return {
        "status": "success",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
        },
    }


@router.post("/logout")
def logout(
    authorization: str | None = Header(
        default=None
    ),
    user=Depends(require_user),
):
    del user

    token = authorization.split(
        " ",
        1,
    )[1]

    auth_service.logout(
        token
    )

    return {
        "status": "success",
        "message": "Logged out",
    }


@router.get(
    "/users",
    dependencies=[
        Depends(require_admin)
    ],
)
def list_users():
    users = get_users()

    return {
        "status": "success",
        "count": len(users),
        "users": users,
    }


@router.post(
    "/users",
    dependencies=[
        Depends(require_admin)
    ],
)
def create_new_user(
    req: UserCreateRequest,
):
    try:
        user = auth_service.create_user(
            username=req.username,
            password=req.password,
            role=req.role,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="username already exists",
        ) from exc

    return {
        "status": "success",
        "user": user,
    }