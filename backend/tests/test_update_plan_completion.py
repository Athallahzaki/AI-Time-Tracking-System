from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.core import database as db
from backend.main import app
from backend.services.auth_service import auth_service

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    db.DB_PATH = tmp_path / "completion.db"
    db._initialized_for = None
    db.init_database()
    yield
    db._initialized_for = None


def _header(username="admin", role="admin", employee_internal_id=None):
    auth_service.create_user(username, "password-123", role, employee_internal_id)
    token = auth_service.login(username, "password-123")["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_last_admin_cannot_be_disabled():
    header = _header()
    user_id = db.get_user_by_username("admin")["id"]
    response = client.patch(f"/api/auth/users/{user_id}", json={"enabled": False}, headers=header)
    assert response.status_code == 409


def test_viewer_cannot_read_another_employee():
    own = db.create_employee("EMP-1", "Own")
    other = db.create_employee("EMP-2", "Other")
    header = _header("viewer", "viewer", own["id"])
    response = client.get(f"/api/employees/{other['id']}", headers=header)
    assert response.status_code == 403


def test_backward_reid_is_non_destructive_overlay():
    employee = db.create_employee("EMP-1", "Employee")
    start, end = 1_000.0, 1_060.0
    payload = {
        "type": "presence.interval", "track_uuid": "track-1", "camera_id": "r1",
        "person_id": None,
        "start_at": datetime.fromtimestamp(start, timezone.utc).isoformat(),
        "end_at": datetime.fromtimestamp(end, timezone.utc).isoformat(),
    }
    db.save_protocol_event(start, "presence.interval", payload, 1, "outbox")
    db.save_attribution({
        "event_outbox_id": "outbox", "event_seq": 2,
        "employee_internal_id": employee["id"], "track_uuid": "track-1",
        "camera_id": "r1", "window_start": start, "window_end": end,
        "attribution_source": "identity_changed", "attribution_confidence": 1.0,
        "needs_hr_review": False, "evidence": [],
    })
    effective = db.get_presence_intervals(900, 1_200, "EMP-1")
    raw = db.get_protocol_events(event_type="presence.interval")
    assert effective[0]["identity_source"] == "reid_retro"
    assert raw[0]["payload"]["person_id"] is None


def test_report_claim_can_retry_failed_revision():
    run_id = db.claim_report_run("2026-10-16")
    db.finish_report_run(run_id, "failed", "temporary")
    assert db.claim_report_run("2026-10-16") == run_id
