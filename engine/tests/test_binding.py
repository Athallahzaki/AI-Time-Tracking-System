"""Tes penyambung pipeline → identitas → interval → gerbang keluar.

Inilah pertama kalinya seluruh jalur Engine A dijalankan sebagai satu benda:
`Track` dan `Frame` sungguhan dari `ports/`, penjadwal dan wasit identitas
sungguhan, perakit interval sungguhan, dan pesan yang keluar divalidasi oleh
validator kontrak yang sama dengan `fake_engine`.

Yang paling penting di berkas ini adalah tes daur ulang `track_id`. Tanpa
generasi di dalam uuid, hasil pengenalan yang datang terlambat untuk orang yang
sudah pergi menempel ke orang yang baru masuk — tanpa error, dan yang tercatat
hadir adalah orang yang salah.
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
import pytest

from contracts.validator import ConformanceChecker, SchemaValidator
from engine.identity import (
    Evidence,
    IdentityArbiter,
    InMemoryReferenceStore,
    MatrixMatcher,
    RecognitionScheduler,
)
from engine.pipeline.zoning import TrackZoner, ZonePriorityQueue
from engine.ports.frame import Frame, FrameMetadata
from engine.ports.geometry import BoundingBox
from engine.ports.tracking import Track, TrackState
from engine.presence import EngineBinding, PresenceAssembler, ZoneLabeller

DIM = 64
OFFSET = 1758240000.0
WIDTH, HEIGHT = 1000, 1000
DOOR = {"r1": [0.62, 0.10, 0.95, 0.55], "r2": [0.05, 0.10, 0.35, 0.55]}

PINTU = (700, 200, 850, 500)
TENGAH = (400, 300, 550, 800)


def unit(seed: int) -> np.ndarray:
    vector = np.random.default_rng(seed).normal(size=DIM).astype(np.float32)
    return vector / np.linalg.norm(vector)


def blend(a, b, t):
    mixed = (1.0 - t) * a + t * b
    return (mixed / np.linalg.norm(mixed)).astype(np.float32)


ALICE, BOB = unit(1), unit(2)


def jitter(vector, index: int, amount: float = 0.22):
    return blend(vector, unit(900 + index), amount)


def frame(pts: float, camera="r1", epoch=0, frame_id=0) -> Frame:
    return Frame(
        image=np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8),
        metadata=FrameMetadata(
            frame_id=frame_id, timestamp=OFFSET + pts, source_id=camera,
            fps=10.0, width=WIDTH, height=HEIGHT, pts=pts,
            pts_source="container", stream_epoch=epoch, wallclock=OFFSET + pts,
        ),
    )


def track(track_id: int, box=PINTU, state=TrackState.TRACKED) -> Track:
    x1, y1, x2, y2 = box
    return Track(track_id=track_id, bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2), state=state)


def build(recognize=None, stitch_window=5.0):
    keluaran: List[dict] = []
    store = InMemoryReferenceStore({"4471": [ALICE], "4802": [BOB]})
    matcher = MatrixMatcher(store, threshold=0.37, margin=0.06)
    arbiter = IdentityArbiter(matcher, min_evidence=3, min_spread_seconds=0.5)
    assembler = PresenceAssembler(
        emit=keluaran.append, zones=ZoneLabeller(DOOR),
        stitch_window_seconds=stitch_window,
    )
    scheduler = RecognitionScheduler(max_age_seconds=100.0)
    binding = EngineBinding(arbiter, assembler, scheduler, recognize=recognize)
    assembler.camera_online("r1", OFFSET, fps=10.0)
    return binding, assembler, arbiter, scheduler, keluaran


def jenis(keluaran, message_type):
    return [m for m in keluaran if m["type"] == message_type]


def kenali(vector):
    """Pengenal palsu yang selalu mengembalikan orang yang sama, dengan derau."""
    counter = {"n": 0}

    def recognize(track_obj, frame_obj) -> Optional[Evidence]:
        counter["n"] += 1
        return Evidence(jitter(vector, counter["n"]), frame_obj.metadata.pts, 0.9, "test-v1")

    return recognize


# --------------------------------------------------------------------------
# daur ulang track_id
# --------------------------------------------------------------------------


def test_track_id_yang_didaur_ulang_mendapat_uuid_berbeda():
    """`pipeline/zoning.py` memakai `camera-t{track_id}` sebagai penahan
    sementara. Kalau itu jadi kunci identitas, embedding orang yang sudah
    pergi menempel ke orang yang baru masuk."""
    binding, _, _, _, _ = build()

    pertama = binding.uuid_for("r1", 7)
    binding.on_tracks_updated([track(7)], frame(1.0))
    binding.on_track_removed(track(7))
    kedua = binding.uuid_for("r1", 7)

    assert pertama != kedua
    assert pertama.endswith("g1") and kedua.endswith("g2")


def test_track_id_sama_di_dua_kamera_bukan_track_yang_sama():
    binding, _, _, _, _ = build()
    assert binding.uuid_for("r1", 3) != binding.uuid_for("r2", 3)


# --------------------------------------------------------------------------
# jalur penuh
# --------------------------------------------------------------------------


def test_masuk_dikenali_keluar_menghasilkan_satu_interval():
    binding, _, _, scheduler, keluaran = build(recognize=kenali(ALICE))

    for index, pts in enumerate((1.0, 1.5, 2.1)):
        current = frame(pts, frame_id=index)
        binding.on_tracks_updated([track(1)], current)
        binding(_request(binding, "r1", 1, pts))

    keluar = track(1, PINTU)
    keluar.attributes["zone"] = "door"
    keluar.attributes["track_uuid"] = binding.uuid_for("r1", 1)
    binding.on_track_removed(keluar)

    intervals = jenis(keluaran, "presence.interval")
    assert len(intervals) == 1
    assert intervals[0]["person_id"] == "4471"
    assert intervals[0]["start_pts"] == 1.0, "dimundurkan ke kelahiran track"
    assert intervals[0]["end_reason"] == "left_frame"
    assert binding.metrics.identified == 1


def test_track_tanpa_pengenal_tidak_menghasilkan_interval_tapi_bersuara():
    """Sistem yang berjalan mulus dan mencatat nol kehadiran adalah mode
    kegagalan terburuk: log bersih, dashboard hidup, tidak ada yang salah
    kelihatannya."""
    binding, _, _, _, keluaran = build(recognize=None)

    binding.on_tracks_updated([track(1)], frame(1.0))
    binding(_request(binding, "r1", 1, 1.0))
    keluar = track(1)
    keluar.attributes["track_uuid"] = binding.uuid_for("r1", 1)
    binding.on_track_removed(keluar)

    assert jenis(keluaran, "presence.interval") == []
    health = binding.health()
    assert health["models_loaded"] is False
    assert "recognizer_not_wired" in health["degraded_components"]


def test_identitas_ditulis_balik_ke_atribut_track():
    """`ZonePriorityQueue` membaca `identity_state` untuk menentukan prioritas.
    Selama ia selalu None, setiap track terlihat PENDING selamanya."""
    binding, _, _, _, _ = build(recognize=kenali(ALICE))
    hidup = track(1)

    for index, pts in enumerate((1.0, 1.5, 2.1)):
        binding.on_tracks_updated([hidup], frame(pts, frame_id=index))
        binding(_request(binding, "r1", 1, pts))

    assert hidup.attributes["identity"] == "4471"
    assert hidup.attributes["identity_source"] == "face"
    assert hidup.attributes["identity_state"].state.value == "CONFIRMED"


def test_zona_berakhir_menentukan_alasan_berakhir():
    """Satu field, dan backend bisa membedakan celah nyata dari celah palsu
    tanpa tahu apa pun tentang tracking."""
    binding, _, _, _, keluaran = build(recognize=kenali(ALICE))

    for index, pts in enumerate((1.0, 1.5, 2.1)):
        binding.on_tracks_updated([track(1, TENGAH)], frame(pts, frame_id=index))
        binding(_request(binding, "r1", 1, pts))

    keluar = track(1, TENGAH)
    keluar.attributes["zone"] = "interior"
    keluar.attributes["track_uuid"] = binding.uuid_for("r1", 1)
    binding.on_track_removed(keluar)

    interval = jenis(keluaran, "presence.interval")[0]
    assert interval["end_zone"] == "interior"
    assert interval["end_reason"] == "occluded_timeout", "bukan kepergian nyata"


def test_track_hilang_sementara_tidak_melepas_identitas():
    """Membuang state identitas saat track LOST berarti setiap oklusi tiga
    detik menghasilkan celah."""
    binding, _, arbiter, _, _ = build(recognize=kenali(ALICE))
    hidup = track(1)

    for index, pts in enumerate((1.0, 1.5, 2.1)):
        binding.on_tracks_updated([hidup], frame(pts, frame_id=index))
        binding(_request(binding, "r1", 1, pts))

    uuid = binding.uuid_for("r1", 1)
    binding.on_track_lost(hidup)

    assert arbiter.identity_of(uuid).person_id == "4471"


# --------------------------------------------------------------------------
# integrasi dengan milik Engine B
# --------------------------------------------------------------------------


def test_antrian_prioritas_milik_b_bisa_memanggil_penyambung_ini():
    """`ZonePriorityQueue.set_consumer` adalah seam yang B siapkan. Kalau tes
    ini gagal, dua jalur punya kontrak yang tidak cocok."""
    binding, _, _, scheduler, keluaran = build(recognize=kenali(ALICE))
    zoner = TrackZoner(ZoneLabeller(DOOR))
    queue = ZonePriorityQueue(scheduler, zoner, max_requests_per_frame=2)
    queue.set_consumer(binding)

    hidup = track(1)
    for index, pts in enumerate((1.0, 1.5, 2.1, 2.8)):
        current = frame(pts, frame_id=index)
        zoner.label(current, [hidup])
        binding.on_tracks_updated([hidup], current)
        queue.step(current, [hidup])

    assert binding.metrics.recognitions_attempted > 0
    assert hidup.attributes["zone"] == "door"


def test_zoner_milik_b_dan_labeller_milik_a_sepakat():
    """Keduanya memakai `presence/zones.py` yang sama — kalau tidak, ada dua
    definisi pintu yang akan berbeda pendapat suatu hari."""
    labeller = ZoneLabeller(DOOR)
    zoner = TrackZoner(labeller)
    hidup = track(1, TENGAH)
    zoner.label(frame(1.0), [hidup])

    assert hidup.attributes["zone"] == labeller.label("r1", (0.4, 0.3, 0.55, 0.8))


# --------------------------------------------------------------------------
# kesesuaian kontrak
# --------------------------------------------------------------------------


def test_seluruh_aliran_lolos_skema_dan_aturan_aliran():
    binding, assembler, _, _, keluaran = build(recognize=kenali(ALICE))

    for index, pts in enumerate((1.0, 1.5, 2.1)):
        binding.on_tracks_updated([track(1)], frame(pts, frame_id=index))
        binding(_request(binding, "r1", 1, pts))

    keluar = track(1)
    keluar.attributes["zone"] = "door"
    keluar.attributes["track_uuid"] = binding.uuid_for("r1", 1)
    binding.on_track_removed(keluar)
    assembler.camera_failed("r1", OFFSET + 10.0, pts=10.0)

    validator = SchemaValidator()
    for index, message in enumerate(keluaran, start=1):
        message["seq"] = index
        issues = validator.validate_message(message, line=index, expected_channel="events")
        assert issues == [], f"{message['type']}: {[str(i) for i in issues]}"

    report = ConformanceChecker().check(
        [dict(m, _line=i) for i, m in enumerate(keluaran, start=1)]
    )
    assert report.errors == [], "\n".join(str(e) for e in report.errors)


# --------------------------------------------------------------------------


class _Request:
    def __init__(self, track_uuid, camera_id, pts):
        self.track_uuid = track_uuid
        self.camera_id = camera_id
        self.requested_pts = pts


def _request(binding, camera, track_id, pts):
    return _Request(binding.uuid_for(camera, track_id), camera, pts)
