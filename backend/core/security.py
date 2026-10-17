"""Minimal guard for mutating endpoints.

Bukan pengganti autentikasi pengguna (itu masih pekerjaan terbuka: siapa HR
yang mengoreksi, siapa operator yang mengganti kamera). Ini memastikan bahwa
kalau `BACKEND_API_KEY` di-set, tidak ada klien di jaringan yang bisa mengubah
kamera, enrollment, atau koreksi tanpa kunci itu.

Frontend dev server menyuntikkan header ini lewat proxy Vite (lihat
`frontend/vite.config.ts`), jadi kunci tidak pernah masuk ke bundle browser.
"""

from __future__ import annotations

import hmac
import os

from fastapi import Cookie, Header, HTTPException, Query
from backend.core.database import get_employee_by_id
from backend.services.auth_service import (
    auth_service,
)

from collections.abc import Mapping

def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.getenv("BACKEND_API_KEY", "")
    if not expected:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
    
def _bearer_token(
    authorization: str | None,
) -> str:
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header",
        )

    scheme, _, token = authorization.partition(" ")

    if (
        scheme.lower() != "bearer"
        or not token
    ):
        raise HTTPException(
            status_code=401,
            detail="Expected Bearer token",
        )

    return token


def require_user(
    authorization: str | None = Header(default=None),
    access_token_cookie: str | None = Cookie(
        default=None,
        alias="access_token",
    ),
):
    raw_token: str | None = None

    if authorization:
        raw_token = _bearer_token(authorization)
    elif access_token_cookie:
        raw_token = access_token_cookie

    if not raw_token:
        raise HTTPException(
            status_code=401,
            detail="Missing authentication token",
        )

    user = auth_service.authenticate(raw_token)

    if user is None or not user["enabled"]:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session",
        )

    return user


def require_admin(
    authorization: str | None = Header(default=None),
    access_token_cookie: str | None = Cookie(
        default=None,
        alias="access_token",
    ),
):
    user = require_user(
        authorization=authorization,
        access_token_cookie=access_token_cookie,
    )

    if user["role"] != "admin":
        raise HTTPException(
            status_code=403,
            detail="Admin role required",
        )

    return user


def require_stream_user(
    authorization: str | None = Header(default=None),
    access_token: str | None = Query(default=None),
    access_token_cookie: str | None = Cookie(default=None, alias="access_token"),
):
    """Authenticate SSE. Native EventSource cannot set Authorization headers."""
    raw = access_token or access_token_cookie
    if raw is None and authorization:
        raw = _bearer_token(authorization)
    if not raw:
        raise HTTPException(status_code=401, detail="Missing stream access token")
    user = auth_service.authenticate(raw)
    if user is None or not user["enabled"]:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return user


def require_video_user(
    authorization: str | None = Header(default=None),
    access_token: str | None = Query(default=None),
    access_token_cookie: str | None = Cookie(default=None, alias="access_token"),
):
    """Authenticate nginx video subrequests using header, query, or cookie."""
    raw = access_token or access_token_cookie
    if raw is None and authorization:
        raw = _bearer_token(authorization)
    if not raw:
        raise HTTPException(status_code=401, detail="Missing video access token")
    user = auth_service.authenticate(raw)
    if user is None or not user["enabled"]:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return user


def employee_scope(user) -> str | None:
    """Return viewer's immutable employee scope; admins have unrestricted scope."""
    if user["role"] == "admin":
        return None
    internal_id = user.get("employee_internal_id")
    if internal_id is None:
        raise HTTPException(status_code=403, detail="Viewer is not linked to an employee")
    employee = get_employee_by_id(int(internal_id))
    if employee is None:
        raise HTTPException(status_code=403, detail="Linked employee no longer exists")
    return str(employee["employee_id"])


def scoped_person_id(user, requested: str | None = None) -> str | None:
    if not isinstance(user, Mapping):
        return requested

    own = employee_scope(user)
    if own is None:
        return requested

    if requested is not None and str(requested) != own:
        raise HTTPException(
            status_code=403,
            detail="Viewer cannot access another employee",
        )

    return own