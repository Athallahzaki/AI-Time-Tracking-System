"""Perakitan ReID ke engine (paket ea-r3), tanpa ONNX: embedder palsu.

Yang diuji: gerbang kualitas crop, blok config `reid`, embedding berbasis
kejadian (bukan tiap frame), worker (batch, basi, penuh, gagal), dan alur dua
kamera ANON → `identity.resolved` yang diperiksa skema + conformance kontrak.
"""

from __future__ import annotations

import dataclasses
import time
from types import SimpleNamespace
from typing import Any, Dict, List

import numpy as np
import pytest

from contracts.validator import ConformanceChecker, SchemaValidator
from engine.config import load_config
from engine.config.loader import ConfigBoundaryError
from engine.config.schema import ReidSettings
from engine.identity.reid import BodyObservation
from engine.identity.reid.quality import GOOD, LOW, REJECT, CropRules, assess_crop
from engine.pipeline.reid_coordinator import ReidCoordinator, build_reid_runtime
from engine.pipeline.reid_tap import ReidCameraTap
from engine.pipeline.reid_worker import ReidWorker
from engine.ports.geometry import BoundingBox
from engine.ports.tracking import Track, TrackState
from engine.presence.assembler import PresenceAssembler

T0 = 1_760_000_000.0   # jam dinding awal stream (UTC)
W, H = 640, 480


# --------------------------------------------------------------------------
# Gerbang kualitas
# --------------------------------------------------------------------------

RULES = CropRules(min_height_px=96, min_aspect=0.15, max_aspect=1.0, edge_margin_px=2)


def test_gerbang_crop_bagus():
    q = assess_crop(100, 100, 160, 260, W, H, RULES)
    assert (q.level, q.reason, q.usable) == (GOOD, "ok", True)


def test_gerbang_terlalu_kecil():
    q = assess_crop(100, 100, 130, 180, W, H, RULES)
    assert (q.level, q.reason, q.usable) == (REJECT, "too_small", False)


def test_gerbang_rasio_aspek():
    assert assess_crop(100, 100, 300, 200, W, H, RULES).reason == "aspect"   # terlalu lebar
    assert assess_crop(100, 100, 110, 300, W, H, RULES).reason == "aspect"   # terlalu sempit


def test_gerbang_terpotong_tepi_berkualitas_rendah():
    q = assess_crop(0, 100, 60, 260, W, H, RULES)
    assert (q.level, q.reason, q.truncated, q.usable) == (LOW, "truncated", True, False)
    q = assess_crop(100, 300, 160, 480, W, H, RULES)
    assert q.truncated


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def _yaml(tmp_path, text: str):
    path = tmp_path / "engine.yaml"
    path.write_text(text, encoding="utf-8")
    return load_config(str(path))


def test_blok_reid_dibaca_dan_ambang_sampai_ke_inti(tmp_path):
    config = _yaml(tmp_path, """
recognition:
  enabled: true
  recognizer: onnx_face
  face_detector_model: det.onnx
  face_embedder_model: emb.onnx
reid:
  enabled: true
  model_path: engine/models/reid/x.onnx
  model_sha256: "%s"
  match_threshold: 0.72
  min_crop_height_px: 120
  embed_interval_seconds: 20
  max_batch: 4
  travel_time_seconds:
    lobby: {smoking: 12}
  default_travel_time_seconds: 45
""" % ("ab" * 32))
    reid = config.reid
    assert reid.enabled and reid.max_batch == 4 and reid.embed_interval_seconds == 20
    assert reid.crop_rules().min_height_px == 120
    merge = reid.merge_config()
    assert merge.match_threshold == pytest.approx(0.72)
    assert merge.travel_seconds("smoking", "lobby") == 12
    assert merge.travel_seconds("lobby", "biliar") == 45

    runtime = build_reid_runtime(reid, emit_event=lambda m: m,
                                 embed=lambda crops: np.eye(len(crops), 8), start=False)
    assert runtime.coordinator.config.match_threshold == pytest.approx(0.72)


def test_ambang_kosong_memakai_usulan_belum_dikalibrasi():
    assert ReidSettings().merge_config().match_threshold == pytest.approx(0.80)


