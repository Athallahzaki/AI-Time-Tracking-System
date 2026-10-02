"""Lag analisis per kamera (04 §6, P17): pengukuran, histeresis, dan event.

Sebelum ini `camera.degraded` ada di skema tetapi engine asli tidak pernah
memancarkannya. Engine yang tertinggal puluhan detik dari kamera tampak sehat
di setiap pesan yang dikirimnya.
"""

from __future__ import annotations

import numpy as np
import pytest

from contracts.validator import SchemaValidator
from engine.api import events
from engine.runtime.lag import LagMonitor, lag_between


def feed(monitor, samples):
    """samples: [(t, lag)] -> daftar transisi yang terjadi."""
    out = []
    for t, lag in samples:
        change = monitor.observe(t, lag)
        if change is not None:
            out.append(change)
    return out


def test_lag_kecil_tidak_pernah_memicu():
    monitor = LagMonitor()
    assert feed(monitor, [(t * 0.1, 0.3) for t in range(600)]) == []
    assert monitor.degraded is False


def test_lonjakan_singkat_tidak_memicu():
    """Satu jeda GPU 2 detik bukan alasan menandai kamera."""
    monitor = LagMonitor(hold_seconds=5.0)
    samples = [(t * 0.1, 0.2) for t in range(50)]
    samples += [(5.0 + t * 0.1, 2.5) for t in range(20)]        # 2 dtk di atas ambang
    samples += [(7.0 + t * 0.1, 0.2) for t in range(50)]
    assert feed(monitor, samples) == []


def test_lag_bertahan_membuka_lalu_menutup_rentang():
    monitor = LagMonitor(enter_seconds=1.0, exit_seconds=0.5, hold_seconds=5.0)
    samples = [(t * 0.1, 0.2) for t in range(100)]               # 0-10 dtk sehat
    samples += [(10.0 + t * 0.1, 3.0) for t in range(100)]       # 10-20 dtk tertinggal
    samples += [(20.0 + t * 0.1, 0.8) for t in range(100)]       # di antara ambang: tetap degraded
    samples += [(30.0 + t * 0.1, 0.1) for t in range(100)]       # 30-40 dtk pulih
    changes = feed(monitor, samples)
    assert [c.kind for c in changes] == ["entered", "exited"]
    entered, exited = changes
    assert entered.since_wallclock == pytest.approx(10.0), "rentang dimulai saat lag pertama melewati ambang"
    assert entered.at_wallclock == pytest.approx(15.0, abs=0.11)
    assert exited.since_wallclock == pytest.approx(10.0)
    assert exited.at_wallclock == pytest.approx(35.0, abs=0.11)


def test_fps_efektif_dan_reset_saat_reconnect():
    monitor = LagMonitor()
    feed(monitor, [(t / 12.0, 0.1) for t in range(120)])
    assert monitor.effective_fps == pytest.approx(12.0, rel=0.02)
    monitor.reset()
    assert monitor.effective_fps is None and monitor.lag_seconds is None and not monitor.degraded


def test_lag_tidak_dihitung_lintas_epoch():
    assert lag_between((3, 10.0), 3, 7.5) == pytest.approx(2.5)
    assert lag_between((4, 0.2), 3, 7.5) is None, "pts dua timeline tidak sebanding"
    assert lag_between(None, 3, 7.5) is None


def test_histeresis_tidak_boleh_terbalik():
    with pytest.raises(ValueError, match="histeresis"):
        LagMonitor(enter_seconds=0.5, exit_seconds=1.0)


def test_event_lag_lolos_skema():
    validator = SchemaValidator()
    degraded = events.camera_degraded("cam01", 1759370000.0, reason="analisis tertinggal 3.0 dtk",
                                      fps=7.5, kind="lag", since_wallclock=1759369990.0, lag_seconds=3.0)
    recovered = events.camera_recovered("cam01", 1759370030.0, kind="lag",
                                        since_wallclock=1759369990.0, until_wallclock=1759370030.0)
    for message in (degraded, recovered):
        stamped = dict(message, seq=1)
        assert validator.validate_message(stamped, expected_channel="events") == [], message


def test_supervisor_memancarkan_degraded_dan_recovered(monkeypatch):
    """Ujung ke ujung di dalam supervisor: sumber yang decode-nya jauh di depan
    analisis menghasilkan camera.degraded, dan camera.recovered saat mengejar."""
    from engine.config import load_config
    from engine.ports.frame import Frame, FrameMetadata
    from engine.runtime import camera as camera_module
    from engine.runtime.camera import CameraSpec, CameraSupervisor

    emitted = []
    supervisor = CameraSupervisor(
        CameraSpec("cam01", "rtsp://127.0.0.1:8554/cam01"),
        load_config("engine/config/default_config.yaml"),
        emit_event=emitted.append, emit_view=lambda m: True,
    )

    class FakeSource:
        latest_decoded = None
        frames_replaced = 0

    source = FakeSource()
    supervisor._source = source
    clock = {"now": 1759370000.0}
    monkeypatch.setattr(camera_module.time, "time", lambda: clock["now"])

    image = np.zeros((4, 4, 3), dtype=np.uint8)
    pts = 0.0
    for step in range(400):                       # 40 dtk pada 10 fps analisis
        clock["now"] += 0.1
        pts += 0.1
        behind = 3.0 if 50 <= step < 200 else 0.1  # tertinggal 3 dtk di tengah
        source.latest_decoded = (0, pts + behind)
        source.frames_replaced += 2 if behind > 1 else 0
        frame = Frame(image=image, metadata=FrameMetadata(frame_id=step, pts=pts, stream_epoch=0))
        supervisor._observe_lag(frame, pts)

    kinds = [(m["type"], m.get("kind")) for m in emitted]
    assert kinds == [("camera.degraded", "lag"), ("camera.recovered", "lag")], kinds
    assert emitted[0]["lag_seconds"] == pytest.approx(3.0, abs=0.01)
    assert supervisor.lag_degraded is False
    metrics = supervisor.metrics()
    assert metrics["lag_seconds"] == pytest.approx(0.1, abs=0.01)
    assert metrics["effective_fps"] == pytest.approx(10.0, rel=0.05)
    assert metrics["frames_dropped_stale"] == 300


def test_health_membawa_camera_metrics():
    from engine.config import load_config
    from engine.runtime.service import EngineRuntime, RuntimeOptions

    runtime = EngineRuntime(config=load_config("engine/config/default_config.yaml"),
                            options=RuntimeOptions(tcp=None))

    class FakeCamera:
        class spec:
            camera_id = "cam01"
        alive = True
        state = "online"
        lag_degraded = True

        def metrics(self):
            return {"lag_seconds": 0.4, "effective_fps": 11.8, "frames_dropped_stale": 3}

        def health(self):
            return {"degraded_components": []}

        stats = type("S", (), {"state": "online"})()

    try:
        runtime._cameras["cam01"] = FakeCamera()
        import time as _time
        runtime._emit_health(_time.time())
        health = runtime.api._outbox.since(0, 10)[-1]
        assert health["camera_metrics"] == {"cam01": {"lag_seconds": 0.4, "effective_fps": 11.8,
                                                      "frames_dropped_stale": 3}}
        assert health["cameras"] == {"cam01": "degraded"}, "kamera yang tertinggal tidak boleh dilaporkan online"
        assert SchemaValidator().validate_message(health, expected_channel="events") == []
    finally:
        runtime._cameras.clear()
        runtime.close()
