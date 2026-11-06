"""scripts/runtime_uji.py: ringkasan fps dan ANON dari events.ndjson + engine.log."""

import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "runtime_uji", Path(__file__).resolve().parents[2] / "scripts" / "runtime_uji.py")
runtime_uji = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime_uji)


def test_ringkasan_fps_dan_anon(tmp_path):
    def health(ts, fps):
        return {"type": "engine.health", "ts": ts, "drop_rate": 0.1,
                "camera_metrics": {"cam0": {"effective_fps": fps, "lag_seconds": 0.5}}}
    msgs = [
        health("2026-11-06T00:00:00Z", 2.0),          # pemanasan, dibuang
        health("2026-11-06T00:01:00.5Z", 9.0),
        health("2026-11-06T00:01:10Z", 10.0),
        {"type": "track.started", "camera_id": "cam0", "track_uuid": "tr_a"},
        {"type": "track.started", "camera_id": "cam0", "track_uuid": "tr_b"},
        {"type": "track.heartbeat", "track_uuid": "tr_a", "person_id": "ANON-1a2b", "identity_source": "reid"},
        {"type": "track.heartbeat", "track_uuid": "tr_b", "person_id": "ANON-1a2b", "identity_source": "reid"},
        {"type": "track.heartbeat", "track_uuid": "tr_b", "person_id": "emp_7", "identity_source": "reid_retro"},
        {"type": "identity.resolved", "anon_id": "ANON-1a2b", "person_id": "emp_7"},
    ]
    (tmp_path / "events.ndjson").write_text("".join(json.dumps(m) + "\n" for m in msgs))
    (tmp_path / "engine.log").write_text("INFO engine.runtime.service: detector bersama: 3 kamera, 25 ms/gambar\n")

    s = runtime_uji.summarize(tmp_path)
    assert s["cameras"]["cam0"]["fps_mean"] == 9.5 and s["cameras"]["cam0"]["fps_min"] == 9.0
    assert s["tracks_started"] == {"cam0": 2}
    assert s["anon_ids"] == 1 and s["named_people"] == 1 and s["identity_resolved"] == 1
    assert s["tracks_by_last_source"] == {"reid": 1, "reid_retro": 1}
    assert "25 ms/gambar" in s["engine_log_last"]["detector bersama:"]