def test_kunci_reid_tak_dikenal_ditolak(tmp_path):
    with pytest.raises(ConfigBoundaryError, match="reid.ambang"):
        _yaml(tmp_path, "reid:\n  ambang: 0.7\n")


def test_reid_tanpa_rekognisi_wajah_ditolak(tmp_path):
    with pytest.raises(ValueError, match="recognition.recognizer"):
        _yaml(tmp_path, "reid:\n  enabled: true\n")


@pytest.mark.parametrize("bad", [
    {"model_sha256": "xyz"},
    {"match_threshold": 1.5},
    {"embed_interval_seconds": 0},
    {"min_aspect": 1.2},
    {"travel_time_seconds": {"lobby": 5}},
])
def test_nilai_reid_tidak_sah_ditolak(bad):
    with pytest.raises(ValueError):
        ReidSettings(**bad)


def test_reid_mati_tidak_membuat_runtime():
    assert build_reid_runtime(ReidSettings(), emit_event=lambda m: m,
                              embed=lambda c: pytest.fail("dipanggil")) is None


# --------------------------------------------------------------------------
# Worker
# --------------------------------------------------------------------------

def _job_args(i: int):
    return ("r1", i, f"tr_t{i}", T0 + i, np.full((10, 5, 3), i, np.uint8))


def test_worker_menggabung_crop_jadi_satu_batch():
    calls, delivered = [], []

    def embed(crops):
        calls.append(len(crops))
        return np.eye(len(crops), 4)

    worker = ReidWorker(embed, lambda job, vec: delivered.append((job.track_uuid, vec)),
                        max_queue=8, max_batch=3)
    for i in range(5):
        assert worker.submit(*_job_args(i))
    worker.process(worker._drain_nowait(3))
    worker.process(worker._drain_nowait(3))
    assert calls == [3, 2]
    assert [uuid for uuid, _ in delivered] == [f"tr_t{i}" for i in range(5)]
    assert all(vec is not None for _, vec in delivered)


def test_worker_antrean_penuh_ditolak_seketika():
    worker = ReidWorker(lambda c: np.eye(len(c), 4), lambda j, v: None, max_queue=2)
    assert worker.submit(*_job_args(0)) and worker.submit(*_job_args(1))
    assert not worker.submit(*_job_args(2))
    assert worker.snapshot_metrics()["rejected_full"] == 1


def test_worker_membuang_crop_basi():
    now = [0.0]
    delivered = []
    worker = ReidWorker(lambda c: pytest.fail("crop basi di-embed"),
                        lambda job, vec: delivered.append(vec), max_age_seconds=1.0,
                        clock=lambda: now[0])
    worker.submit(*_job_args(0))
    now[0] = 2.0
    worker.process(worker._drain_nowait(8))
    assert delivered == [None]
    assert worker.snapshot_metrics()["dropped_stale"] == 1


def test_worker_gagal_tidak_mati_dan_menjawab_none():
    delivered = []

    def embed(crops):
        raise RuntimeError("GPU hilang")

    worker = ReidWorker(embed, lambda job, vec: delivered.append(vec)).start()
    worker.submit(*_job_args(0))
    deadline = time.time() + 5
    while not delivered and time.time() < deadline:
        time.sleep(0.01)
    assert delivered == [None] and worker.running
    worker.stop()


# --------------------------------------------------------------------------
# Kamera palsu: assembler asli + tap + worker sinkron + embedder palsu
# --------------------------------------------------------------------------

def _embed_warna(crops: List[np.ndarray]) -> np.ndarray:
    """Embedding palsu: kanal biru piksel kiri-atas = kode orang -> vektor satu-panas."""
    out = np.zeros((len(crops), 16), dtype=np.float32)
    for row, crop in enumerate(crops):
        out[row, int(crop[0, 0, 0]) % 16] = 1.0
    return out


