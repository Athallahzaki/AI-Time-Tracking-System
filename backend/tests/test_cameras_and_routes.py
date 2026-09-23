from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.core import database
from backend.core.config import CameraConfigError, load_cameras_from_yaml, settings

JKT = ZoneInfo("Asia/Jakarta")

CAMERAS = """
cameras:
  - id: "r1"
    source_uri: "rtsp://localhost:8554/cam01"
    allowed_sources: ["rtsp://localhost:8554/cam01-backup"]
    door_region: [0.6, 0.1, 0.95, 0.55]
    enabled_by_default: true
  - id: "r2"
    source_uri: "rtsp://localhost:8554/cam02"
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "backend.db")
    database.init_database()
    path = tmp_path / "cameras.yaml"
    path.write_text(CAMERAS, encoding="utf-8")
    monkeypatch.setattr(settings, "cameras_yaml_path", path)
    monkeypatch.setattr(settings, "_cameras_cache", None)
    from backend.services.free_time import free_time_ledger
    free_time_ledger.tracker.clear()
    free_time_ledger.invalidate()
    yield path
    settings._cameras_cache = None


def test_broken_cameras_yaml_fails_loudly(tmp_path):
    path = tmp_path / "cameras.yaml"
    path.write_text("cameras: [ {id: r1, source_uri: x", encoding="utf-8")
    with pytest.raises(CameraConfigError):
        load_cameras_from_yaml(path)
    path.write_text("cameras: []", encoding="utf-8")
    with pytest.raises(CameraConfigError):
        load_cameras_from_yaml(path)


def test_set_cameras_carries_door_region_and_persisted_overrides(env):
    from backend.services.camera_state import set_cameras_message
    database.set_camera_override("r2", enabled=True)
    message = set_cameras_message()
    by_id = {c["camera_id"]: c for c in message["cameras"]}
    assert by_id["r1"]["door_region"] == [0.6, 0.1, 0.95, 0.55]
    assert "door_region" not in by_id["r2"]
    assert by_id["r2"]["enabled"] is True          # operator override survives reconnect
    from contracts.validator import SchemaValidator
    assert not SchemaValidator().validate_message({**message, "channel": "control"})


def test_source_switch_is_restricted_to_allow_list(env):
    from fastapi import HTTPException
    from backend.routers import cameras
    with pytest.raises(HTTPException) as denied:
        cameras.switch_camera_source("r1", cameras.SwitchSourceRequest(source_uri="/etc/passwd"))
    assert denied.value.status_code == 403
    ok = cameras.switch_camera_source(
        "r1", cameras.SwitchSourceRequest(source_uri="rtsp://localhost:8554/cam01-backup"))
    assert ok["status"] == "success"
    listed = {c["id"]: c for c in cameras.list_cameras()["cameras"]}
    assert listed["r1"]["source_uri"] == "rtsp://localhost:8554/cam01-backup"


def _interval(person, start, end, iid, seq):
    iso = lambda dt: dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    event = {
        "type": "presence.interval", "v": 1, "ts": iso(end), "interval_id": iid,
        "person_id": person, "camera_id": "r1", "stream_epoch": 0,
        "start_at": iso(start), "end_at": iso(end), "start_zone": "interior",
        "end_zone": "interior", "end_reason": "left_frame",
        "identity_confidence": 0.9, "evidence_count": 2,
    }
    database.save_protocol_event(end.timestamp(), event["type"], event, seq, "ob")


def test_breaks_endpoint_reports_facility_visits(env):
    from backend.routers import attendance
    day = datetime(2026, 9, 22, tzinfo=JKT)
    _interval("4471", day.replace(hour=9), day.replace(hour=9, minute=10), "iv_1", 1)
    _interval("4471", day.replace(hour=15), day.replace(hour=15, minute=10), "iv_2", 2)
    response = attendance.get_all_break_usage("2026-09-22")
    usage = next(u for u in response["data"] if u["person_id"] == "4471")
    assert usage["break_count"] == 2
    assert usage["used_minutes"] == pytest.approx((580 + 580) / 60, abs=0.01)
    assert usage["breaks"][0]["gap_id"] == "visit_iv_1"
    assert usage["status"] == "ok"


def test_correction_is_applied_and_listed(env):
    from backend.routers import attendance
    from backend.schemas.corrections import CorrectionCreate
    day = datetime(2026, 9, 22, tzinfo=JKT)
    _interval("4471", day.replace(hour=9), day.replace(hour=9, minute=10), "iv_1", 1)
    attendance.create_manual_correction(CorrectionCreate(
        person_id="4471", date="2026-09-22", gap_id="visit_iv_1",
        new_classification="not_free_time", corrected_by="hr", reason="rapat",
    ))
    usage = attendance.get_break_usage("4471", "2026-09-22")
    assert usage["used_minutes"] == 0
    assert usage["breaks"][0]["corrected"] is True
    events = attendance.get_recent_events(50)["events"]
    assert any(e["type"] == "ManualCorrectionEvent" for e in events)


def test_overlay_uses_the_durable_ledger(env, monkeypatch):
    from backend.core import state as state_module
    from backend.services.free_time import free_time_ledger
    day = datetime(2026, 9, 22, tzinfo=JKT)
    _interval("4471", day.replace(hour=9), day.replace(hour=9, minute=40), "iv_1", 1)
    now = day.replace(hour=10).timestamp()
    monkeypatch.setattr(state_module.time, "time", lambda: now)
    state = state_module.SystemState(ledger=free_time_ledger)
    enriched = state.update_view_frame({
        "type": "view.frame", "camera_id": "r1",
        "boxes": [{"track_uuid": "tr_x", "bbox": [0, 0, 1, 1], "person_id": "4471"}],
    })
    box = enriched["boxes"][0]
    assert box["daily_used_seconds"] == pytest.approx(2380.0)
    assert box["remaining_seconds"] == 0
