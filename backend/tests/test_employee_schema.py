"""Tests for Phase 1B — Upgrade Employee Schema.

Verifies:
- New columns (email, status, updated_at) exist and have correct defaults.
- Migration is idempotent (safe to call twice).
- Old rows get updated_at = created_at via migration.
- create_employee returns all columns.
- get_employees returns all columns.
- get_employee_by_id / get_employee_by_employee_id work.
- update_employee partial update works.
- Status validation (only active/inactive).
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import time

import pytest

# Override DB path before importing database module.
_tmpdir = tempfile.mkdtemp()
os.environ["BACKEND_DB_PATH"] = os.path.join(_tmpdir, "test_1b.db")

from backend.core import database as db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """Give each test a clean database."""
    test_db = str(tmp_path / "test.db")
    db.DB_PATH = type(db.DB_PATH)(test_db)
    db._initialized_for = None
    db.init_database()
    yield
    db._initialized_for = None


# ── Schema existence ──────────────────────────────────────────────────────


def test_employees_table_has_new_columns(fresh_db):
    with db.connect() as conn:
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(employees)").fetchall()
        }
    assert "email" in cols
    assert "status" in cols
    assert "updated_at" in cols


def test_migration_is_idempotent(fresh_db):
    """Running init_database twice must not fail."""
    db._initialized_for = None
    db.init_database()  # second call — should be safe
    with db.connect() as conn:
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(employees)").fetchall()
        }
    assert "email" in cols
    assert "status" in cols
    assert "updated_at" in cols


# ── Migration back-fills ──────────────────────────────────────────────────


def test_migration_backfills_updated_at(tmp_path):
    """Simulates an old DB without the new columns and verifies migration."""
    old_db = str(tmp_path / "old.db")
    db.DB_PATH = type(db.DB_PATH)(old_db)
    db._initialized_for = None

    # Create the old-style table manually.
    conn = sqlite3.connect(old_db)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    created = time.time() - 86400
    conn.execute(
        "INSERT INTO employees (employee_id, name, created_at) VALUES (?, ?, ?)",
        ("OLD-001", "Legacy Worker", created),
    )
    conn.commit()
    conn.close()

    # Now run init_database which should migrate.
    db.init_database()

    with db.connect() as conn:
        row = conn.execute(
            "SELECT email, status, updated_at FROM employees WHERE employee_id = ?",
            ("OLD-001",),
        ).fetchone()

    assert row is not None
    email, status, updated_at = row
    assert email is None  # no email set
    assert status == "active"  # default
    assert updated_at == pytest.approx(created, abs=0.01)  # backfill


# ── create_employee ──────────────────────────────────────────────────────


def test_create_employee_returns_all_fields(fresh_db):
    emp = db.create_employee("EMP-001", "Alice")
    assert emp["id"] is not None
    assert emp["employee_id"] == "EMP-001"
    assert emp["name"] == "Alice"
    assert emp["email"] is None
    assert emp["status"] == "active"
    assert emp["created_at"] == emp["updated_at"]


def test_create_employee_with_email_and_status(fresh_db):
    emp = db.create_employee(
        "EMP-002", "Bob", email="bob@example.com", status="inactive"
    )
    assert emp["email"] == "bob@example.com"
    assert emp["status"] == "inactive"


def test_create_employee_duplicate_employee_id_fails(fresh_db):
    db.create_employee("EMP-DUP", "First")
    with pytest.raises(sqlite3.IntegrityError):
        db.create_employee("EMP-DUP", "Second")


# ── get_employees ────────────────────────────────────────────────────────


def test_get_employees_returns_new_fields(fresh_db):
    db.create_employee("EMP-010", "Charlie", email="c@test.com")
    db.create_employee("EMP-011", "Diana", status="inactive")

    employees = db.get_employees()
    assert len(employees) == 2

    charlie = employees[0]
    assert charlie["id"] is not None
    assert charlie["email"] == "c@test.com"
    assert charlie["status"] == "active"
    assert charlie["updated_at"] is not None


def test_get_employees_status_filter(fresh_db):
    db.create_employee("EMP-020", "Active1")
    db.create_employee("EMP-021", "Inactive1", status="inactive")
    db.create_employee("EMP-022", "Active2")

    active = db.get_employees(status_filter="active")
    assert len(active) == 2
    assert all(e["status"] == "active" for e in active)

    inactive = db.get_employees(status_filter="inactive")
    assert len(inactive) == 1
    assert inactive[0]["name"] == "Inactive1"


# ── get_employee_by_id / get_employee_by_employee_id ─────────────────────


def test_get_employee_by_id(fresh_db):
    created = db.create_employee("EMP-030", "Eve")
    found = db.get_employee_by_id(created["id"])
    assert found is not None
    assert found["employee_id"] == "EMP-030"


def test_get_employee_by_id_not_found(fresh_db):
    assert db.get_employee_by_id(99999) is None


def test_get_employee_by_employee_id(fresh_db):
    db.create_employee("NIP-123", "Frank")
    found = db.get_employee_by_employee_id("NIP-123")
    assert found is not None
    assert found["name"] == "Frank"


def test_get_employee_by_employee_id_not_found(fresh_db):
    assert db.get_employee_by_employee_id("NONEXISTENT") is None


# ── update_employee ──────────────────────────────────────────────────────


def test_update_employee_name(fresh_db):
    emp = db.create_employee("EMP-040", "OldName")
    updated = db.update_employee(emp["id"], name="NewName")
    assert updated is not None
    assert updated["name"] == "NewName"
    assert updated["employee_id"] == "EMP-040"  # unchanged
    assert updated["updated_at"] > emp["updated_at"]


def test_update_employee_email(fresh_db):
    emp = db.create_employee("EMP-041", "Grace")
    updated = db.update_employee(emp["id"], email="grace@example.com")
    assert updated["email"] == "grace@example.com"


def test_update_employee_clear_email(fresh_db):
    emp = db.create_employee("EMP-042", "Heidi", email="old@test.com")
    updated = db.update_employee(emp["id"], email=None)
    assert updated["email"] is None


def test_update_employee_status(fresh_db):
    emp = db.create_employee("EMP-043", "Ivan")
    updated = db.update_employee(emp["id"], status="inactive")
    assert updated["status"] == "inactive"


def test_update_employee_invalid_status(fresh_db):
    emp = db.create_employee("EMP-044", "Judy")
    with pytest.raises(ValueError, match="status must be"):
        db.update_employee(emp["id"], status="fired")


def test_update_employee_employee_id(fresh_db):
    emp = db.create_employee("EMP-045", "Karl")
    updated = db.update_employee(emp["id"], employee_id="EMP-045-NEW")
    assert updated["employee_id"] == "EMP-045-NEW"


def test_update_employee_not_found(fresh_db):
    assert db.update_employee(99999, name="Nobody") is None


def test_update_employee_no_changes(fresh_db):
    emp = db.create_employee("EMP-046", "Lara")
    result = db.update_employee(emp["id"])
    assert result is not None
    assert result["name"] == "Lara"


def test_update_employee_duplicate_employee_id_fails(fresh_db):
    db.create_employee("EMP-050", "First")
    emp2 = db.create_employee("EMP-051", "Second")
    with pytest.raises(sqlite3.IntegrityError):
        db.update_employee(emp2["id"], employee_id="EMP-050")
