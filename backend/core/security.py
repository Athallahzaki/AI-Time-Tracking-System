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

from fastapi import Header, HTTPException
from backend.services.auth_service import (
    auth_service,
)

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
    authorization: str | None = Header(
        default=None
    ),
):
    token = _bearer_token(
        authorization
    )

    user = auth_service.authenticate(
        token
    )

    if user is None or not user["enabled"]:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session",
        )

    return user


def require_admin(
    authorization: str | None = Header(
        default=None
    ),
):
    user = require_user(
        authorization
    )

    if user["role"] != "admin":
        raise HTTPException(
            status_code=403,
            detail="Admin role required",
        )

    return user