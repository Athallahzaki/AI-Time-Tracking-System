"""P18: bias offset jam per kamera, diukur dan dikoreksi bertahap.

Skenario lapangan: offset ditetapkan saat stream dibuka (t=100), tetapi MediaMTX
mengirim mulai dari keyframe yang direkam 2 dtk sebelumnya (t=98) secara burst,
lalu frame berikutnya tiba real-time dengan latensi 50 ms. Tanpa koreksi, setiap
`at` mendahului kenyataan ±1,95 dtk selamanya.
"""

from __future__ import annotations

import pytest

from engine.ingest.timeline import StreamTimeline
from engine.runtime.clock import OffsetCorrector

OPEN = 100.0
CAPTURED_FIRST = 98.0        # keyframe pertama direkam 2 dtk sebelum stream dibuka
LATENCY = 0.05
FPS = 25.0


def _arrival(pts: float) -> float:
    if pts < 2.0:
        return OPEN + 0.02 * (pts / 2.0)          # burst: semua tiba sekaligus saat dibuka
    return CAPTURED_FIRST + pts + LATENCY         # real-time


def _feed(timeline, seconds, start_pts=0.0):
    pts = start_pts
    end = start_pts + seconds
    while pts < end:
        timeline.stamp(1000.0 + pts, arrival=_arrival(pts))
        pts += 1.0 / FPS
    return pts


def _timeline():
    timeline = StreamTimeline(source_id="cam01")
    timeline.begin_epoch(wall_now=OPEN)
    return timeline


def test_bias_terukur_setelah_burst_lewat():
    timeline = _timeline()
    _feed(timeline, 4.0)
    assert timeline.offset_bias is None, "jendela belum cukup panjang: jangan menebak"
    _feed(timeline, 4.0, start_pts=4.0)
    assert timeline.offset_bias == pytest.approx(-(OPEN - CAPTURED_FIRST) + LATENCY, abs=0.01)


def test_tanpa_waktu_tiba_tidak_ada_bias():
    """Tanpa thread pembaca, pyav_source tidak mengirim waktu tiba."""
    timeline = _timeline()
    pts = 0.0
    while pts < 10.0:
        timeline.stamp(1000.0 + pts)
        pts += 1.0 / FPS
    assert timeline.offset_bias is None


def test_slew_menggeser_bias_yang_tersimpan():
    timeline = _timeline()
    _feed(timeline, 8.0)
    before = timeline.offset_bias
    timeline.slew_offset(-1.0)
    assert timeline.offset_bias == pytest.approx(before + 1.0)
    assert timeline.wallclock_offset == pytest.approx(OPEN - 1.0)


def test_koreksi_bertahap_menuntaskan_bias_dan_at_tidak_pernah_mundur():
    timeline = _timeline()
    corrector = OffsetCorrector()
    pts = 0.0
    last_at = None
    for _ in range(int(40 * FPS)):                 # 40 dtk real-time
        arrival = _arrival(pts)
        stamp = timeline.stamp(1000.0 + pts, arrival=arrival)
        delta = corrector.observe(arrival, timeline.offset_bias)
        if delta:
            timeline.slew_offset(delta)
        at = timeline.wallclock_offset + pts
        if last_at is not None:
            assert at > last_at, "at wajib naik monoton selama koreksi"
        last_at = at
        pts += 1.0 / FPS
    assert corrector.corrected_total == pytest.approx(-(OPEN - CAPTURED_FIRST) + LATENCY, abs=0.06)
    assert abs(timeline.offset_bias) <= 0.06
    assert corrector.active is False


def test_bias_kecil_dibiarkan():
    corrector = OffsetCorrector()
    assert corrector.observe(0.0, -0.3) == 0.0
    assert corrector.observe(1.0, -0.3) == 0.0 and not corrector.active


def test_laju_koreksi_dibatasi():
    corrector = OffsetCorrector(max_rate=0.1)
    corrector.observe(0.0, -3.0)
    assert corrector.observe(1.0, -3.0) == pytest.approx(-0.1)


