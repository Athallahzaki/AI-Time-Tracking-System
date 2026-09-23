"""Jatah free time = waktu TERLIHAT di ruang fasilitas, dari event durabel."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.core import database
from backend.services.break_policy import BreakPolicy
from backend.services.free_time import FreeTimeLedger

JKT = ZoneInfo("Asia/Jakarta")
DAY = "2026-09-22"


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "backend.db")
    database.init_database()
    return database


def at(hh, mm, ss=0):
    return datetime(2026, 9, 22, hh, mm, ss, tzinfo=JKT)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


_seq = {"n": 0}


def store(event, outbox="ob-1"):
    _seq["n"] += 1
    event = {"v": 1, "ts": event.get("at") or event.get("end_at"), **event}
    ts = datetime.fromisoformat(event["ts"].replace("Z", "+00:00")).timestamp()
    database.save_protocol_event(ts, event["type"], event, _seq["n"], outbox)
    return event


def interval(person, cam, start, end, iid):
    return store({
        "type": "presence.interval", "interval_id": iid, "person_id": person,
        "camera_id": cam, "stream_epoch": 0, "start_at": iso(start), "end_at": iso(end),
        "start_zone": "interior", "end_zone": "interior", "end_reason": "left_frame",
        "identity_confidence": 0.9, "evidence_count": 2,
    })


def policy(**kw):
    return BreakPolicy(**kw)


def test_same_person_on_two_cameras_is_charged_once(db):
    interval("4471", "r1", at(10, 0), at(10, 10), "iv_a")
    interval("4471", "r2", at(10, 0), at(10, 10), "iv_b")
    usage = FreeTimeLedger(policy()).usage("4471", DAY, now=at(11, 0).timestamp())
    # 600 s present, first 20 s free -> 580, not 1160.
    assert usage["used_seconds"] == pytest.approx(580.0)
    assert len(usage["visits"]) == 1
    assert sorted(usage["visits"][0]["cameras"]) == ["r1", "r2"]


def test_passer_by_is_free_and_charge_starts_after_qualification(db):
    interval("E1", "r1", at(9, 0, 0), at(9, 0, 15), "iv_1")     # 15 s: passing
    interval("E1", "r1", at(9, 30, 0), at(9, 30, 25), "iv_2")   # 25 s: 5 s charged
    usage = FreeTimeLedger(policy()).usage("E1", DAY, now=at(10, 0).timestamp())
    assert usage["used_seconds"] == pytest.approx(5.0)


def test_occlusion_gap_merges_into_one_visit(db):
    interval("E1", "r1", at(9, 0, 0), at(9, 0, 15), "iv_1")
    interval("E1", "r1", at(9, 0, 25), at(9, 0, 40), "iv_2")   # 10 s occlusion
    usage = FreeTimeLedger(policy(visit_merge_gap_seconds=30)).usage(
        "E1", DAY, now=at(10, 0).timestamp())
    assert len(usage["visits"]) == 1
    assert usage["used_seconds"] == pytest.approx(20.0)        # 40 s span - 20 s grace


def test_official_break_respects_minutes(db):
    interval("E1", "r1", at(12, 0), at(14, 0), "iv_1")
    p = policy(official_breaks=[(12 * 60 + 30, 13 * 60 + 30)])
    usage = FreeTimeLedger(p).usage("E1", DAY, now=at(15, 0).timestamp())
    # 2 h present, 12:30-13:30 not counted -> 3600 s - 20 s grace.
    assert usage["used_seconds"] == pytest.approx(3580.0)


def test_open_presence_from_durable_track_events(db):
    ledger = FreeTimeLedger(policy())
    for event in [
        {"type": "track.started", "track_uuid": "tr_1", "camera_id": "r1",
         "stream_epoch": 0, "pts": 0.0, "at": iso(at(10, 0)), "zone": "interior"},
        {"type": "track.identified", "track_uuid": "tr_1", "person_id": "E1", "pts": 8.0,
         "at": iso(at(10, 0, 8)), "track_started_pts": 0.0, "similarity": 0.8,
         "margin": 0.2, "evidence_count": 2},
    ]:
        ledger.apply_event(store(event))
    usage = ledger.usage("E1", DAY, now=at(10, 1, 0).timestamp())
    assert usage["present"] is True
    # Counted from the track's birth (10:00:00), not from the face read (10:00:08).
    assert usage["used_seconds"] == pytest.approx(40.0)


def test_open_presence_stops_when_engine_goes_silent(db):
    ledger = FreeTimeLedger(policy(open_presence_stale_seconds=90))
    ledger.apply_event(store({"type": "track.started", "track_uuid": "tr_1", "camera_id": "r1",
                              "stream_epoch": 0, "pts": 0.0, "at": iso(at(10, 0)), "zone": "interior"}))
    ledger.apply_event(store({"type": "track.identified", "track_uuid": "tr_1", "person_id": "E1",
                              "pts": 1.0, "at": iso(at(10, 0, 1)), "track_started_pts": 0.0,
                              "similarity": 0.8, "margin": 0.2, "evidence_count": 1}))
    usage = ledger.usage("E1", DAY, now=at(11, 0).timestamp())
    # last news at 10:00:01 + 90 s stale window, not a whole hour.
    assert usage["used_seconds"] == pytest.approx(71.0)


def test_closed_track_is_not_double_counted(db):
    ledger = FreeTimeLedger(policy())
    ledger.apply_event(store({"type": "track.started", "track_uuid": "tr_1", "camera_id": "r1",
                              "stream_epoch": 0, "pts": 0.0, "at": iso(at(10, 0)), "zone": "interior"}))
    ledger.apply_event(store({"type": "track.identified", "track_uuid": "tr_1", "person_id": "E1",
                              "pts": 1.0, "at": iso(at(10, 0, 1)), "track_started_pts": 0.0,
                              "similarity": 0.8, "margin": 0.2, "evidence_count": 1}))
    closed = interval("E1", "r1", at(10, 0), at(10, 5), "iv_1")
    closed["track_uuid"] = "tr_1"
    ledger.apply_event(closed)
    ledger.apply_event(store({"type": "track.ended", "track_uuid": "tr_1", "pts": 300.0,
                              "at": iso(at(10, 5)), "reason": "left_frame", "exit_zone": "interior"}))
    usage = ledger.usage("E1", DAY, now=at(11, 0).timestamp())
    assert usage["used_seconds"] == pytest.approx(280.0)
    assert usage["present"] is False


def test_rebuild_after_backend_restart(db):
    store({"type": "track.started", "track_uuid": "tr_1", "camera_id": "r1",
           "stream_epoch": 0, "pts": 0.0, "at": iso(at(10, 0)), "zone": "interior"})
    store({"type": "track.identified", "track_uuid": "tr_1", "person_id": "E1", "pts": 1.0,
           "at": iso(at(10, 0, 1)), "track_started_pts": 0.0, "similarity": 0.8,
           "margin": 0.2, "evidence_count": 1})
    store({"type": "track.heartbeat", "track_uuid": "tr_1", "person_id": "E1", "pts": 30.0,
           "at": iso(at(10, 0, 30)), "identity_source": "tracking", "confidence": 0.8})
    fresh = FreeTimeLedger(policy())
    fresh.rebuild_from_database(lookback_hours=24 * 3650)
    usage = fresh.usage("E1", DAY, now=at(10, 1).timestamp())
    assert usage["present"] is True
    assert usage["used_seconds"] == pytest.approx(40.0)


def test_many_old_intervals_do_not_hide_today(db):
    old = datetime(2026, 8, 1, 9, 0, tzinfo=JKT)
    for index in range(1100):
        start = old.replace(minute=0) .timestamp() + index * 60
        s = datetime.fromtimestamp(start, JKT)
        interval("E9", "r1", s, datetime.fromtimestamp(start + 30, JKT), f"iv_old{index}")
    interval("E1", "r1", at(10, 0), at(10, 1), "iv_today")
    usage = FreeTimeLedger(policy()).usage("E1", DAY, now=at(11, 0).timestamp())
    assert usage["used_seconds"] == pytest.approx(40.0)


def test_corrections_exclude_visit_and_adjust(db):
    interval("E1", "r1", at(9, 0), at(9, 10), "iv_1")
    interval("E1", "r1", at(15, 0), at(15, 5), "iv_2")
    ledger = FreeTimeLedger(policy())
    before = ledger.usage("E1", DAY, now=at(16, 0).timestamp())
    assert before["used_seconds"] == pytest.approx(580.0 + 280.0)

    database.save_correction({"correction_id": "c1", "person_id": "E1", "date": DAY,
                              "gap_id": "visit_iv_1", "exclude_visit": True})
    database.save_correction({"correction_id": "c2", "person_id": "E1", "date": DAY,
                              "adjustment_seconds": -60.0})
    ledger.invalidate()
    after = ledger.usage("E1", DAY, now=at(16, 0).timestamp())
    assert after["used_seconds"] == pytest.approx(280.0 - 60.0)
    assert [v["excluded"] for v in after["visits"]] == [True, False]


def test_limit_status(db):
    interval("E1", "r1", at(9, 0), at(9, 40), "iv_1")
    usage = FreeTimeLedger(policy()).usage("E1", DAY, now=at(10, 0).timestamp())
    assert usage["status"] == "exceeded"
    assert usage["remaining_seconds"] == 0


def test_policy_file_keeps_minutes(tmp_path):
    from backend.services.break_policy import load_break_policy
    path = tmp_path / "p.yaml"
    path.write_text('official_break:\n  start: "12:30"\n  end: "13:15"\n', encoding="utf-8")
    loaded = load_break_policy(path)
    assert loaded.official_breaks == [(750, 795)]
