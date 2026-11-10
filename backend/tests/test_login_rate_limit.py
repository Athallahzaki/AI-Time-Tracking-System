"""Overhaul P1: login gagal beruntun ditolak 429, per username dan per IP."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.core import database
from backend.main import app
from backend.routers.auth import login_limiter
from backend.services.auth_service import auth_service


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "backend.db")
    database.init_database()
    auth_service.create_user(username="admin", password="rahasia-panjang", role="admin")
    login_limiter.reset()
    yield TestClient(app)
    login_limiter.reset()


def _login(client, username="admin", password="salah-password"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_lima_gagal_per_username_lalu_ditolak_bahkan_dengan_password_benar(client):
    for _ in range(login_limiter.max_per_user):
        assert _login(client).status_code == 401
    blocked = _login(client, password="rahasia-panjang")
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0


def test_username_beda_huruf_tetap_satu_kuota(client):
    for name in ("admin", "ADMIN", " Admin ", "admin", "aDmin"):
        _login(client, username=name)
    assert _login(client).status_code == 429


def test_dua_puluh_gagal_dari_satu_ip_menolak_username_lain(client):
    for i in range(login_limiter.max_per_ip):
        _login(client, username=f"tebak{i}")
    assert _login(client, username="admin", password="rahasia-panjang").status_code == 429


def test_login_berhasil_mereset_kuota_username(client):
    for _ in range(login_limiter.max_per_user - 1):
        _login(client)
    assert _login(client, password="rahasia-panjang").status_code == 200
    assert _login(client).status_code == 401, "kuota username mulai dari nol lagi"


def test_jendela_lewat_kuota_kembali():
    from backend.routers.auth import _LoginLimiter

    limiter = _LoginLimiter(window_seconds=10, max_per_ip=100, max_per_user=2)
    limiter.failed("1.1.1.1", "u", now=0.0)
    limiter.failed("1.1.1.1", "u", now=1.0)
    assert limiter.retry_after("1.1.1.1", "u", now=5.0) == 6
    assert limiter.retry_after("1.1.1.1", "u", now=11.5) == 0


def test_penyerang_dari_ip_lain_tidak_bisa_mengunci_akun():
    """Audit 10 Nov: 5 password salah dari satu IP tidak mengunci admin di IP lain."""
    from backend.routers.auth import _LoginLimiter

    limiter = _LoginLimiter(window_seconds=300, max_per_ip=20, max_per_user=5)
    for i in range(5):
        limiter.failed("6.6.6.6", "admin", now=float(i))
    assert limiter.retry_after("6.6.6.6", "admin", now=5.0) > 0
    assert limiter.retry_after("10.0.0.7", "admin", now=5.0) == 0
