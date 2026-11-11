"""Paket B (11 Nov 2026): sesi, password sementara, dan akses viewer.

Temuan audit keamanan 1, 2, 5, 7 (docs/ANALISIS-KETAHANAN.md §2.2).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.core import database
from backend.main import app
from backend.services.auth_service import auth_service

client = TestClient(app)


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "backend.db")
    database._initialized_for = None
    database.init_database()
    client.cookies.clear()
    yield
    client.cookies.clear()
    database._initialized_for = None


def _login(username: str, password: str) -> dict:
    token = auth_service.login(username, password)["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _user(username: str, role: str = "viewer", **extra) -> dict:
    employee = None
    if role == "viewer":
        employee = database.create_employee(f"E-{username}", username)["id"]
    auth_service.create_user(username=username, password="rahasia-awal-1", role=role,
                             employee_internal_id=employee, **extra)
    return _login(username, "rahasia-awal-1")


def test_password_sementara_ditolak_server_sampai_diganti():
    """Dulu hanya frontend yang memaksa ganti password."""
    viewer = _user("baru", must_change_password=True)
    for path in ("/api/attendance/breaks", "/api/cameras", "/api/notifications", "/api/me/usage-today"):
        response = client.get(path, headers=viewer)
        assert (response.status_code, response.json()["detail"]) == (403, "Password change required"), path
    assert client.get("/api/detections/stream", headers=viewer).status_code == 403
    assert client.get("/api/auth/video-authorize", headers=viewer).status_code == 403

    assert client.get("/api/auth/me", headers=viewer).json()["user"]["must_change_password"] is True
    changed = client.post("/api/auth/change-password", headers=viewer,
                          json={"old_password": "rahasia-awal-1", "new_password": "rahasia-baru-22"})
    assert changed.status_code == 204
    assert client.get("/api/cameras", headers=viewer).status_code == 200      # sesi yang sama, kini bebas


def test_ganti_password_mencabut_sesi_lain_tetapi_bukan_sesi_ini():
    ini = _user("andi")
    lain = _login("andi", "rahasia-awal-1")                                   # perangkat lain / token curian
    assert client.get("/api/auth/me", headers=lain).status_code == 200
    client.post("/api/auth/change-password", headers=ini,
                json={"old_password": "rahasia-awal-1", "new_password": "rahasia-baru-22"})
    assert client.get("/api/auth/me", headers=ini).status_code == 200
    assert client.get("/api/auth/me", headers=lain).status_code == 401


def test_reset_password_oleh_admin_mencabut_semua_sesi_pengguna_itu():
    admin = _user("bos", role="admin")
    korban = _user("andi")
    user_id = client.get("/api/auth/me", headers=korban).json()["user"]["id"]
    assert client.post(f"/api/auth/users/{user_id}/reset-password", headers=admin).status_code == 200
    assert client.get("/api/auth/me", headers=korban).status_code == 401
    assert client.get("/api/auth/me", headers=admin).status_code == 200       # sesi admin tidak tersentuh


def test_logout_dengan_sesi_cookie_saja():
    """Dulu 500: logout membaca header Authorization yang tidak ada."""
    _user("andi")
    login = client.post("/api/auth/login", json={"username": "andi", "password": "rahasia-awal-1"})
    assert login.status_code == 200 and client.cookies.get("access_token")
    assert client.post("/api/auth/logout").status_code == 200
    client.cookies.set("access_token", login.json()["access_token"])
    assert client.get("/api/auth/me").status_code == 401                      # sesinya benar-benar dihapus


def test_viewer_tidak_melihat_alamat_sumber_kamera_dan_status_email():
    admin, viewer = _user("bos", role="admin"), _user("andi")
    seen = client.get("/api/cameras", headers=viewer).json()["cameras"]
    assert seen and all("source_uri" not in c and "allowed_sources" not in c for c in seen)
    detail = client.get(f"/api/cameras/{seen[0]['id']}", headers=viewer).json()
    assert "source_uri" not in detail
    assert "source_uri" in client.get("/api/cameras", headers=admin).json()["cameras"][0]
    assert client.get("/api/settings/email", headers=viewer).status_code == 403
    assert client.get("/api/settings/email", headers=admin).status_code == 200


def test_api_key_ditegakkan_bila_diisi(monkeypatch):
    """Dulu `require_api_key` tidak dipasang di rute mana pun."""
    admin = _user("bos", role="admin")
    assert client.get("/api/auth/me", headers=admin).status_code == 200       # kosong = tidak diperiksa
    monkeypatch.setenv("BACKEND_API_KEY", "kunci-port-backend")
    assert client.get("/api/auth/me", headers=admin).status_code == 401
    assert client.get("/api/settings/display").status_code == 401             # rute publik pun lewat nginx
    assert client.get("/api/auth/me", headers={**admin, "X-API-Key": "kunci-port-backend"}).status_code == 200
    assert client.get("/").status_code == 200                                 # healthcheck container
