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


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.getenv("BACKEND_API_KEY", "")
    if not expected:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
