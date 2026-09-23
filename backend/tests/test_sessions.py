from backend.services.break_policy import BreakPolicy
from backend.services.session_deriver import SessionDeriver


def _interval(identifier, start, end, *, start_zone="door", end_zone="door", reason="left_frame"):
    return {
        "type": "presence.interval",
        "interval_id": identifier,
        "person_id": "4471",
        "camera_id": "r1",
        "start_at": start,
        "end_at": end,
        "start_zone": start_zone,
        "end_zone": end_zone,
        "end_reason": reason,
        "identity_confidence": 0.9,
        "evidence_count": 3,
        "stream_epoch": 0,
    }


def test_door_gap_is_a_break():
    intervals = [
        _interval("iv_a", "2026-09-20T08:00:00Z", "2026-09-20T09:00:00Z"),
        _interval("iv_b", "2026-09-20T09:10:00Z", "2026-09-20T10:00:00Z"),
    ]
    result = SessionDeriver().classify_gaps(intervals, BreakPolicy())
    assert result["gaps"][0]["classification"] == "break"


def test_short_interior_gap_is_tracking_loss():
    intervals = [
        _interval(
            "iv_a", "2026-09-20T08:00:00Z", "2026-09-20T09:00:00Z",
            end_zone="interior", reason="occluded_timeout",
        ),
        _interval("iv_b", "2026-09-20T09:00:20Z", "2026-09-20T10:00:00Z"),
    ]
    result = SessionDeriver().classify_gaps(intervals, BreakPolicy())
    assert result["gaps"][0]["classification"] == "tracking_loss"
