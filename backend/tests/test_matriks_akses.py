"""Paket C (11 Nov 2026): matriks akses atas SEMUA rute, diambil dari skema OpenAPI.

Rute baru otomatis ikut teruji. Rute yang sengaja terbuka harus didaftarkan di
`PUBLIK`; menambah rute tanpa autentikasi akan menggagalkan tes ini, bukan
lolos diam-diam.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from backend.core import database
from backend.main import app
from backend.services.auth_service import auth_service
from backend.services.policy_service import policy_service

client = TestClient(app)

# Sengaja tanpa login. Tambah di sini HANYA dengan alasan.
PUBLIK = {
    ("POST", "/api/auth/login"),         # pintu masuk
    ("GET", "/api/settings/display"),    # dibaca halaman login sebelum ada sesi
    ("GET", "/"),                        # healthcheck container
}
# Urusan akun sendiri: sah untuk viewer walau bukan GET.
SWALAYAN = {("POST", "/api/auth/logout"), ("POST", "/api/auth/change-password")}
STREAM = ("/stream",)                    # SSE tidak pernah selesai di TestClient

RUTE = sorted(
    (method.upper(), path)
    for path, operations in app.openapi()["paths"].items()
    for method in operations
    if method in ("get", "post", "put", "patch", "delete")
)
BODY_CACAT = ({}, [], "x", {"a": {"b": [None] * 20}})
QUERY_CACAT = {"limit": "-1", "date": "bukan-tanggal", "person_id": "' OR 1=1--", "camera_id": "../.."}


def _url(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "backend.db")
    # Sapuan memanggil rute yang menulis berkas: arahkan ke salinan, jangan ke policy.yaml repo.
    policy_copy = tmp_path / "policy.yaml"
    policy_copy.write_bytes(policy_service.path.read_bytes())
    monkeypatch.setattr(policy_service, "path", policy_copy)
    database._initialized_for = None
    database.init_database()
    client.cookies.clear()
    yield
    client.cookies.clear()
    database._initialized_for = None


def _token(username: str, role: str) -> dict:
    employee = database.create_employee(f"E-{username}", username)["id"] if role == "viewer" else None
    auth_service.create_user(username=username, password="rahasia-uji-123", role=role,
                             employee_internal_id=employee)
    return {"Authorization": f"Bearer {auth_service.login(username, 'rahasia-uji-123')['access_token']}"}


def test_ada_rute_untuk_diuji():
    assert len(RUTE) > 50, "skema OpenAPI kosong? matriks di bawah tidak menguji apa pun"


def test_tanpa_login_semua_rute_menolak(db):
    terbuka = []
    for method, path in RUTE:
        if (method, path) in PUBLIK:
            continue
        status = client.request(method, _url(path), json={}).status_code
        client.cookies.clear()
        if status not in (401, 403):
            terbuka.append((method, path, status))
    assert terbuka == [], f"rute terbuka tanpa login: {terbuka}"


def test_viewer_tidak_bisa_mengubah_apa_pun(db):
    viewer = _token("andi", "viewer")
    berhasil = []
    for method, path in RUTE:
        if method == "GET" or (method, path) in PUBLIK | SWALAYAN:
            continue
        status = client.request(method, _url(path), json={}, headers=viewer).status_code
        client.cookies.clear()
        if status < 400:
            berhasil.append((method, path, status))
    assert berhasil == [], f"viewer berhasil mengubah: {berhasil}"
    assert client.get("/api/auth/me", headers=viewer).status_code == 200   # sesi utuh: sapuan tidak hampa


def test_masukan_cacat_tidak_pernah_menjadi_5xx(db):
    """Body dan parameter rusak (termasuk percobaan injeksi) harus dijawab 4xx."""
    _token("tumbal", "viewer")           # user id 1 dan karyawan id 1: sasaran rute `/{id}`
    admin = _token("bos", "admin")       # id 2: tidak tersentuh reset-password/hapus di sapuan
    gagal = []
    for method, path in RUTE:
        if path.endswith(STREAM) or (method, path) in SWALAYAN:
            continue
        for body in BODY_CACAT:
            response = client.request(method, _url(path), json=body, headers=admin, params=QUERY_CACAT)
            client.cookies.clear()
            if response.status_code >= 500:
                gagal.append((method, path, response.status_code))
                break
    assert gagal == [], f"masukan cacat menghasilkan 5xx: {gagal}"
    assert client.get("/api/auth/me", headers=admin).status_code == 200    # sesi admin utuh: sapuan tidak hampa
