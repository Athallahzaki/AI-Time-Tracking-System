from __future__ import annotations

import sqlite3

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
)

from backend.core.database import (
    count_active_admins,
    delete_user,
    get_employee_by_id,
    get_user_by_id,
    get_users,
    update_user,
)
from backend.core.security import (
    require_admin,
    require_video_user,
    require_user,
)
from backend.schemas.auth import (
    LoginRequest,
    UserCreateRequest,
    UserUpdateRequest,
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
            "employee_internal_id": user.get("employee_internal_id"),
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
            employee_internal_id=req.employee_internal_id,
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


def _validate_link(role: str, employee_internal_id):
    if role == "viewer" and employee_internal_id is None:
        raise HTTPException(status_code=400, detail="viewer must be linked to an employee")
    if employee_internal_id is not None:
        employee = get_employee_by_id(employee_internal_id)
        if employee is None:
            raise HTTPException(status_code=400, detail="employee not found")
        if role == "viewer" and employee["status"] != "active":
            raise HTTPException(status_code=400, detail="viewer requires an active employee")


@router.patch("/users/{user_id}")
def patch_user(user_id: int, req: UserUpdateRequest, _admin=Depends(require_admin)):
    current = get_user_by_id(user_id)
    if current is None:
        raise HTTPException(status_code=404, detail="User not found")
    new_role = req.role or current["role"]
    new_enabled = current["enabled"] if req.enabled is None else req.enabled
    employee_link = (
        req.employee_internal_id
        if "employee_internal_id" in req.model_fields_set
        else current["employee_internal_id"]
    )
    _validate_link(new_role, employee_link)
    removes_active_admin = (
        current["role"] == "admin" and current["enabled"]
        and (new_role != "admin" or not new_enabled)
    )
    if removes_active_admin and count_active_admins(exclude_user_id=user_id) == 0:
        raise HTTPException(status_code=409, detail="Cannot remove the last active admin")
    try:
        updated = update_user(
            user_id,
            username=req.username,
            password_hash=auth_service.hash_password(req.password) if req.password else None,
            role=req.role,
            enabled=req.enabled,
            employee_internal_id=(employee_link if "employee_internal_id" in req.model_fields_set else ...),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="username already exists") from exc
    return {"status": "success", "user": updated}


@router.delete("/users/{user_id}")
def remove_user(user_id: int, _admin=Depends(require_admin)):
    current = get_user_by_id(user_id)
    if current is None:
        raise HTTPException(status_code=404, detail="User not found")
    if (current["role"] == "admin" and current["enabled"]
            and count_active_admins(exclude_user_id=user_id) == 0):
        raise HTTPException(status_code=409, detail="Cannot delete the last active admin")
    delete_user(user_id)
    return {"status": "success", "deleted_user_id": user_id}


@router.get("/video-authorize", status_code=204)
def video_authorize(
    request: Request,
    camera_id: str | None = Query(default=None),
    _user=Depends(require_video_user),
):
    """nginx ``auth_request`` target for HLS/WHEP resources.

    ``camera_id`` may be explicit, or inferred from ``X-Original-URI`` paths
    such as ``/hls/cam01/index.m3u8`` and ``/whep/cam01/whep``.
    """
    from backend.core.config import settings

    candidate = camera_id
    if candidate is None:
        parts = [part for part in request.headers.get("x-original-uri", "").split("?")[0].split("/") if part]
        if len(parts) >= 2 and parts[0] in {"hls", "whep"}:
            candidate = parts[1]
    if not candidate or candidate not in settings.cameras:
        raise HTTPException(status_code=403, detail="Camera access denied")
    return None
