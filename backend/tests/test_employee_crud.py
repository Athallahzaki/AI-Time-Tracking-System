"""Tests for Phase 1C — Employee CRUD endpoints.

Verifies:
- GET /api/employees (list, filter by status)
- POST /api/employees (create, duplicate validation)
- GET /api/employees/{id} (get one, 404)
- PATCH /api/employees/{id} (partial update, duplicate employee_id, 404)
- Auth enforcement: admin-only for mutations, login-required for reads
"""

from __future__ import annotations

import os
import tempfile

import pytest

_tmpdir = tempfile.mkdtemp()
os.environ["BACKEND_DB_PATH"] = os.path.join(_tmpdir, "test_1c.db")

from fastapi.testclient import TestClient  # noqa: E402

from backend.core import database as db  # noqa: E402
from backend.main import app  # noqa: E402
from backend.services.auth_service import auth_service  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    test_db = str(tmp_path / "test.db")
    db.DB_PATH = type(db.DB_PATH)(test_db)
    db._initialized_for = None
    db.init_database()
    yield
    db._initialized_for = None


def _create_admin_token() -> str:
    """Helper: create admin user and return bearer token."""
    auth_service.create_user(
        username="testadmin",
        password="adminpass123",
        role="admin",
    )
    result = auth_service.login("testadmin", "adminpass123")
    return result["access_token"]


def _create_viewer_token() -> str:
    """Helper: create viewer user and return bearer token."""
    employee = db.create_employee("VIEWER-001", "Test Viewer")
    auth_service.create_user(
        username="testviewer",
        password="viewerpass123",
        role="viewer",
        employee_internal_id=employee["id"],
    )
    result = auth_service.login("testviewer", "viewerpass123")
    return result["access_token"]


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── POST /api/employees ─────────────────────────────────────────────────