class _Kamera:
    def __init__(self, camera_id: str, runtime, emit):
        self.camera_id = camera_id
        self.assembler = PresenceAssembler(emit=emit, interval_prefix=f"iv_{camera_id}",
                                           interval_gate=runtime.coordinator.interval_gate)
        self.assembler.camera_online(camera_id, wallclock_now=T0, fps=10.0)
        self.tap = runtime.tap_for(camera_id, self.assembler)
        self.tracks: Dict[str, Track] = {}
        self.codes: Dict[str, int] = {}

    def masuk(self, uuid: str, track_id: int, code: int, pts: float) -> None:
        track = Track(track_id=track_id, bbox=BoundingBox(200, 100, 260, 300),
                      state=TrackState.TRACKED)
        track.attributes["track_uuid"] = uuid
        self.tracks[uuid] = track
        self.codes[uuid] = code
        self.assembler.track_started(uuid, self.camera_id, pts)

    def wajah(self, uuid: str, person_id: str, pts: float) -> None:
        self.tracks[uuid].attributes["identity_state"] = SimpleNamespace(
            person_id=person_id, identity_source="face", confidence=0.9)
        self.assembler.identified(uuid, person_id, pts=pts, similarity=0.9, margin=0.2,
                                  evidence_count=3, confidence=0.9)

    def keluar(self, uuid: str, pts: float) -> None:
        self.tracks.pop(uuid)
        self.assembler.track_ended(uuid, pts=pts, reason="left_frame", zone="door")

    def frame(self, pts: float) -> None:
        image = np.zeros((H, W, 3), dtype=np.uint8)
        for uuid, code in self.codes.items():
            if uuid in self.tracks:
                image[100:300, 200:260] = (code, 0, 0)
        self.tap.step(SimpleNamespace(image=image), list(self.tracks.values()), pts)


def _runtime(**settings: Any):
    base = dict(enabled=True, embed_interval_seconds=15.0, max_batch=8,
                travel_time_seconds={"r1": {"r2": 5}}, default_travel_time_seconds=30)
    base.update(settings)
    messages: List[Dict[str, Any]] = []

    def emit(message):
        message = dict(message, seq=len(messages) + 1)
        messages.append(message)
        return message

    runtime = build_reid_runtime(ReidSettings(**base), emit_event=emit, embed=_embed_warna,
                                 start=False)
    return runtime, messages, emit


def _flush(runtime) -> None:
    worker = runtime.worker
    while True:
        jobs = worker._drain_nowait(8)
        if not jobs:
            return
        worker.process(jobs)


def _jalan(kameras, start: float, end: float, runtime, step: float = 0.5) -> None:
    pts = start
    while pts <= end + 1e-9:
        for kamera in kameras:
            kamera.frame(pts)
        _flush(runtime)
        pts += step


def test_embedding_berbasis_kejadian_bukan_tiap_frame():
    runtime, _, emit = _runtime()
    r1 = _Kamera("r1", runtime, emit)
    r1.masuk("tr_r1-a", 1, 3, 0.0)
    _jalan([r1], 0.0, 40.0, runtime)            # 81 frame
    assert r1.tap.metrics.submitted == 3        # dtk 0, 15, 30
    r1.wajah("tr_r1-a", "4471", 41.0)
    _jalan([r1], 41.0, 42.0, runtime)
    assert r1.tap.metrics.submitted == 4        # wajah baru terkonfirmasi = kejadian


def test_crop_kecil_tidak_dikirim_ke_worker():
    runtime, _, emit = _runtime(min_crop_height_px=400)
    r1 = _Kamera("r1", runtime, emit)
    r1.masuk("tr_r1-a", 1, 3, 0.0)
    _jalan([r1], 0.0, 5.0, runtime)
    assert r1.tap.metrics.submitted == 0
    assert r1.tap.metrics.gate_too_small >= 1


