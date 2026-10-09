"""Jadwal analisis kamera (paket ea-r5, kontrak ea-k1 `schedule_off`).

`core.analysis_off_mode: pause`: `set_cameras enabled=false` menjeda analisis,
kamera tetap hidup; track ditutup `schedule_off` + forced, tanpa camera.failed;
menyala lagi tanpa camera.online baru dan orangnya track baru. Default `stop`
(perilaku lama) tidak berubah.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from typing import Any, Dict, List

import numpy as np
import pytest

from contracts.validator import ConformanceChecker, SchemaValidator
from engine.api import events
from engine.config import load_config
from engine.identity import Evidence, InMemoryReferenceStore, MatrixMatcher, RecognitionScheduler
from engine.runtime import EngineRuntime, RuntimeOptions
from engine.runtime.camera import CameraSpec, CameraSupervisor

DOOR = [0.0, 0.0, 0.40, 0.40]


def _config(mode: str = "pause"):
    base = dataclasses.replace(load_config(), source_type="mock", auto_warmup=False,
                               analysis_off_mode=mode)
    return dataclasses.replace(base, recognition=dataclasses.replace(
        base.recognition, enabled=True, max_requests_per_frame=2))


def _collector():
    messages: List[Dict[str, Any]] = []
    lock = threading.Lock()

    def emit(message):
        with lock:
            message = dict(message, seq=len(messages) + 1)
            messages.append(message)
            return message

    return messages, emit


def _recognizer():
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    store = InMemoryReferenceStore({"4471": [vector]}, embedding_version="stub-v1")
    matcher = MatrixMatcher(store)
    matcher.rebuild()
    rng = np.random.default_rng(5)

    def recognize(track, frame):
        noisy = vector + rng.normal(0.0, 0.02, size=512).astype(np.float32)
        noisy /= np.linalg.norm(noisy)
        return Evidence(embedding=noisy, pts=frame.metadata.pts or 0.0,
                        quality=0.9, embedding_version="stub-v1")

    return matcher, recognize


def _wait(predicate, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_end_reason_schedule_off_dikenal_pembuat_event():
    clock = events.PtsClock("r1", 0, 1_700_000_000.0)
    message = events.track_ended(clock, "tr_x-1", 5.0, "schedule_off", "interior")
    assert message["reason"] == "schedule_off"


def test_mode_default_stop_dan_nilai_salah_ditolak(tmp_path):
    assert load_config().analysis_off_mode == "stop"
    for name in ("demo-4060", "demo-4060-tick", "demo-1060"):
        assert load_config(f"engine/config/{name}.yaml").analysis_off_mode == "stop"
    path = tmp_path / "c.yaml"
    path.write_text("core:\n  analysis_off_mode: pause\n", encoding="utf-8")
    assert load_config(str(path)).analysis_off_mode == "pause"
    with pytest.raises(ValueError, match="analysis_off_mode"):
        dataclasses.replace(load_config(), analysis_off_mode="tidur")


def test_jeda_jadwal_menutup_track_schedule_off_lalu_lanjut_tanpa_camera_online():
    matcher, recognize = _recognizer()
    messages, emit = _collector()
    views: List[Dict[str, Any]] = []
    camera = CameraSupervisor(
        spec=CameraSpec("r1", "mock", DOOR), config=_config(), emit_event=emit,
        emit_view=lambda m: views.append(m) or m,
        scheduler=RecognitionScheduler(max_age_seconds=10.0),
        matcher=matcher, recognize=recognize,
    )
    camera.start()
    try:
        def kinds():
            return [m["type"] for m in list(messages)]

        assert _wait(lambda: "track.identified" in kinds()), "tidak ada yang dikenali"
        first_uuid = [m for m in messages if m["type"] == "track.started"][0]["track_uuid"]

        camera.set_analysis_enabled(False)
        assert _wait(lambda: any(m["type"] == "track.ended" for m in list(messages)))
        assert _wait(lambda: camera.analysis_paused)
        frames_at_pause = camera.stats.frames
        assert _wait(lambda: camera.stats.frames > frames_at_pause + 20), "stream berhenti dibaca saat jeda"
        started_during_pause = [m for m in list(messages)
                                if m["type"] == "track.started" and m["track_uuid"] != first_uuid]
        assert not started_during_pause, "analisis berjalan padahal dijeda"

        camera.set_analysis_enabled(True)
        assert _wait(lambda: any(m["type"] == "track.started" and m["track_uuid"] != first_uuid
                                 for m in list(messages)))
        assert camera.alive and not camera.analysis_paused
    finally:
        camera.stop()

    ended = [m for m in messages if m["type"] == "track.ended" and m["track_uuid"] == first_uuid]
    assert [m["reason"] for m in ended] == ["schedule_off"]
    assert ended[0]["exit_zone"] != "door"
    intervals = [m for m in messages if m["type"] == "presence.interval"
                 and m.get("track_uuid") == first_uuid]
    assert intervals and intervals[0]["end_reason"] == "schedule_off"
    assert intervals[0]["end_source"] == "forced"
    assert intervals[0]["person_id"] == "4471"

    kinds = [m["type"] for m in messages]
    assert kinds.count("camera.online") == 1, "jadwal tidak boleh membuat camera.online baru"
    assert "camera.failed" not in kinds, "jadwal bukan kamera putus"

    validator = SchemaValidator()
    for message in messages:
        assert not validator.validate_message(message, expected_channel="events"), message
    report = ConformanceChecker().check(messages)
    assert report.ok, report.errors


def _runtime(mode: str) -> EngineRuntime:
    config = dataclasses.replace(load_config(), source_type="mock", auto_warmup=False,
                                 analysis_off_mode=mode)
    return EngineRuntime(config=config, options=RuntimeOptions(tcp=("127.0.0.1", 0)))


def test_rekonsiliasi_mode_pause_menjeda_kamera_yang_sama():
    runtime = _runtime("pause")
    try:
        runtime._reconcile({"r1": CameraSpec("r1", "mock", DOOR)})
        camera = runtime.cameras["r1"]
        runtime._reconcile({"r1": CameraSpec("r1", "mock", DOOR, enabled=False)})
        assert runtime.cameras["r1"] is camera
        assert _wait(lambda: camera.analysis_paused)
        runtime._reconcile({"r1": CameraSpec("r1", "mock", DOOR, enabled=True)})
        assert runtime.cameras["r1"] is camera
        assert _wait(lambda: not camera.analysis_paused)
        # Kamera yang dihapus dari daftar tetap ditutup seperti biasa.
        runtime._reconcile({})
        assert "r1" not in runtime.cameras
    finally:
        runtime.close()


def test_rekonsiliasi_mode_stop_tetap_perilaku_lama():
    runtime = _runtime("stop")
    try:
        runtime._reconcile({"r1": CameraSpec("r1", "mock", DOOR)})
        runtime._reconcile({"r1": CameraSpec("r1", "mock", DOOR, enabled=False)})
        assert "r1" not in runtime.cameras
    finally:
        runtime.close()