def test_create_employee(fresh_db):
    token = _create_admin_token()
    resp = client.post(
        "/api/employees",
        json={
            "employee_id": "EMP-001",
            "name": "Alice",
            "email": "alice@example.com",
        },
        headers=_auth_header(token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "success"
    emp = data["employee"]
    assert emp["employee_id"] == "EMP-001"
    assert emp["name"] == "Alice"
    assert emp["email"] == "alice@example.com"
    assert emp["status"] == "active"
    assert emp["id"] is not None


def test_create_employee_minimal(fresh_db):
    token = _create_admin_token()
    resp = client.post(
        "/api/employees",
        json={"employee_id": "EMP-002", "name": "Bob"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201
    emp = resp.json()["employee"]
    assert emp["email"] is None
    assert emp["status"] == "active"


def test_create_employee_duplicate(fresh_db):
    token = _create_admin_token()
    client.post(
        "/api/employees",
        json={"employee_id": "DUP-001", "name": "First"},
        headers=_auth_header(token),
    )
    resp = client.post(
        "/api/employees",
        json={"employee_id": "DUP-001", "name": "Second"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 409


def test_create_employee_requires_admin(fresh_db):
    viewer_token = _create_viewer_token()
    resp = client.post(
        "/api/employees",
        json={"employee_id": "EMP-X", "name": "X"},
        headers=_auth_header(viewer_token),
    )
    assert resp.status_code == 403


def test_create_employee_requires_auth(fresh_db):
    resp = client.post(
        "/api/employees",
        json={"employee_id": "EMP-Y", "name": "Y"},
    )
    assert resp.status_code == 401


# ── GET /api/employees ──────────────────────────────────────────────────


def test_list_employees(fresh_db):
    token = _create_admin_token()
    # Create 2 employees
    client.post(
        "/api/employees",
        json={"employee_id": "EMP-010", "name": "A"},
        headers=_auth_header(token),
    )
    client.post(
        "/api/employees",
        json={"employee_id": "EMP-011", "name": "B", "status": "inactive"},
        headers=_auth_header(token),
    )

    resp = client.get("/api/employees", headers=_auth_header(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert len(data["employees"]) == 2


def test_list_employees_filter_status(fresh_db):
    token = _create_admin_token()
    client.post(
        "/api/employees",
        json={"employee_id": "EMP-020", "name": "Active1"},
        headers=_auth_header(token),
    )
    client.post(
        "/api/employees",
        json={"employee_id": "EMP-021", "name": "Inactive1", "status": "inactive"},
        headers=_auth_header(token),
    )

    resp = client.get(
        "/api/employees?status=active", headers=_auth_header(token)
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["employees"][0]["name"] == "Active1"


def test_list_employees_requires_auth(fresh_db):
    resp = client.get("/api/employees")
    assert resp.status_code == 401


def test_list_employees_viewer_can_read(fresh_db):
    admin_token = _create_admin_token()
    viewer_token = _create_viewer_token()
    client.post(
        "/api/employees",
        json={"employee_id": "EMP-030", "name": "C"},
        headers=_auth_header(admin_token),
    )
    resp = client.get("/api/employees", headers=_auth_header(viewer_token))
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


# ── GET /api/employees/{id} ─────────────────────────────────────────────


def test_get_employee(fresh_db):
    token = _create_admin_token()
    create_resp = client.post(
        "/api/employees",
        json={"employee_id": "EMP-040", "name": "Dave"},
        headers=_auth_header(token),
    )
    emp_id = create_resp.json()["employee"]["id"]

    resp = client.get(f"/api/employees/{emp_id}", headers=_auth_header(token))
    assert resp.status_code == 200
    assert resp.json()["employee"]["name"] == "Dave"


def test_get_employee_not_found(fresh_db):
    token = _create_admin_token()
    resp = client.get("/api/employees/99999", headers=_auth_header(token))
    assert resp.status_code == 404


def test_get_employee_requires_auth(fresh_db):
    resp = client.get("/api/employees/1")
    assert resp.status_code == 401


# ── PATCH /api/employees/{id} ───────────────────────────────────────────


def test_patch_employee_name(fresh_db):
    token = _create_admin_token()
    create_resp = client.post(
        "/api/employees",
        json={"employee_id": "EMP-050", "name": "OldName"},
        headers=_auth_header(token),
    )
    emp_id = create_resp.json()["employee"]["id"]

    resp = client.patch(
        f"/api/employees/{emp_id}",
        json={"name": "NewName"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    assert resp.json()["employee"]["name"] == "NewName"
    assert resp.json()["employee"]["employee_id"] == "EMP-050"


def test_patch_employee_email(fresh_db):
    token = _create_admin_token()
    create_resp = client.post(
        "/api/employees",
        json={"employee_id": "EMP-051", "name": "Eve"},
        headers=_auth_header(token),
    )
    emp_id = create_resp.json()["employee"]["id"]

    resp = client.patch(
        f"/api/employees/{emp_id}",
        json={"email": "eve@example.com"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    assert resp.json()["employee"]["email"] == "eve@example.com"


def test_patch_employee_clear_email(fresh_db):
    token = _create_admin_token()
    create_resp = client.post(
        "/api/employees",
        json={"employee_id": "EMP-052", "name": "Frank", "email": "old@test.com"},
        headers=_auth_header(token),
    )
    emp_id = create_resp.json()["employee"]["id"]

    resp = client.patch(
        f"/api/employees/{emp_id}",
        json={"email": None},
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    assert resp.json()["employee"]["email"] is None


def test_patch_employee_status(fresh_db):
    token = _create_admin_token()
    create_resp = client.post(
        "/api/employees",
        json={"employee_id": "EMP-053", "name": "Grace"},
        headers=_auth_header(token),
    )
    emp_id = create_resp.json()["employee"]["id"]

    resp = client.patch(
        f"/api/employees/{emp_id}",
        json={"status": "inactive"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    assert resp.json()["employee"]["status"] == "inactive"


def test_patch_employee_duplicate_employee_id(fresh_db):
    token = _create_admin_token()
    client.post(
        "/api/employees",
        json={"employee_id": "EMP-060", "name": "First"},
        headers=_auth_header(token),
    )
    create_resp = client.post(
        "/api/employees",
        json={"employee_id": "EMP-061", "name": "Second"},
        headers=_auth_header(token),
    )
    emp_id = create_resp.json()["employee"]["id"]

    resp = client.patch(
        f"/api/employees/{emp_id}",
        json={"employee_id": "EMP-060"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 409


def test_patch_employee_not_found(fresh_db):
    token = _create_admin_token()
    resp = client.patch(
        "/api/employees/99999",
        json={"name": "Nobody"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 404


def test_patch_employee_requires_admin(fresh_db):
    admin_token = _create_admin_token()
    create_resp = client.post(
        "/api/employees",
        json={"employee_id": "EMP-070", "name": "Heidi"},
        headers=_auth_header(admin_token),
    )
    emp_id = create_resp.json()["employee"]["id"]

    viewer_token = _create_viewer_token()
    resp = client.patch(
        f"/api/employees/{emp_id}",
        json={"name": "Hacked"},
        headers=_auth_header(viewer_token),
    )
    assert resp.status_code == 403
