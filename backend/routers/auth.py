from __future__ import annotations

import sqlite3
import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
)
import os

from backend.core.database import (
    count_active_admins,
    delete_user,
    get_employee_by_id,
    get_employee_by_employee_id,
    get_user_by_id,
    get_users,
    update_user,
)
from backend.core.security import (
    require_admin,
    require_session,
    session_token,
    require_video_user,
    require_user,
)
from backend.schemas.auth import (
    LoginRequest,
    UserCreateRequest,
    UserUpdateRequest,
    ChangePasswordRequest,
)
from backend.services.auth_service import (
    AuthenticationError,
    auth_service,
)


router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"],
)


def _public_user(user):
    employee = get_employee_by_id(user["employee_internal_id"]) if user.get("employee_internal_id") else None
    return {
        **user,
        "employee_uid": str(employee["id"]) if employee else None,
        "employee_id": employee["employee_id"] if employee else None,
        "name": employee["name"] if employee else None,
    }


class _LoginLimiter:
    """Batas login GAGAL per IP dan per (username, IP) dalam jendela geser (overhaul P1).

    Kuota username diikat ke IP (audit 10 Nov): dulu 5 password salah dari mana
    saja mengunci akun itu untuk SEMUA orang, jadi siapa pun bisa mengunci admin.
    Tebakan terdistribusi ke satu akun ditahan batas per IP, panjang password,
    dan allowlist Traefik; bukan lagi oleh penguncian akun.

    shortcut: state di memori satu proses (uvicorn --workers 1); reset saat restart.
    Naikkan ke tabel SQLite bila backend jalan lebih dari satu worker.
    IP klien dari X-Forwarded-For hanya dipercaya dari jaringan proxy (FORWARDED_ALLOW_IPS,
    deploy/backend/Dockerfile); batas per username tetap menahan tebakan satu akun.
    """

    def __init__(self, window_seconds: float, max_per_ip: int, max_per_user: int) -> None:
        self.window = window_seconds
        self.max_per_ip = max_per_ip
        self.max_per_user = max_per_user
        self._failures: dict = defaultdict(deque)
        self._lock = threading.Lock()

    def _recent(self, key, now: float) -> deque:
        bucket = self._failures[key]
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        return bucket

    def retry_after(self, ip: str, username: str, now: float) -> int:
        """Detik sampai boleh mencoba lagi; 0 = boleh."""
        with self._lock:
            waits = []
            for key, limit in ((("ip", ip), self.max_per_ip), (("user", username, ip), self.max_per_user)):
                bucket = self._recent(key, now)
                if len(bucket) >= limit:
                    waits.append(self.window - (now - bucket[0]))
                if not bucket:
                    self._failures.pop(key, None)
            return int(max(waits) + 1) if waits else 0

    def failed(self, ip: str, username: str, now: float) -> None:
        with self._lock:
            self._failures[("ip", ip)].append(now)
            self._failures[("user", username, ip)].append(now)

    def succeeded(self, ip: str, username: str) -> None:
        with self._lock:
            self._failures.pop(("user", username, ip), None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


login_limiter = _LoginLimiter(
    window_seconds=float(os.getenv("AUTH_LOGIN_WINDOW_SECONDS", "300")),
    max_per_ip=int(os.getenv("AUTH_LOGIN_MAX_FAILURES_PER_IP", "20")),
    max_per_user=int(os.getenv("AUTH_LOGIN_MAX_FAILURES_PER_USER", "5")),
)


@router.post("/login")
def login(req: LoginRequest, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    username = req.username.strip().lower()
    now = time.monotonic()
    wait = login_limiter.retry_after(ip, username, now)
    if wait:
        raise HTTPException(
            status_code=429,
            detail="Terlalu banyak percobaan login gagal. Coba lagi nanti.",
            headers={"Retry-After": str(wait)},
        )
    try:
        result = auth_service.login(
            req.username,
            req.password,
        )
        login_limiter.succeeded(ip, username)
        response.set_cookie(
            "access_token", result["access_token"], httponly=True, samesite="lax",
            secure=os.getenv("AUTH_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"},
            max_age=max(1, int(result["expires_at"] - time.time())), path="/",
        )
        return result

    except AuthenticationError as exc:
        login_limiter.failed(ip, username, now)
        raise HTTPException(
            status_code=401,
            detail=str(exc),
        ) from exc


@router.get("/me")
def me(
    user=Depends(require_session),
):
    return {
        "status": "success",
        "user": _public_user(user),
    }


@router.post("/logout")
def logout(
    response: Response,
    token: str = Depends(session_token),
    user=Depends(require_session),
):
    del user

    # Token dari header ATAU cookie: dulu sesi cookie-saja gagal 500 di sini.
    auth_service.logout(
        token
    )
    response.delete_cookie("access_token", path="/")

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
    users = [_public_user(item) for item in get_users()]

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
        employee_internal_id = req.employee_internal_id
        if employee_internal_id is None and req.employee_id:
            employee = get_employee_by_employee_id(req.employee_id)
            if employee is None:
                raise ValueError("employee not found")
            employee_internal_id = int(employee["id"])
        user = auth_service.create_user(
            username=req.username,
            password=req.password,
            role=req.role,
            employee_internal_id=employee_internal_id,
            must_change_password=req.must_change_password,
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
        "user": _public_user(user),
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
    return {"status": "success", "user": _public_user(updated)}


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, _admin=Depends(require_admin)):
    if get_user_by_id(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    temporary = secrets.token_urlsafe(10)
    update_user(
        user_id, password_hash=auth_service.hash_password(temporary),
        must_change_password=True,
    )
    return {"temporary_password": temporary}


@router.post("/change-password", status_code=204)
def change_password(req: ChangePasswordRequest, user=Depends(require_session),
                    token: str = Depends(session_token)):
    current = get_user_by_id(user["id"], include_password=True)
    if current is None or not auth_service.verify_password(req.old_password, current["password_hash"]):
        raise HTTPException(status_code=400, detail="Old password is incorrect")
    update_user(
        user["id"], password_hash=auth_service.hash_password(req.new_password),
        must_change_password=False,
        # Sesi ini tetap hidup; semua sesi lain pengguna ini dicabut.
        keep_session_hash=auth_service.hash_token(token),
    )
    return None


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
        original_uri = request.headers.get("x-original-uri", "").split("?")[0]
        parts = [part for part in original_uri.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"hls", "whep"}:
            candidate = parts[1]
        if candidate not in settings.cameras:
            candidate = next(
                (camera_id for camera_id, config in settings.cameras.items()
                 if config.stream_url and (
                     original_uri == config.stream_url
                     or (candidate and f"/{candidate}/" in config.stream_url)
                     or original_uri.removeprefix("/hls") == config.stream_url.removeprefix("/hls")
                     or original_uri.removeprefix("/whep") == config.stream_url.removeprefix("/whep")
                 )),
                None,
            )
    if not candidate or candidate not in settings.cameras:
        raise HTTPException(status_code=403, detail="Camera access denied")
    return None