def test_dua_kamera_anon_lalu_wajah_menghasilkan_identity_resolved_yang_sah():
    runtime, messages, emit = _runtime()
    r1, r2 = _Kamera("r1", runtime, emit), _Kamera("r2", runtime, emit)

    # r1: orang tanpa wajah (kode 3) 0-10 dtk -> kelompok ANON, interval ANON.
    r1.masuk("tr_r1-a", 1, 3, 0.0)
    _jalan([r1], 0.0, 10.0, runtime)
    anon = r1.tap.label_of("tr_r1-a")
    assert anon is not None and anon[0].startswith("ANON-") and anon[1] == "reid"
    r1.keluar("tr_r1-a", 10.0)
    _jalan([r1], 10.5, 11.0, runtime)

    # r2: orang yang sama (kode 3) muncul dtk 20 (> waktu tempuh 5) -> kelompok yang sama.
    r2.masuk("tr_r2-b", 1, 3, 20.0)
    _jalan([r2], 20.0, 24.0, runtime)
    assert r2.tap.label_of("tr_r2-b") == anon

    # Wajah terbaca di r2 -> kelompok diselesaikan ke 4471.
    r2.wajah("tr_r2-b", "4471", 25.0)
    _jalan([r2], 25.0, 30.0, runtime)
    r2.keluar("tr_r2-b", 30.0)

    # r1: tubuh yang sama tanpa wajah dtk 40 -> cocok galeri berjangkar wajah (reid).
    r1.masuk("tr_r1-c", 2, 3, 40.0)
    _jalan([r1, r2], 40.0, 44.0, runtime)
    assert r1.tap.label_of("tr_r1-c") == ("4471", "reid")
    r1.keluar("tr_r1-c", 45.0)

    # Orang lain (kode 5) tidak tertukar: ANON baru.
    r1.masuk("tr_r1-d", 3, 5, 50.0)
    _jalan([r1], 50.0, 52.0, runtime)
    other = r1.tap.label_of("tr_r1-d")
    assert other[0].startswith("ANON-") and other[0] != anon[0]

    resolved = [m for m in messages if m["type"] == "identity.resolved"]
    assert len(resolved) == 1
    event = resolved[0]
    anon_intervals = [m for m in messages
                      if m["type"] == "presence.interval" and m["person_id"] == anon[0]]
    assert len(anon_intervals) == 1
    assert event["anon_id"] == anon[0] and event["person_id"] == "4471"
    assert event["reason"] == "face_confirmed"
    assert event["trigger_track_uuid"] == "tr_r2-b"
    assert set(event["track_uuids"]) == {"tr_r1-a", "tr_r2-b"}
    assert event["moved_intervals"] == [anon_intervals[0]["interval_id"]]
    assert messages.index(anon_intervals[0]) < messages.index(event)
    after = [m for m in messages if m["type"] == "presence.interval"
             and m.get("track_uuid") in ("tr_r2-b", "tr_r1-c")]
    assert [m["person_id"] for m in after] == ["4471", "4471"]

    validator = SchemaValidator()
    for message in messages:
        assert not validator.validate_message(message, expected_channel="events"), message
    report = ConformanceChecker().check(messages)
    assert report.ok, report.errors


def test_interval_anon_yang_ditutup_sesudah_penyelesaian_langsung_berlabel_karyawan():
    """Gerbang interval: label ANON lama di presence diganti saat ditutup."""
    runtime, messages, emit = _runtime()
    r1, r2 = _Kamera("r1", runtime, emit), _Kamera("r2", runtime, emit)
    r1.masuk("tr_r1-a", 1, 3, 0.0)
    _jalan([r1], 0.0, 3.0, runtime)
    anon = r1.tap.label_of("tr_r1-a")[0]
    r1.keluar("tr_r1-a", 3.0)
    _jalan([r1], 3.5, 3.5, runtime)
    r2.masuk("tr_r2-b", 1, 3, 10.0)
    _jalan([r2], 10.0, 11.0, runtime)
    # Wajah dikirim langsung ke koordinator TANPA frame berikutnya di r2:
    # label di presence r2 masih ANON saat track ditutup.
    runtime.coordinator.observe(BodyObservation(
        camera_id="r2", track_id=1, track_uuid="tr_r2-b", at=T0 + 11.5, face_person_id="4471"))
    r2.keluar("tr_r2-b", 12.0)
    closed = [m for m in messages if m["type"] == "presence.interval"
              and m.get("track_uuid") == "tr_r2-b"]
    assert closed[0]["person_id"] == "4471"
    resolved = [m for m in messages if m["type"] == "identity.resolved"][0]
    assert resolved["anon_id"] == anon
    assert ConformanceChecker().check(messages).ok


