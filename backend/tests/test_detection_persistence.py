from __future__ import annotations

import sqlite3

from backend.core import database


def test_detection_frame_is_normalized_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "backend.db")
    database.init_database()
    message = {
        "type": "view.frame",
        "camera_id": "r1",
        "stream_epoch": 1,
        "pts": 10.0,
        "width": 848,
        "height": 478,
        "fps": 25.0,
        "boxes": [{
            "track_uuid": "tr_r1-t1-g1",
            "person_id": "pegawai-1",
            "confidence": 0.9,
            "bbox": [0.1, 0.2, 0.3, 0.8],
            "session_elapsed": 10.0,
            "presence_status": "VERIFYING",
            "daily_used_seconds": 0.0,
            "remaining_seconds": 1800.0,
        }],
    }

    assert database.save_detection_frame(message, observed_at=1000.0) is True
    assert database.save_detection_frame(message, observed_at=1001.0) is False

    rows = database.get_detection_observations(camera_id="r1")
    assert len(rows) == 1
    assert rows[0]["track_uuid"] == "tr_r1-t1-g1"
    assert rows[0]["session_elapsed"] == 10.0
    with sqlite3.connect(database.DB_PATH) as conn:
        assert conn.execute("SELECT COUNT(*) FROM detection_frames").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM track_sessions").fetchone()[0] == 1


def test_empty_frame_closes_active_track(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "backend.db")
    database.init_database()
    base = {
        "type": "view.frame", "camera_id": "r1", "stream_epoch": 2,
        "pts": 1.0, "boxes": [{
            "track_uuid": "track-1", "bbox": [0.0, 0.0, 0.2, 0.4],
            "session_elapsed": 1.0,
        }],
    }
    database.save_detection_frame(base, observed_at=10.0)
    database.save_detection_frame(
        {**base, "pts": 2.0, "boxes": []}, observed_at=11.0
    )

    with sqlite3.connect(database.DB_PATH) as conn:
        active, ended_pts = conn.execute(
            "SELECT is_active, ended_pts FROM track_sessions"
        ).fetchone()
    assert active == 0
    assert ended_pts == 2.0

