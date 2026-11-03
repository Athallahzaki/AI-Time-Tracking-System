"""Gerbang analisis berbasis perubahan kotak (keputusan tim 3 Nov).

Yang dikunci: analisis dipicu oleh PERUBAHAN, bukan interval; jitter/drift dan hilang
sebentar tidak memicu; overlap cepat yang bisa menukar ID memicu rekalkulasi.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from engine.config.schema import AnalysisTriggerConfig
from engine.pipeline.change_gate import ChangeGate
from engine.ports.geometry import BoundingBox
from engine.ports.tracking import TrackState


def _t(tid, x, y=100.0, w=100.0, h=300.0, state=TrackState.TRACKED):
    return SimpleNamespace(track_id=tid, bbox=BoundingBox(x1=x, y1=y, x2=x + w, y2=y + h), state=state)


def _gate(**kw):
    return ChangeGate(AnalysisTriggerConfig(enabled=True, max_interval_seconds=None, **kw))


def _run(gate, frames, start=0, dt=0.1):
    """frames: list of track lists; frame_id dan pts naik otomatis."""
    for i, tracks in enumerate(frames):
        gate.observe(start + i, tracks, (start + i) * dt)


def _drain(gate, tid, kind="face", pts=0.0):
    n = 0
    while gate.due(tid, kind):
        gate.mark(tid, kind, pts)
        n += 1
    return n


def test_track_baru_dapat_kredit_burst_lalu_diam_tidak_dianalisis_lagi():
    gate = _gate()
    _run(gate, [[_t(1, 100)]])
    assert _drain(gate, 1, "face") == 3, "wajah butuh beberapa bukti untuk konfirmasi"
    assert _drain(gate, 1, "reid") == 1
    _run(gate, [[_t(1, 100)] for _ in range(50)], start=1)
    assert not gate.due(1, "face") and not gate.due(1, "reid"), "diam = tidak ada analisis"


def test_jitter_dan_drift_satu_frame_tidak_memicu():
    gate = _gate()
    _run(gate, [[_t(1, 100)]]); _drain(gate, 1); _drain(gate, 1, "reid")
    rng = np.random.default_rng(0)
    frames = [[_t(1, 100 + rng.normal(0, 6), 100 + rng.normal(0, 6))] for _ in range(60)]
    frames[30] = [_t(1, 400)]  # satu frame melompat (drift tracker)
    _run(gate, frames, start=1)
    assert not gate.due(1, "face") and not gate.due(1, "reid")


def test_perpindahan_yang_bertahan_memicu_wajah_dan_reid():
    gate = _gate()
    _run(gate, [[_t(1, 100)]]); _drain(gate, 1); _drain(gate, 1, "reid")
    _run(gate, [[_t(1, 400)] for _ in range(6)], start=1)   # geser 1x tinggi badan
    assert _drain(gate, 1, "face") == 3 and _drain(gate, 1, "reid") == 1
    assert gate.metrics()["trigger_face_change"] == 1


def test_mendekat_ke_kamera_skala_berubah_memicu():
    gate = _gate()
    _run(gate, [[_t(1, 100)]]); _drain(gate, 1); _drain(gate, 1, "reid")
    _run(gate, [[_t(1, 100, w=150, h=450)] for _ in range(6)], start=1)
    assert gate.due(1, "face")


def test_hilang_sebentar_diabaikan_hilang_lama_cek_ulang():
    gate = _gate(lost_recheck_seconds=1.0)
    _run(gate, [[_t(1, 100)]]); _drain(gate, 1); _drain(gate, 1, "reid")
    _run(gate, [[_t(1, 100, state=TrackState.LOST)] for _ in range(3)] + [[_t(1, 105)]], start=1)
    assert not gate.due(1, "face"), "0,3 dtk hilang: anomali tracker, bukan orang baru"
    _run(gate, [[_t(1, 100, state=TrackState.LOST)] for _ in range(15)] + [[_t(1, 105)]], start=10)
    assert gate.due(1, "face") and gate.metrics()["trigger_face_lost"] == 1


def test_overlap_cepat_memicu_rekalkulasi_kedua_track():
    gate = _gate(fast_overlap_seconds=3.0, overlap_recheck=3)
    _run(gate, [[_t(1, 100), _t(2, 600)]])
    for tid in (1, 2):
        _drain(gate, tid); _drain(gate, tid, "reid")
    crossing = [[_t(1, 100 + 50 * i), _t(2, 600 - 50 * i)] for i in range(1, 10)]  # berpapasan
    apart = [[_t(1, 800), _t(2, -100)] for _ in range(2)]
    _run(gate, crossing + apart, start=1)
    for tid in (1, 2):
        assert _drain(gate, tid, "face") == 3, tid
    assert gate.metrics()["trigger_face_overlap"] == 2


def test_berdiri_berdampingan_lama_tidak_dianggap_risiko_tukar_id():
    gate = _gate(fast_overlap_seconds=3.0)
    _run(gate, [[_t(1, 100), _t(2, 150)]])
    for tid in (1, 2):
        _drain(gate, tid); _drain(gate, tid, "reid")
    _run(gate, [[_t(1, 100), _t(2, 150)] for _ in range(60)], start=1)   # 6 dtk bertumpuk
    _run(gate, [[_t(1, 100), _t(2, 700)]], start=61)
    assert gate.metrics().get("trigger_face_overlap", 0) == 0


def test_interval_pengaman_dan_track_tak_dikenal_gagal_terbuka():
    gate = ChangeGate(AnalysisTriggerConfig(enabled=True, max_interval_seconds=5.0))
    _run(gate, [[_t(1, 100)]]); _drain(gate, 1, pts=0.0)
    _run(gate, [[_t(1, 100)] for _ in range(40)], start=1)    # 4 dtk
    assert not gate.due(1, "face")
    _run(gate, [[_t(1, 100)] for _ in range(20)], start=41)   # lewat 5 dtk
    assert gate.due(1, "face")
    assert gate.due(999, "face"), "track yang belum dilihat gerbang tidak boleh terblokir"


def test_observe_idempoten_per_frame_dan_params_bisa_diganti_saat_jalan():
    gate = _gate()
    _run(gate, [[_t(1, 100)]]); _drain(gate, 1)
    for _ in range(5):
        gate.observe(7, [_t(1, 400)], 0.7)                      # frame sama dipanggil 2 komponen
    assert not gate.due(1, "face"), "satu frame dihitung sekali"
    gate.params = AnalysisTriggerConfig(enabled=True, sustain_frames=1, max_interval_seconds=None)
    gate.observe(8, [_t(1, 400)], 0.8)
    assert gate.due(1, "face")


def test_config_divalidasi():
    with pytest.raises(ValueError):
        AnalysisTriggerConfig(swap_iou=0.05, overlap_iou=0.1)
    with pytest.raises(ValueError):
        AnalysisTriggerConfig(sustain_frames=0)
    assert AnalysisTriggerConfig().enabled is False


# --------------------------------------------------------------------------
# Terpasang di antrean rekognisi sungguhan
# --------------------------------------------------------------------------

def _queue(gate):
    from engine.identity import RecognitionScheduler
    from engine.pipeline.zoning import TrackZoner, ZonePriorityQueue

    handed = []
    scheduler = RecognitionScheduler(max_age_seconds=100.0, retry_interval_seconds=0.0)
    queue = ZonePriorityQueue(scheduler=scheduler, zoner=TrackZoner(), max_requests_per_frame=4,
                              change_gate=gate)
    queue.set_consumer(lambda request: (handed.append(request.track_uuid),
                                        scheduler.complete(request.track_uuid, produced_evidence=False)))
    return queue, handed


def _step(queue, i, x, identity=None):
    from engine.ports.frame import Frame, FrameMetadata
    from engine.ports.tracking import Track

    track = Track(track_id=1, bbox=BoundingBox(x1=x, y1=100.0, x2=x + 100.0, y2=400.0),
                  state=TrackState.TRACKED)
    track.attributes["track_uuid"] = "tr_x_1"
    if identity is not None:
        track.attributes["identity_state"] = identity
    frame = Frame(image=np.zeros((10, 10, 3), dtype=np.uint8),
                  metadata=FrameMetadata(frame_id=i, pts=i * 0.1, source_id="cam01", width=1920, height=1080))
    queue.step(frame, [track])


def test_orang_tak_dikenal_yang_diam_tidak_dicoba_terus():
    gate = _gate()
    queue, handed = _queue(gate)
    for i in range(100):                                       # 10 dtk berdiri diam membelakangi kamera
        _step(queue, i, 100.0)
    assert len(handed) == 3, "hanya kredit track baru; tanpa gerbang, scheduler mencoba tiap frame"
    assert gate.metrics()["trigger_skipped_face"] > 0
    for i in range(100, 106):                                  # berbalik/berjalan
        _step(queue, i, 450.0)
    assert len(handed) == 6


def test_identitas_terkonfirmasi_diverifikasi_ulang_saat_kotak_berubah_bukan_tunggu_60_dtk():
    from engine.identity.ports import IdentityState, TrackIdentity

    gate = _gate()
    queue, handed = _queue(gate)
    confirmed = TrackIdentity(track_uuid="tr_x_1", camera_id="cam01", state=IdentityState.CONFIRMED,
                              person_id="4471", last_face_pts=0.0)
    for i in range(30):
        _step(queue, i, 100.0, confirmed)
    assert len(handed) == 3, "kredit track baru (dipakai saat pengenalan pertama), lalu diam = tidak ada pekerjaan"
    for i in range(30, 36):
        _step(queue, i, 450.0, confirmed)                     # bergeser: bisa jadi tracker menukar orang
    assert len(handed) == 6


def test_tanpa_gerbang_perilaku_lama():
    queue, handed = _queue(None)
    for i in range(20):
        _step(queue, i, 100.0)
    assert len(handed) == 20