def test_id_anon_berbeda_antar_proses_engine():
    """Engine restart di tengah hari tidak boleh menerbitkan ANON yang sama lagi."""
    def anon_pertama(coordinator):
        coordinator.register("r1")
        coordinator.observe(BodyObservation(camera_id="r1", track_id=1, track_uuid="tr_x",
                                             at=T0, embedding=np.eye(1, 8)[0]))
        return coordinator.core.unresolved_anon_ids()[0]

    config = ReidSettings().merge_config()
    a = anon_pertama(ReidCoordinator(config, emit_event=lambda m: m, nonce="a1b2"))
    b = anon_pertama(ReidCoordinator(config, emit_event=lambda m: m, nonce="c3d4"))
    assert a != b
    assert a.startswith("ANON-") and a.endswith("a1b20001")
    import re
    assert re.match(r"^ANON-[A-Za-z0-9]{1,32}$", a)


def test_waktu_tempuh_mustahil_tidak_digabung():
    runtime, _, emit = _runtime(travel_time_seconds={"r1": {"r2": 60}})
    r1, r2 = _Kamera("r1", runtime, emit), _Kamera("r2", runtime, emit)
    r1.masuk("tr_r1-a", 1, 3, 0.0)
    _jalan([r1], 0.0, 2.0, runtime)
    r1.keluar("tr_r1-a", 2.0)
    _jalan([r1], 2.5, 2.5, runtime)
    r2.masuk("tr_r2-b", 1, 3, 10.0)          # 8 dtk kemudian, butuh 60
    _jalan([r2], 10.0, 12.0, runtime)
    assert r1.tap.label_of("tr_r1-a") is None   # sudah berakhir
    label = r2.tap.label_of("tr_r2-b")
    assert label[0].startswith("ANON-")
    assert runtime.coordinator.core.group_members(label[0]) == ("tr_r2-b",)


def test_track_berwajah_tidak_pernah_dilabeli_reid():
    runtime, _, emit = _runtime()
    r1 = _Kamera("r1", runtime, emit)
    r1.masuk("tr_r1-a", 1, 3, 0.0)
    r1.wajah("tr_r1-a", "4471", 0.0)
    _jalan([r1], 0.0, 5.0, runtime)
    assert r1.tap.label_of("tr_r1-a") is None
    assert runtime.coordinator.core.gallery.persons() == ["4471"]


# --------------------------------------------------------------------------
# Kamera sungguhan (sumber mock) dengan ReID menyala
# --------------------------------------------------------------------------

def test_kamera_mock_dengan_reid_tetap_conformant():
    from engine.runtime.camera import CameraSpec, CameraSupervisor

    messages: List[Dict[str, Any]] = []

    def emit(message):
        message = dict(message, seq=len(messages) + 1)
        messages.append(message)
        return message

    runtime = build_reid_runtime(
        ReidSettings(enabled=True, min_crop_height_px=50), emit_event=emit,
        embed=_embed_warna, start=True)
    config = dataclasses.replace(load_config(), source_type="mock", auto_warmup=False)
    camera = CameraSupervisor(spec=CameraSpec("r1", "mock", [0.0, 0.0, 0.4, 0.4]), config=config,
                              emit_event=emit, emit_view=lambda m: m, max_frames=60, reid=runtime)
    camera.start()
    deadline = time.time() + 30
    while camera.alive and time.time() < deadline:
        time.sleep(0.02)
    camera.stop()
    runtime.stop()

    assert runtime.worker.snapshot_metrics()["submitted"] >= 1
    intervals = [m for m in messages if m["type"] == "presence.interval"]
    assert intervals and intervals[0]["person_id"].startswith("ANON-")
    beats = [m for m in messages if m["type"] == "track.heartbeat"]
    assert beats and beats[0]["identity_source"] == "reid"
    # Tanpa wajah orangnya tetap "belum dikenali", walau berlabel ANON.
    validator = SchemaValidator()
    for message in messages:
        assert not validator.validate_message(message, expected_channel="events"), message
    assert ConformanceChecker().check(messages).ok


# --------------------------------------------------------------------------
# Pengosongan cache harian terjadwal (reid.daily_purge_time)
# --------------------------------------------------------------------------

def _lokal(hari: int, jam: int, menit: int = 0) -> float:
    from datetime import datetime
    return datetime(2026, 10, hari, jam, menit).timestamp()


