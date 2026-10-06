from __future__ import annotations

import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.core.state import SystemState
from backend.routers import attendance
from backend.services.break_policy import break_policy
from backend.schemas.protocol import parse_message


def test_view_frame_creates_a_backend_timer(monkeypatch):
    clock = {"now": 100.0}
    monkeypatch.setattr("backend.core.state.time.time", lambda: clock["now"])
    state = SystemState()

    enriched = state.update_view_frame({
        "type": "view.frame",
        "camera_id": "r1",
        "boxes": [{
            "track_uuid": "tr-r1-1",
            "bbox": [0.1, 0.1, 0.3, 0.5],
            "person_id": None,
        }],
    })
    assert enriched["boxes"][0]["session_elapsed"] == 0.0

    clock["now"] = 105.4
    sessions = state.get_active_sessions()
    assert len(sessions) == 1
    assert sessions[0]["track_id"] == "tr-r1-1"
    assert sessions[0]["session_elapsed"] == pytest.approx(5.4)
    assert sessions[0]["formatted_duration"] == "5s"
    assert sessions[0]["presence_status"] == "VERIFYING"
    assert sessions[0]["qualification_remaining_seconds"] == pytest.approx(14.6)
    assert sessions[0]["daily_used_seconds"] == 0.0


def test_passing_person_is_not_charged_and_charge_starts_after_20_seconds(monkeypatch):
    clock = {"now": 100.0}
    monkeypatch.setattr("backend.core.state.time.time", lambda: clock["now"])
    state = SystemState()
    state.update_view_frame({
        "type": "view.frame", "camera_id": "r1",
        "boxes": [{"track_uuid": "track-1", "bbox": [0, 0, 1, 1], "person_id": "E01"}],
    })

    clock["now"] = 119.0
    state.update_view_frame({
        "type": "view.frame", "camera_id": "r1",
        "boxes": [{"track_uuid": "track-1", "bbox": [0, 0, 1, 1], "person_id": "E01"}],
    })
    at_19 = state.get_active_sessions()[0]
    assert at_19["presence_status"] == "VERIFYING"
    assert at_19["daily_used_seconds"] == 0

    clock["now"] = 125.0
    state.update_view_frame({
        "type": "view.frame", "camera_id": "r1",
        "boxes": [{"track_uuid": "track-1", "bbox": [0, 0, 1, 1], "person_id": "E01"}],
    })
    at_25 = state.get_active_sessions()[0]
    assert at_25["presence_status"] == "CONFIRMED"
    # view.frame is display-only and must never charge
    # the durable free-time ledger.
    assert at_25["daily_used_seconds"] == 0.0
    assert at_25["remaining_seconds"] == pytest.approx(
        break_policy.allowance_seconds
    )


def test_timer_pauses_during_official_break(monkeypatch):
    jakarta = ZoneInfo("Asia/Jakarta")
    clock = {"now": datetime(2026, 9, 22, 11, 59, 50, tzinfo=jakarta).timestamp()}
    monkeypatch.setattr("backend.core.state.time.time", lambda: clock["now"])
    state = SystemState()
    state.update_view_frame({
        "type": "view.frame", "camera_id": "r1",
        "boxes": [{"track_uuid": "track-1", "bbox": [0, 0, 1, 1], "person_id": "E01"}],
    })

    clock["now"] = datetime(2026, 9, 22, 12, 30, tzinfo=jakarta).timestamp()
    state.update_view_frame({
        "type": "view.frame", "camera_id": "r1",
        "boxes": [{"track_uuid": "track-1", "bbox": [0, 0, 1, 1], "person_id": "E01"}],
    })
    during_break = state.get_active_sessions()[0]
    assert during_break["presence_status"] == "OFFICIAL_BREAK"
    assert during_break["qualification_remaining_seconds"] == pytest.approx(10.0)
    assert during_break["daily_used_seconds"] == 0

    clock["now"] = datetime(2026, 9, 22, 13, 0, 15, tzinfo=jakarta).timestamp()
    state.update_view_frame({
        "type": "view.frame", "camera_id": "r1",
        "boxes": [{"track_uuid": "track-1", "bbox": [0, 0, 1, 1], "person_id": "E01"}],
    })
    after_break = state.get_active_sessions()[0]
    assert after_break["presence_status"] == "CONFIRMED"

    # view.frame hanya untuk realtime/display.
    # Free-time hanya dihitung dari durable engine events.
    assert after_break["daily_used_seconds"] == 0.0


def test_snapshot_schema_matches_contract_shape():
    parsed = parse_message({
        "type": "snapshot",
        "v": 1,
        "ts": "2026-09-22T01:00:00Z",
        "seq": 1,
        "pts_wallclock_offset": {
            "r1": {"stream_epoch": 1, "offset": 100.0},
        },
        "live": [{
            "track_uuid": "tr-r1-1",
            "camera_id": "r1",
            "stream_epoch": 1,
            "person_id": None,
            "since_pts": 0.0,
        }],
    })
    assert parsed.live[0].stream_epoch == 1
    assert parsed.pts_wallclock_offset["r1"].offset == 100.0

def test_breaks_endpoint_returns_frontend_shape(monkeypatch):
    start = datetime.fromisoformat(
        "2026-09-22T01:00:00+00:00"
    ).timestamp()

    end = datetime.fromisoformat(
        "2026-09-22T01:10:00+00:00"
    ).timestamp()

    monkeypatch.setattr(
        attendance.free_time_ledger,
        "known_person_ids",
        lambda: {"4471"},
    )

    monkeypatch.setattr(
        attendance.free_time_ledger,
        "usage",
        lambda person_id, local_date: {
            "person_id": person_id,
            "date": local_date,
            "used_seconds": 600.0,
            "allowance_seconds": 1800.0,
            "remaining_seconds": 1200.0,
            "status": "ok",
            "adjustment_seconds": 0.0,
            "present": False,
            "qualification_remaining_seconds": 0.0,
            "is_official_break": False,
            "visits": [
                {
                    "visit_id": "visit-test",
                    "start_ts": start,
                    "end_ts": end,
                    "cameras": ["r1"],
                    "open": False,
                    "countable_seconds": 620.0,
                    "charged_seconds": 600.0,
                    "original_charged_seconds": 600.0,
                    "excluded": False,
                }
            ],
        },
    )

    response = attendance.get_all_break_usage(
        "2026-09-22"
    )

    usage = response["data"][0]

    assert response["status"] == "success"
    assert usage["person_id"] == "4471"
    assert usage["break_count"] == 1
    assert usage["used_minutes"] == 10.0
    assert (
        usage["breaks"][0]["duration_seconds"]
        == 600.0
    )