"""P7: rekognisi wajah di luar loop frame.

Yang dibuktikan di sini:
- worker tidak pernah memblok pemanggilnya, menolak saat penuh, membuang
  pekerjaan basi, dan selalu menjawab (scheduler tidak boleh menunggu selamanya);
- hasil diterapkan di thread kamera pada frame berikutnya, bukan di thread worker;
- hasil untuk track yang sudah berakhir tidak menempel ke siapa pun;
- ujung ke ujung: dengan recognizer yang lambat, loop frame mode async jauh lebih
  cepat daripada sync, DAN orangnya tetap teridentifikasi.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from engine.identity.ports import Evidence
from engine.pipeline.recognition_worker import RecognitionWorker, TrackSnapshot


def _track(x1=10.0, track_id=1):
    return SimpleNamespace(track_id=track_id, bbox=SimpleNamespace(x1=x1, y1=20.0, x2=110.0, y2=220.0),
                           attributes={"zone": "door"})


def _wait(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


# --------------------------------------------------------------------------
# worker
# --------------------------------------------------------------------------


def test_submit_tidak_menunggu_recognizer_yang_lambat():
    gate = threading.Event()
    worker = RecognitionWorker(lambda track, frame: gate.wait(2.0) and "bukti", max_queue=4).start()
    try:
        done = []
        t0 = time.perf_counter()
        assert worker.submit("u1", "cam01", _track(), object(), lambda u, e: done.append((u, e)))
        assert time.perf_counter() - t0 < 0.05, "loop frame tidak boleh menunggu SCRFD/AuraFace"
        gate.set()
        assert _wait(lambda: done == [("u1", "bukti")])
    finally:
        worker.stop()


def test_antrean_penuh_ditolak_seketika():
    gate = threading.Event()
    worker = RecognitionWorker(lambda t, f: gate.wait(2.0), max_queue=2).start()
    try:
        results = []
        accepted = [worker.submit(f"u{i}", "cam01", _track(), None, lambda u, e: results.append(u))
                    for i in range(6)]
        # Satu sedang diproses + dua mengantre; sisanya ditolak tanpa menunggu.
        assert accepted.count(True) in (2, 3) and accepted.count(False) >= 3
        assert worker.snapshot_metrics()["rejected_full"] >= 3
        gate.set()
        assert _wait(lambda: len(results) == accepted.count(True)), "setiap yang diterima wajib dijawab"
    finally:
        worker.stop()


def test_pekerjaan_basi_dibuang_tapi_tetap_dijawab():
    gate = threading.Event()
    worker = RecognitionWorker(lambda t, f: gate.wait(2.0) or "bukti", max_queue=4,
                               max_age_seconds=0.05).start()
    try:
        results = {}
        worker.submit("lama-1", "cam01", _track(), None, lambda u, e: results.__setitem__(u, e))
        worker.submit("lama-2", "cam01", _track(), None, lambda u, e: results.__setitem__(u, e))
        time.sleep(0.2)          # lama-2 menunggu > 0,05 dtk di antrean
        gate.set()
        assert _wait(lambda: len(results) == 2)
        assert results["lama-2"] is None, "crop setengah detik lalu lebih buruk dari crop berikutnya"
        assert worker.snapshot_metrics()["dropped_stale"] >= 1
    finally:
        worker.stop()


def test_snapshot_kotak_tidak_ikut_berubah_saat_tracker_bergerak():
    seen = []
    gate = threading.Event()

    def recognize(track, frame):
        gate.wait(2.0)
        seen.append(track.bbox.x1)
        return None

    worker = RecognitionWorker(recognize).start()
    try:
        live = _track(x1=10.0)
        worker.submit("u1", "cam01", live, None, lambda u, e: None)
        live.bbox.x1 = 500.0      # tracker sudah memindahkan kotaknya
        gate.set()
        assert _wait(lambda: seen == [10.0])
        assert isinstance(TrackSnapshot.of(live), TrackSnapshot)
    finally:
        worker.stop()


def test_recognizer_yang_error_tidak_mematikan_worker():
    calls = []

    def recognize(track, frame):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("wajah rusak")
        return "bukti"

    worker = RecognitionWorker(recognize).start()
    try:
        results = []
        worker.submit("u1", "c", _track(), None, lambda u, e: results.append(e))
        worker.submit("u2", "c", _track(), None, lambda u, e: results.append(e))
        assert _wait(lambda: results == [None, "bukti"])
        assert worker.snapshot_metrics()["failed"] == 1 and worker.running
    finally:
        worker.stop()


def test_stop_menjawab_pekerjaan_yang_tertinggal():
    gate = threading.Event()
    worker = RecognitionWorker(lambda t, f: gate.wait(0.3), max_queue=4).start()
    results = []
    for i in range(3):
        worker.submit(f"u{i}", "c", _track(), None, lambda u, e: results.append(u))
    worker.stop(timeout=2.0)
    assert sorted(results) == ["u0", "u1", "u2"]
    assert worker.submit("u9", "c", _track(), None, lambda u, e: None) is False


# --------------------------------------------------------------------------
# binding: hasil diterapkan di thread kamera
# --------------------------------------------------------------------------


class _InlineExecutor:
    """Executor yang menahan pekerjaan sampai tes melepasnya."""

    def __init__(self):
        self.jobs = []

    def submit(self, uuid, camera_id, track, frame, done):
        self.jobs.append((uuid, done))
        return True

    def finish_all(self, evidence):
        for uuid, done in self.jobs:
            done(uuid, evidence)
        self.jobs.clear()


def _binding(executor, recognize):
    from engine.identity import IdentityArbiter, InMemoryReferenceStore, MatrixMatcher, RecognitionScheduler
    from engine.presence.assembler import PresenceAssembler
    from engine.presence.binding import EngineBinding

    vector = np.ones(512, dtype=np.float32) / np.sqrt(512)
    other = np.zeros(512, dtype=np.float32)
    other[0] = 1.0
    store = InMemoryReferenceStore({"emp_017": [vector], "emp_002": [other]}, embedding_version="v")
    matcher = MatrixMatcher(store)
    matcher.rebuild()
    emitted = []
    assembler = PresenceAssembler(emit=emitted.append)
    assembler.camera_online("cam01", wallclock_now=1759370000.0, fps=12.0)
    scheduler = RecognitionScheduler()
    binding = EngineBinding(arbiter=IdentityArbiter(matcher=matcher), assembler=assembler,
                            scheduler=scheduler, recognize=recognize, executor=executor)
    return binding, scheduler, emitted, vector


def _frame(pts, camera="cam01"):
    from engine.ports.frame import Frame, FrameMetadata
    return Frame(image=np.zeros((240, 320, 3), dtype=np.uint8),
                 metadata=FrameMetadata(frame_id=int(pts * 10), pts=pts, source_id=camera))


def _live_track(track_id=1):
    from engine.ports.geometry import BoundingBox
    from engine.ports.tracking import Track, TrackState
    import inspect
    params = inspect.signature(Track).parameters
    kwargs = {"track_id": track_id, "bbox": BoundingBox(10, 20, 110, 220)}
    if "state" in params:
        kwargs["state"] = TrackState.TRACKED
    track = Track(**kwargs)
    track.state = TrackState.TRACKED
    return track


def test_hasil_diterapkan_di_frame_berikutnya_bukan_saat_diminta():
    executor = _InlineExecutor()
    binding, scheduler, emitted, vector = _binding(executor, recognize=lambda t, f: None)
    track = _live_track()
    binding.on_tracks_updated([track], _frame(1.0))
    uuid = track.attributes["track_uuid"]
    request = SimpleNamespace(track_uuid=uuid, camera_id="cam01")

    binding(request)
    assert binding.pending_recognitions == 1 and binding.metrics.evidence_submitted == 0

    executor.finish_all(Evidence(embedding=vector, pts=1.0, quality=1.0, embedding_version="v"))
    assert binding.metrics.evidence_submitted == 0, "thread worker tidak boleh menyentuh arbiter"

    binding.on_tracks_updated([track], _frame(1.1))
    assert binding.metrics.evidence_submitted == 1 and binding.pending_recognitions == 0
    assert binding.evidence_by_uuid[uuid] == 1


def test_hasil_untuk_track_yang_sudah_berakhir_dibuang():
    executor = _InlineExecutor()
    binding, scheduler, emitted, vector = _binding(executor, recognize=lambda t, f: None)
    track = _live_track()
    binding.on_tracks_updated([track], _frame(1.0))
    uuid = track.attributes["track_uuid"]
    binding(SimpleNamespace(track_uuid=uuid, camera_id="cam01"))

    binding.on_track_removed(track)              # orangnya keluar frame
    executor.finish_all(Evidence(embedding=vector, pts=1.0, quality=1.0, embedding_version="v"))
    binding.on_tracks_updated([], _frame(1.2))
    assert binding.metrics.results_discarded == 1 and binding.metrics.evidence_submitted == 0
    assert not any(m.get("type") == "track.identified" for m in emitted)


def test_antrean_worker_penuh_melepas_giliran_scheduler():
    class Full:
        def submit(self, *a, **k):
            return False

    binding, scheduler, emitted, vector = _binding(Full(), recognize=lambda t, f: None)
    track = _live_track()
    binding.on_tracks_updated([track], _frame(1.0))
    uuid = track.attributes["track_uuid"]
    scheduler._in_flight[uuid] = (1.0, "cam01")    # seolah baru di-pop
    binding(SimpleNamespace(track_uuid=uuid, camera_id="cam01"))
    assert scheduler.in_flight == 0, "track yang ditolak worker wajib bisa diminta lagi"
    assert binding.metrics.recognitions_rejected == 1


# --------------------------------------------------------------------------
# ujung ke ujung: runtime asli, sumber mock, recognizer lambat
# --------------------------------------------------------------------------


def _run_runtime(execution: str, seconds: float = 2.5):
    from engine.config import load_config
    from engine.identity import InMemoryReferenceStore, MatrixMatcher
    from engine.runtime.service import EngineRuntime, RuntimeOptions

    base = load_config()
    config = dataclasses.replace(
        base, source_type="mock", auto_warmup=False, target_fps=None,
        recognition=dataclasses.replace(base.recognition, enabled=True, execution=execution,
                                        max_requests_per_frame=2, embedding_version="v"),
    )
    vector = np.ones(512, dtype=np.float32) / np.sqrt(512)
    other = np.zeros(512, dtype=np.float32)
    other[0] = 1.0
    matcher = MatrixMatcher(InMemoryReferenceStore({"emp_017": [vector], "emp_002": [other]},
                                                   embedding_version="v"))
    matcher.rebuild()

    rng = np.random.default_rng(7)
    threads = []

    def slow_recognize(track, frame):
        threads.append(threading.current_thread().name)
        time.sleep(0.05)                          # 50 ms per wajah, seperti SCRFD+AuraFace di GPU sibuk
        # Wajah asli berbeda sedikit antar-frame; bukti identik ditolak arbiter
        # sebagai redundant_evidence (bukan bukti independen).
        noisy = vector + rng.normal(0.0, 0.02, 512).astype(np.float32)
        return Evidence(embedding=noisy / np.linalg.norm(noisy), pts=float(frame.metadata.pts or 0.0),
                        quality=1.0, embedding_version="v")

    emitted = []
    runtime = EngineRuntime(config=config, options=RuntimeOptions(tcp=None, view_fps=0.0),
                            recognize=slow_recognize, matcher=matcher)
    runtime.emit_event = lambda m: emitted.append(m) or m     # tangkap event tanpa socket
    try:
        from engine.runtime.camera import CameraSpec
        camera = runtime._start_camera(CameraSpec("cam01", "mock")) if hasattr(runtime, "_start_camera") else None
        if camera is None:
            runtime._on_set_cameras({"type": "set_cameras", "cameras": [{"camera_id": "cam01", "uri": "mock"}]})
            camera = runtime.cameras["cam01"]
        time.sleep(seconds)
        frames = camera.stats.frames
    finally:
        runtime.close()
    identified = [m for m in emitted if m.get("type") == "track.identified"]
    return frames, identified, threads


def test_async_loop_frame_tidak_tertahan_recognizer_lambat():
    """Yang dibuktikan: rekognisi TIDAK berjalan di thread kamera saat async.

    Dulu diukur dengan rasio frame (async > 3x sync). Rasio itu bergantung mesin:
    di Windows/4060 (3 Okt) 4410 vs 1961 = 2,25x, karena loop mock jauh lebih
    cepat dari 50 ms sehingga porsi waktu rekognisi berbeda per mesin. Thread
    tempat recognizer dipanggil tidak bergantung kecepatan mesin.
    """
    sync_frames, _, sync_threads = _run_runtime("sync")
    async_frames, async_identified, async_threads = _run_runtime("async")
    camera_thread = "camera-cam01"
    assert sync_threads and all(name == camera_thread for name in sync_threads), (
        f"sync wajib memanggil recognizer di thread kamera: {set(sync_threads)}"
    )
    assert async_threads and camera_thread not in async_threads, (
        f"async: recognizer dipanggil di thread kamera -> rekognisi masih menahan loop ({set(async_threads)})"
    )
    assert async_frames > sync_frames, (
        f"loop frame async {async_frames} frame vs sync {sync_frames}: rekognisi masih menahan loop"
    )
    assert async_identified, "async wajib tetap mengidentifikasi orangnya"
