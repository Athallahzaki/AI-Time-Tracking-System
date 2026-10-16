from datetime import datetime
from backend.schemas.attendance import GapClassification
from backend.services.break_policy import BreakPolicy
from backend.routers import attendance

def test_breaks_endpoint_returns_frontend_shape(
    monkeypatch,
):
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