def test_jam_purge_dibaca_dari_config(tmp_path):
    config = _yaml(tmp_path, 'reid:\n  daily_purge_time: "03:30"\n')
    assert config.reid.purge_offset_seconds() == 3 * 3600 + 30 * 60
    config = _yaml(tmp_path, "reid:\n  daily_purge_time: 03:30\n")   # tanpa kutip
    assert config.reid.daily_purge_time == "03:30"


@pytest.mark.parametrize("bad", ["24:00", "3", "03:7", "aa:bb", "12:60"])
def test_jam_purge_tidak_sah_ditolak(bad):
    with pytest.raises(ValueError, match="daily_purge_time"):
        ReidSettings(daily_purge_time=bad)


def _isi_galeri(coordinator, at: float) -> None:
    coordinator.register("r1")
    coordinator.observe(BodyObservation(camera_id="r1", track_id=1, track_uuid="tr_wajah", at=at,
                                         embedding=np.eye(1, 8)[0], face_person_id="4471"))
    coordinator.observe(BodyObservation(camera_id="r1", track_id=2, track_uuid="tr_anon", at=at,
                                         embedding=np.eye(1, 8, 3)[0]))


def test_cache_dikosongkan_terjadwal_walau_tidak_ada_pengamatan():
    coordinator = ReidCoordinator(ReidSettings().merge_config(), emit_event=lambda m: m,
                                  purge_offset_seconds=3 * 3600)   # 03:00
    _isi_galeri(coordinator, _lokal(9, 20))
    assert coordinator.core.gallery.persons() == ["4471"]
    assert coordinator.core.unresolved_anon_ids()

    assert not coordinator.maybe_purge(_lokal(9, 23, 59))
    assert not coordinator.maybe_purge(_lokal(10, 2, 59))    # lewat tengah malam, belum jam 03:00
    assert coordinator.core.gallery.persons() == ["4471"]
    assert coordinator.maybe_purge(_lokal(10, 3, 0))
    assert coordinator.core.gallery.persons() == []
    assert coordinator.core.unresolved_anon_ids() == ()
    assert coordinator.core.day == "2026-10-10"
    assert not coordinator.maybe_purge(_lokal(10, 3, 1))     # sekali per hari
    assert coordinator.snapshot_metrics()["days_purged"] == 1


def test_purge_tanpa_galeri_tidak_melakukan_apa_pun():
    coordinator = ReidCoordinator(ReidSettings().merge_config(), emit_event=lambda m: m)
    assert not coordinator.maybe_purge(_lokal(10, 0, 5))


def test_label_track_hidup_tidak_dicabut_oleh_purge():
    """Orang yang masih terlihat saat purge tidak kehilangan kehadirannya."""
    runtime, messages, emit = _runtime(daily_purge_time="00:00")
    r1 = _Kamera("r1", runtime, emit)
    r1.masuk("tr_r1-a", 1, 3, 0.0)
    _jalan([r1], 0.0, 3.0, runtime)
    label = r1.tap.label_of("tr_r1-a")
    assert label[0].startswith("ANON-")
    runtime.coordinator.maybe_purge(T0 + 2 * 86400)          # paksa hari berikutnya
    _jalan([r1], 3.5, 6.0, runtime)                           # pembaruan rentang sesudah purge
    assert r1.tap.label_of("tr_r1-a") == label
    r1.keluar("tr_r1-a", 6.0)
    intervals = [m for m in messages if m["type"] == "presence.interval"]
    assert [m["person_id"] for m in intervals] == [label[0]]
    assert ConformanceChecker().check(messages).ok


