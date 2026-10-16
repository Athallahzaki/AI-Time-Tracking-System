"""Satu scheduler rekognisi, lima kamera (paket ea-r12).

Sebelum ea-r12 loop kamera B bisa mengambil permintaan milik kamera A dari
scheduler bersama. Binding B tidak mengenal track A, jadi giliran itu dilepas
tanpa bukti, padahal `attempts` track A sudah naik: track A masuk backoff tanpa
pernah dicoba. Umur permintaan juga diukur dengan PTS, padahal PTS direbase ke
0 per kamera per epoch, jadi kamera yang baru reconnect membuang permintaan
kamera lain sebagai "basi".

Tes di sini memakai kelas asli (RecognitionScheduler, ZonePriorityQueue,
TrackZoner, EngineBinding, PresenceAssembler), dirakit seperti runtime/camera.py.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np

from engine.identity import IdentityArbiter, InMemoryReferenceStore, MatrixMatcher, Priority, RecognitionScheduler
from engine.pipeline.zoning import TrackZoner, ZonePriorityQueue
from engine.ports.frame import Frame, FrameMetadata
from engine.ports.geometry import BoundingBox
from engine.ports.tracking import Track, TrackState
from engine.presence.assembler import PresenceAssembler
from engine.presence.binding import EngineBinding

KAMERA = ["c1", "c2", "c3", "c4", "c5"]


class JamPalsu:
    def __init__(self, mulai: float = 100.0) -> None:
        self.t = mulai

    def __call__(self) -> float:
        return self.t


class PencatatWorker:
    """Pengganti RecognitionWorker: mencatat siapa yang benar-benar dikirim ke model."""

    def __init__(self) -> None:
        self.dikirim = []          # (kamera, uuid)
        self._tugas = []

    def submit(self, uuid, camera_id, track, frame, done) -> bool:
        self.dikirim.append((camera_id, uuid))
        self._tugas.append((uuid, done))
        return True

    def selesaikan_semua(self) -> None:
        for uuid, done in self._tugas:
            done(uuid, None)       # tidak ada wajah: giliran selesai tanpa bukti
        self._tugas.clear()


def _matcher() -> MatrixMatcher:
    vector = np.ones(512, dtype=np.float32) / np.sqrt(512)
    store = InMemoryReferenceStore({"emp_1": [vector]}, embedding_version="v")
    matcher = MatrixMatcher(store)
    matcher.rebuild()
    return matcher


def _frame(kamera: str, pts: float) -> Frame:
    return Frame(image=np.zeros((1000, 1000, 3), dtype=np.uint8),
                 metadata=FrameMetadata(frame_id=int(pts * 100), pts=pts, source_id=kamera,
                                        width=1000, height=1000))


def _track(track_id: int) -> Track:
    x = 100.0 + 150.0 * track_id
    track = Track(track_id=track_id, bbox=BoundingBox(x, 300.0, x + 100.0, 600.0))
    track.state = TrackState.TRACKED
    return track


class _Kamera:
    """Satu kamera dirakit seperti CameraSupervisor: binding + antrean sendiri,
    scheduler bersama."""

    def __init__(self, nama: str, scheduler, worker: PencatatWorker, matcher) -> None:
        self.nama = nama
        assembler = PresenceAssembler(emit=lambda event: None)
        assembler.camera_online(nama, wallclock_now=1759370000.0, fps=6.0)
        self.binding = EngineBinding(arbiter=IdentityArbiter(matcher=matcher), assembler=assembler,
                                     scheduler=scheduler, recognize=lambda t, f: None,
                                     uuid_prefix=f"tr_{nama}", executor=worker)
        self.zoner = TrackZoner()
        self.queue = ZonePriorityQueue(scheduler=scheduler, zoner=self.zoner, max_requests_per_frame=2)
        self.queue.set_consumer(self.binding)
        self.tracks = [_track(i) for i in range(1, 5)]

    def step(self, pts: float) -> None:
        frame = _frame(self.nama, pts)
        self.binding.on_tracks_updated(self.tracks, frame)
        self.zoner.label(frame, self.tracks)
        self.queue.step(frame, self.tracks)

    def uuid_milik_sendiri(self) -> set:
        return {t.attributes.get("track_uuid") for t in self.tracks}


def _simulasi(pts_awal, detik=30.0, fps=6.0):
    jam = JamPalsu()
    scheduler = RecognitionScheduler(clock=jam)
    worker = PencatatWorker()
    matcher = _matcher()
    kamera = [_Kamera(nama, scheduler, worker, matcher) for nama in KAMERA]
    for langkah in range(int(detik * fps)):
        for k in kamera:
            k.step(pts_awal[k.nama] + langkah / fps)
        worker.selesaikan_semua()
        jam.t += 1.0 / fps
    return kamera, worker, scheduler


def test_setiap_kamera_hanya_menerima_giliran_track_miliknya():
    """Kasus terbaik untuk kode lama (PTS kelima kamera identik): dulu c1 mendapat
    nol percobaan nyata dalam 30 detik."""
    kamera, worker, _ = _simulasi({nama: 0.0 for nama in KAMERA})

    for k in kamera:
        dikirim = [uuid for cam, uuid in worker.dikirim if cam == k.nama]
        assert dikirim, f"{k.nama} tidak pernah dicoba"
        assert set(dikirim) <= k.uuid_milik_sendiri()
        assert k.binding.metrics.requests_unknown_track == 0, f"{k.nama} menerima giliran kamera lain"


def test_semua_track_semua_kamera_kebagian_percobaan():
    kamera, worker, _ = _simulasi({nama: 0.0 for nama in KAMERA})
    dicoba = {uuid for _, uuid in worker.dikirim}
    for k in kamera:
        assert k.uuid_milik_sendiri() <= dicoba, f"ada track {k.nama} yang tidak pernah dicoba"


def test_pts_beda_titik_nol_tidak_membuat_basi_palsu():
    """c1 baru reconnect (PTS mulai 0), kamera lain sudah jalan 5000 dtk."""
    pts_awal = {nama: 5000.0 for nama in KAMERA}
    pts_awal["c1"] = 0.0
    kamera, worker, scheduler = _simulasi(pts_awal, detik=10.0)

    assert scheduler.dropped_stale == 0
    for k in kamera:
        assert any(cam == k.nama for cam, _ in worker.dikirim), f"{k.nama} tidak pernah dicoba"
        assert k.binding.metrics.requests_unknown_track == 0


# --------------------------------------------------------------------------
# RecognitionScheduler langsung
# --------------------------------------------------------------------------


def test_pop_per_kamera_tidak_mengambil_milik_kamera_lain_dan_tidak_menaikkan_attempts():
    scheduler = RecognitionScheduler(clock=JamPalsu())
    scheduler.submit("tr_a", "cA", Priority.DOOR_NEW, 10.0)
    scheduler.submit("tr_b", "cB", Priority.UNIDENTIFIED, 10.0)

    request = scheduler.pop(10.1, camera_id="cB")
    assert request.track_uuid == "tr_b"
    assert scheduler.depth == 1, "permintaan cA tetap di antrean"
    assert "tr_a" not in scheduler._attempts, "track cA tidak boleh dihitung dicoba"

    assert scheduler.pop(10.1, camera_id="cB") is None
    assert scheduler.pop(10.1, camera_id="cA").track_uuid == "tr_a"


def test_umur_diukur_dengan_jam_bersama_bukan_pts():
    jam = JamPalsu()
    scheduler = RecognitionScheduler(max_age_seconds=0.5, clock=jam)
    scheduler.submit("tr_a", "cA", Priority.UNIDENTIFIED, 5000.0)
    scheduler.submit("tr_b", "cB", Priority.UNIDENTIFIED, 0.2)

    # Kamera B memanggil dengan PTS-nya sendiri: tidak ada yang basi menurut jam.
    assert scheduler.pop(0.3, camera_id="cB").track_uuid == "tr_b"
    assert scheduler.dropped_stale == 0

    jam.t += 0.6
    assert scheduler.pop(5000.1, camera_id="cA") is None, "PTS bilang segar, jam bilang basi"
    assert scheduler.dropped_stale == 1


def test_tanpa_jam_kamera_lain_tidak_dinilai_dengan_pts_kamera_ini():
    scheduler = RecognitionScheduler(max_age_seconds=0.5)
    scheduler.submit("tr_a", "cA", Priority.UNIDENTIFIED, 0.0)
    assert scheduler.pop(5000.0, camera_id="cB") is None
    assert scheduler.dropped_stale == 0 and scheduler.depth == 1


def test_urutan_dalam_prioritas_sama_mengikuti_jam_bukan_pts():
    """Sesudah epoch baru PTS kembali ke 0; permintaan yang masuk lebih dulu tetap duluan."""
    jam = JamPalsu()
    scheduler = RecognitionScheduler(max_age_seconds=100.0, clock=jam)
    scheduler.submit("tr_lama", "cA", Priority.UNIDENTIFIED, 900.0)
    jam.t += 0.1
    scheduler.submit("tr_baru", "cA", Priority.UNIDENTIFIED, 0.1)
    assert scheduler.pop(0.2, camera_id="cA").track_uuid == "tr_lama"


def test_metrik_umur_tertua_memakai_jam():
    jam = JamPalsu()
    scheduler = RecognitionScheduler(max_age_seconds=100.0, clock=jam)
    scheduler.submit("tr_a", "cA", Priority.UNIDENTIFIED, 5000.0)
    jam.t += 0.25
    assert scheduler.metrics(0.0)["oldest_queued_age"] == 0.25


def test_tanpa_camera_id_perilaku_lama_tetap():
    scheduler = RecognitionScheduler(max_age_seconds=100.0)
    scheduler.submit("tr_a", "cA", Priority.UNIDENTIFIED, 0.0)
    scheduler.submit("tr_b", "cB", Priority.DOOR_NEW, 0.1)
    assert scheduler.pop(0.2).track_uuid == "tr_b"
    assert scheduler.pop(0.2).track_uuid == "tr_a"


# --------------------------------------------------------------------------
# metrik binding + peringatan di log health
# --------------------------------------------------------------------------


def test_binding_menghitung_giliran_untuk_track_asing():
    k = _Kamera("c1", RecognitionScheduler(), PencatatWorker(), _matcher())
    k.binding(SimpleNamespace(track_uuid="tr_c2-asing", camera_id="c2"))
    assert k.binding.metrics.requests_unknown_track == 1


def test_log_health_memperingatkan_giliran_track_asing():
    from engine.runtime.service import EngineRuntime

    class Rekam(logging.Handler):
        def __init__(self):
            super().__init__()
            self.pesan = []

        def emit(self, record):
            self.pesan.append((record.levelno, record.getMessage()))

    rekam = Rekam()
    log = logging.getLogger("engine.runtime")
    log.addHandler(rekam)
    try:
        palsu = SimpleNamespace(_unknown_track_requests=0)
        kamera = [SimpleNamespace(unknown_track_requests=lambda: 3),
                  SimpleNamespace(unknown_track_requests=lambda: 0)]
        assert EngineRuntime._report_unknown_track_requests(palsu, kamera) == 3
        assert EngineRuntime._report_unknown_track_requests(palsu, kamera) == 0
    finally:
        log.removeHandler(rekam)
    peringatan = [m for level, m in rekam.pesan if level == logging.WARNING]
    assert len(peringatan) == 1 and "3 giliran" in peringatan[0]