def test_bias_positif_adalah_delay_bukan_jam():
    """Uji 4060: thread pembaca tertinggal -> bias +0,5. Itu tidak boleh disapu."""
    corrector = OffsetCorrector()
    corrector.observe(0.0, 0.51)
    total = sum(corrector.observe(float(t), 0.51) for t in range(1, 11))
    assert 0 < total <= 0.02 + 1e-9, "10 dtk antrean hanya boleh tergeser <= 0,02 dtk"


def test_drift_kristal_positif_tetap_terkejar():
    """Kristal kamera 100 ppm lebih lambat: bias tumbuh 0,36 dtk/jam, dan terkejar."""
    corrector = OffsetCorrector(start=0.5, stop=0.05)
    bias, now = 0.0, 0.0
    for _ in range(3 * 3600):                       # 3 jam, satu observasi per detik
        now += 1.0
        bias += 100e-6
        bias -= corrector.observe(now, bias)
    assert bias < 0.6, "drift kristal tidak boleh menumpuk tanpa batas"


def test_bias_negatif_tetap_cepat():
    corrector = OffsetCorrector()
    corrector.observe(0.0, -2.0)
    assert corrector.observe(1.0, -2.0) == pytest.approx(-0.1)


@pytest.mark.parametrize("kwargs", [{"start": 0.1, "stop": 0.5}, {"max_rate": 1.0},
                                    {"max_rate_late": 0.5}, {"max_rate_late": -0.001}])
def test_parameter_berbahaya_ditolak(kwargs):
    with pytest.raises(ValueError):
        OffsetCorrector(**kwargs)


def test_supervisor_menggeser_jam_assembler(monkeypatch):
    """Ujung ke ujung di supervisor: `*_at` di event ikut terkoreksi."""
    import numpy as np
    from engine.config import load_config
    from engine.presence.assembler import PresenceAssembler
    from engine.runtime import camera as camera_module
    from engine.runtime.camera import CameraSpec, CameraSupervisor

    supervisor = CameraSupervisor(CameraSpec("cam01", "rtsp://127.0.0.1:8554/cam01"),
                                  load_config("engine/config/default_config.yaml"),
                                  emit_event=lambda m: m, emit_view=lambda m: True)
    supervisor._assembler = PresenceAssembler(emit=lambda m: None)
    supervisor._assembler.camera_online("cam01", wallclock_now=OPEN, fps=FPS)

    class Source:
        uses_reader_thread = True
        timeline = _timeline()

    supervisor._source = Source()
    clock = {"now": OPEN}
    monkeypatch.setattr(camera_module.time, "time", lambda: clock["now"])

    pts = 0.0
    for _ in range(int(40 * FPS)):
        clock["now"] = _arrival(pts)
        Source.timeline.stamp(1000.0 + pts, arrival=clock["now"])
        supervisor._correct_offset()
        pts += 1.0 / FPS

    corrected = supervisor._assembler.clock_for("cam01").offset
    assert corrected == pytest.approx(CAPTURED_FIRST + LATENCY, abs=0.06)
    assert corrected == pytest.approx(Source.timeline.wallclock_offset), "jam event dan timeline wajib sama"
    assert abs(supervisor.metrics()["clock_drift_seconds"]) <= 0.06


def test_tanpa_thread_pembaca_supervisor_tidak_mengoreksi(monkeypatch):
    from engine.config import load_config
    from engine.presence.assembler import PresenceAssembler
    from engine.runtime.camera import CameraSpec, CameraSupervisor

    supervisor = CameraSupervisor(CameraSpec("cam01", "rtsp://x/cam01"),
                                  load_config("engine/config/default_config.yaml"),
                                  emit_event=lambda m: m, emit_view=lambda m: True)
    supervisor._assembler = PresenceAssembler(emit=lambda m: None)
    supervisor._assembler.camera_online("cam01", wallclock_now=OPEN, fps=FPS)

    class Source:
        uses_reader_thread = False
        timeline = _timeline()

    _feed(Source.timeline, 10.0)        # bias terukur, tapi bukan dari thread pembaca
    supervisor._source = Source()
    for _ in range(100):
        supervisor._correct_offset()
    assert supervisor._assembler.clock_for("cam01").offset == OPEN