def test_ticker_runtime_memanggil_jadwal_purge(monkeypatch):
    from engine.runtime import EngineRuntime, RuntimeOptions

    base = dataclasses.replace(load_config(), source_type="mock", auto_warmup=False)
    config = dataclasses.replace(
        base,
        recognition=dataclasses.replace(base.recognition, enabled=True, recognizer="onnx_face",
                                        face_detector_model="det.onnx", face_embedder_model="emb.onnx"),
        reid=ReidSettings(enabled=True),
    )
    runtime = EngineRuntime(config=config, options=RuntimeOptions(tcp=("127.0.0.1", 0)),
                            recognize=lambda track, frame: None, reid_embed=_embed_warna)
    calls = []
    monkeypatch.setattr(runtime._reid.coordinator, "maybe_purge", lambda now: calls.append(now))
    runtime.listen()
    try:
        deadline = time.time() + 5
        while not calls and time.time() < deadline:
            time.sleep(0.05)
    finally:
        runtime.close()
    assert calls, "ticker tidak pernah memeriksa jadwal purge ReID"


# --------------------------------------------------------------------------
# forget_person -> data tubuh ikut dihapus (paket ea-r7)
# --------------------------------------------------------------------------

def test_galeri_lupa_orang_dan_diblokir_sampai_purge():
    from engine.identity.reid import DailyGallery

    gallery = DailyGallery("2026-10-09")
    assert gallery.add("4471", np.eye(1, 8)[0], source="face")
    assert gallery.forget("4471") == 1
    assert "4471" not in gallery
    assert not gallery.add("4471", np.eye(1, 8)[0], source="face"), "diisi lagi sebelum purge"
    assert gallery.forget("tidak-ada") == 0
    gallery.purge_day("2026-10-10")
    assert gallery.add("4471", np.eye(1, 8)[0], source="face"), "blokir harus hilang saat purge"


def test_lupa_orang_mencabut_klaim_reid_tetapi_tidak_klaim_wajah():
    runtime, messages, emit = _runtime()
    r1 = _Kamera("r1", runtime, emit)
    r1.masuk("tr_r1-a", 1, 3, 0.0)
    r1.wajah("tr_r1-a", "4471", 0.0)
    _jalan([r1], 0.0, 2.0, runtime)
    r1.keluar("tr_r1-a", 2.0)
    r1.masuk("tr_r1-b", 2, 3, 40.0)              # tubuh sama tanpa wajah -> reid 4471
    _jalan([r1], 40.0, 42.0, runtime)
    assert r1.tap.label_of("tr_r1-b") == ("4471", "reid")

    prototypes, revoked = runtime.coordinator.forget_person("4471")
    assert prototypes >= 1 and revoked == 1
    _jalan([r1], 42.5, 50.0, runtime)
    assert r1.tap.label_of("tr_r1-b") is None, "klaim ReID ke orang yang dihapus masih menempel"
    _jalan([r1], 50.5, 56.0, runtime)            # embedding ulang dtk 55: galeri kosong + diblokir
    label = r1.tap.label_of("tr_r1-b")
    assert label is not None and label[0].startswith("ANON-"), label
    assert runtime.coordinator.core.gallery.persons() == []
    r1.keluar("tr_r1-b", 56.0)
    owners = [m["person_id"] for m in messages if m["type"] == "presence.interval"
              and m.get("track_uuid") == "tr_r1-b"]
    assert owners == [label[0]], "interval harus atas nama ANON, bukan orang yang dihapus"
    assert ConformanceChecker().check(messages).ok


def test_handler_forget_person_runtime_ikut_menghapus_reid():
    from engine.runtime import EngineRuntime, RuntimeOptions

    base = dataclasses.replace(load_config(), source_type="mock", auto_warmup=False)
    config = dataclasses.replace(
        base,
        recognition=dataclasses.replace(base.recognition, enabled=True, recognizer="onnx_face",
                                        face_detector_model="det.onnx", face_embedder_model="emb.onnx"),
        reid=ReidSettings(enabled=True),
    )
    runtime = EngineRuntime(config=config, options=RuntimeOptions(tcp=("127.0.0.1", 0)),
                            recognize=lambda track, frame: None, reid_embed=_embed_warna)
    try:
        _isi_galeri(runtime._reid.coordinator, T0)
        reply = runtime._on_forget_person({"type": "forget_person", "request_id": "rq1",
                                           "person_id": "4471"})
        assert runtime._reid.coordinator.core.gallery.persons() == []
        assert set(reply) == {"type", "v", "ts", "request_id", "person_id", "removed_references"}
        assert not SchemaValidator().validate_message(reply, expected_channel="control")
    finally:
        runtime.close()
