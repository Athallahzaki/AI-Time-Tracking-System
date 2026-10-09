"""
The engine as a process: one socket, one sequence, N cameras.

`fake_engine` has been the only thing the backend could talk to. This is the
real one, speaking the same protocol on the same socket, and the point of the
exercise is that the backend cannot tell which it is connected to except by the
pictures being real.

## What is shared, and the lock that follows from it

**One outbox, one `seq`.** §6.5 makes the sequence monotonic across the whole
engine, not per camera — a backend that reconnects asks for everything after
`last_event_seq` and gets one ordered stream. Five camera threads appending to
one counter is the one genuine race in this design, and `Outbox.append` (the
in-memory one) does not lock. So every emission goes through `emit_event` here,
under one lock. The SQLite outbox locks internally and would not need it; paying
for a lock that is already held costs a few microseconds on a path that runs a
hundred times a second, and having two rules for two outboxes costs a bug.

**One scheduler.** Its per-camera quota (§5.2) is meaningless unless one queue
sees every camera, so it is shared and wrapped in `_LockedScheduler` rather than
edited — `identity/` is Engine A's, and a lock belongs to whoever assembles the
threads, not to the policy being locked.

**One matcher.** Read-mostly: rebuilt when `set_roster` changes the references,
read on every recognition. Guarded by the same lock during rebuild.

## Reconciliation, not commands

`set_cameras` carries the whole desired set and this layer matches its state to
it (§6.3): open what is missing, close what is gone, leave alone what matches,
and re-label the zone of a camera whose only change is its door region — a zone
is applied to boxes, so it does not need the stream reopened. Imperative
`add_camera`/`remove_camera` desynchronises the moment one message is lost and
nobody finds out until a ghost camera is still being processed.

**The command is acked when received, never when done.** Opening RTSP can take
five seconds and can fail; the result arrives as `camera.online` or
`camera.failed`. A `set_cameras` that waited would hang the backend at startup,
and that is §6.3 in one sentence.

## What this deliberately does not do yet

**Enrollment is declined, out loud.** `enroll` needs an embedder, and no
recognizer is wired until the identity models land (§10, step A8/15). An engine
that accepted enrolments and stored nothing would be the §9 item 9 failure in
its most expensive form, so the ack says no and says why.

**No cross-camera fusion.** §5.4 is step 17. Identity is per camera here, and
`snapshot` reports each camera's own live list rather than a merged one.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..api import EngineApi, events
from ..api.outbox import Outbox, SqliteOutbox
from ..config import EngineConfig, load_config
from ..identity import RecognitionScheduler
from .camera import CameraSpec, CameraSupervisor

logger = logging.getLogger("engine.runtime")

# How often the engine restates the whole picture (§4.5) and its own condition.
SNAPSHOT_INTERVAL_SECONDS = 10.0
HEALTH_INTERVAL_SECONDS = 30.0


class _LockedScheduler:
    """One scheduler, many camera threads.

    A wrapper rather than a lock inside `RecognitionScheduler`: that class is
    Engine A's and is correct as written for one caller. Which threads exist is
    a fact about this module, so the lock lives here.
    """

    def __init__(self, inner: RecognitionScheduler) -> None:
        self._inner = inner
        self._lock = threading.Lock()

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._inner, name)
        if not callable(attribute):
            return attribute

        def locked(*args: Any, **kwargs: Any) -> Any:
            with self._lock:
                return attribute(*args, **kwargs)

        return locked


@dataclass
class RuntimeOptions:
    config_path: Optional[str] = None
    tcp: Optional[Tuple[str, int]] = ("127.0.0.1", 8765)
    socket_path: Optional[str] = None
    engine_version: str = "0.4.0"
    snapshot_interval_seconds: float = SNAPSHOT_INTERVAL_SECONDS
    health_interval_seconds: float = HEALTH_INTERVAL_SECONDS
    view_fps: float = 10.0
    max_frames: Optional[int] = None
    # Berkas outbox durabel. `None` = di memori (hanya untuk tes). Engine asli
    # (`python -m engine.runtime`) selalu mengisinya: nomor urut wajib bertahan
    # melintasi restart, lihat docstring `api/outbox.py`.
    outbox_path: Optional[str] = None
    # Override core.target_fps (None = pakai nilai config). Frame di atas laju
    # ini dibuang sebelum detector; cara paling murah membuat engine ringan.
    target_fps: Optional[float] = None
    # Ulang video file lokal dari awal saat habis (demo/testing).
    loop_files: bool = False
    # Kunci bersama handshake (P3). None = autentikasi mati. Diisi dari env
    # ENGINE_SHARED_KEY oleh __main__, tidak pernah dari argumen CLI.
    auth_key: Optional[str] = None


class EngineRuntime:
    """Owns the socket, the cameras, and the one sequence they share."""

    def __init__(
        self,
        config: Optional[EngineConfig] = None,
        options: Optional[RuntimeOptions] = None,
        api: Optional[EngineApi] = None,
        matcher: Any = None,
        recognize: Optional[Callable[..., Any]] = None,
        reference_store: Any = None,
        reid_embed: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.options = options or RuntimeOptions()
        self.config = config or load_config(self.options.config_path)
        if self.options.target_fps:
            import dataclasses
            self.config = dataclasses.replace(
                self.config, target_fps=float(self.options.target_fps))
        # Penjadwal berdetak tahap 1 (dokumen 04 §14). Detak = fps analisis:
        # target_fps disamakan supaya tracker dan decimation file memakai irama
        # yang sama dengan detaknya.
        from .tick_scheduler import TickGate, tick_fps_for
        tick_fps = tick_fps_for(self.config.scheduler, self.config.tick_fps, self.config.target_fps)
        self._tick_gate: Optional[TickGate] = None
        if tick_fps is not None:
            if self.config.target_fps != tick_fps:
                import dataclasses
                logger.info("core.scheduler tick: target_fps %s -> %.2f (mengikuti tick_fps)",
                            self.config.target_fps, tick_fps)
                self.config = dataclasses.replace(self.config, target_fps=tick_fps)
            self._tick_gate = TickGate(tick_fps)
        # Sebelum detector/recognizer dimuat, supaya variabel lingkungan
        # masih berlaku untuk pustaka yang belum diimpor.
        from .threads import apply_cpu_threads
        self.cpu_threads = apply_cpu_threads(self.config.cpu_threads)

        if recognize is None and self.config.recognition.recognizer != "none":
            # The recognizer slot (config-driven). Fails loudly if the config
            # asks for it and it cannot load — never a silent nameless engine.
            recognize, reference_store, matcher = _build_identity(self.config)
        outbox = (
            SqliteOutbox(self.options.outbox_path)
            if self.options.outbox_path
            else Outbox()
        )
        self.api = api or EngineApi(
            outbox=outbox,
            engine_version=self.options.engine_version,
            models=_model_names(self.config, recognize is not None),
            auth_key=self.options.auth_key,
        )
        self._matcher = matcher
        self._recognize = recognize
        self._store = reference_store

        # ReID berjangkar wajah (dokumen 12 §3.6). Mati = None, tidak ada yang
        # dimuat. Menyala tapi model tidak bisa dimuat = ReidModelUnavailable
        # di sini, jadi engine menolak start (sama seperti recognizer wajah).
        # `reid_embed` hanya untuk tes (embedder palsu tanpa ONNX). Dimuat
        # sebelum worker wajah, supaya start yang ditolak tidak meninggalkan thread.
        from ..pipeline.reid_coordinator import build_reid_runtime

        self._reid = build_reid_runtime(self.config.reid, self.emit_event, embed=reid_embed)

        # P7: satu worker rekognisi untuk semua kamera (satu GPU). Loop frame
        # hanya menitipkan pekerjaan; lihat pipeline/recognition_worker.py.
        self._worker = None
        if recognize is not None and self.config.recognition.execution == "async":
            from ..pipeline.recognition_worker import DEFAULT_MAX_AGE_SECONDS, RecognitionWorker

            max_age = self.config.recognition.max_age_seconds or DEFAULT_MAX_AGE_SECONDS
            self._worker = RecognitionWorker(
                recognize, max_queue=self.config.recognition.worker_queue, max_age_seconds=max_age,
            ).start()

        # Satu D-FINE untuk semua kamera (detector.share_across_cameras),
        # dimuat saat kamera pertama dibuka. Lihat perception/shared_detector.py.
        self._shared_detector: Any = None
        self._detector_lock = threading.Lock()

        self._scheduler = _LockedScheduler(
            RecognitionScheduler(**self.config.recognition.scheduler_kwargs())
        )
        self._cameras: Dict[str, CameraSupervisor] = {}
        self._close_lock = threading.Lock()
        self._closing = False
        self._closed = threading.Event()
        self._emit_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._stop = threading.Event()
        self._ticker: Optional[threading.Thread] = None

        self.api.on_control("set_cameras", self._on_set_cameras)
        self.api.on_control("set_roster", self._on_set_roster)
        self.api.on_control("enroll", self._on_enroll)
        self.api.on_control("forget_person", self._on_forget_person)

    # -- emission ---------------------------------------------------------

    def emit_event(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Every durable event in the process passes through here, in order."""
        with self._emit_lock:
            return self.api.emit_event(message)

    def emit_view(self, message: Dict[str, Any]) -> bool:
        # No lock: the view channel has no sequence to keep, and a queue is
        # already thread-safe. Taking the lock here would let the best-effort
        # channel contend with the reliable one, which is backwards.
        return self.api.emit_view(message)

    # -- lifecycle --------------------------------------------------------

    def serve(self) -> None:
        """Listen, then block until stopped. The cameras arrive by `set_cameras`."""
        self.listen()
        try:
            self.api.serve_forever()
        finally:
            self.close()

    def listen(self) -> None:
        if self.options.socket_path:
            self.api.listen(socket_path=self.options.socket_path)
            logger.info("engine mendengarkan di %s", self.options.socket_path)
        else:
            self.api.listen(tcp=self.options.tcp)
            logger.info("engine mendengarkan di tcp %s:%s", *self.options.tcp)

        self._ticker = threading.Thread(
            target=self._tick_loop, name="engine-ticker", daemon=True
        )
        self._ticker.start()

    def close(self) -> None:
        """Idempoten dan aman dipanggil dari dua thread (Ctrl+C + akhir serve()).

        Pemanggil kedua MENUNGGU yang pertama selesai. Tanpa itu, thread utama
        keluar duluan sementara kamera masih menutup interval (`engine_shutdown`),
        dan proses mati sebelum event penutup terkirim. Menunggu dalam potongan
        pendek supaya Ctrl+C kedua tetap bisa masuk di Windows.
        """
        with self._close_lock:
            first = not self._closing
            self._closing = True
        if not first:
            while not self._closed.wait(0.2):
                pass
            return
        try:
            self._stop.set()
            with self._state_lock:
                cameras = list(self._cameras.values())
                self._cameras.clear()
            # Serentak: minta semua berhenti dulu, baru tunggu satu per satu.
            # Berurutan berarti 5 kamera x batas tunggu masing-masing.
            for camera in cameras:
                camera.request_stop()
            if self._tick_gate is not None:
                # Kamera yang sedang menunggu detak langsung dibangunkan.
                self._tick_gate.stop()
            for camera in cameras:
                camera.stop()
            if self._worker is not None:
                self._worker.stop()
            if self._reid is not None:
                self._reid.stop()
            if self._shared_detector is not None:
                self._shared_detector.stop()
            self.api.close()
        finally:
            self._closed.set()

    # -- control ----------------------------------------------------------

    def _on_set_cameras(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Declarative (§6.3). Acked now; `camera.online` follows when it opens."""
        try:
            desired = {
                spec.camera_id: spec for spec in _specs_from(message.get("cameras") or [])
            }
        except ValueError as error:
            return {
                "type": "ack", "v": 1, "ts": events.rfc3339(time.time()),
                "in_reply_to": "set_cameras", "accepted": False, "reason": str(error),
            }

        # Reconciliation runs on its own thread: opening a stream can take
        # seconds, and this function has to return an ack now.
        threading.Thread(
            target=self._reconcile, args=(desired,), name="set-cameras", daemon=True
        ).start()
        return None

    def _reconcile(self, desired: Dict[str, CameraSpec]) -> None:
        with self._state_lock:
            current = dict(self._cameras)

            pause_mode = self.config.analysis_off_mode == "pause"
            for camera_id, camera in current.items():
                spec = desired.get(camera_id)
                if pause_mode and spec is not None and spec.uri == camera.spec.uri:
                    # Kontrak ea-k1: enabled=false menjeda analisis, kamera tetap hidup.
                    camera.set_door_region(spec.door_region)
                    camera.set_analysis_enabled(spec.enabled)
                    continue
                if spec is None or not spec.enabled:
                    logger.info("[%s] tidak ada di daftar; ditutup", camera_id)
                    camera.stop()
                    self._cameras.pop(camera_id, None)
                    self._release_detector(camera_id)
                elif not spec.same_stream_as(camera.spec):
                    logger.info("[%s] uri berubah; dibuka ulang", camera_id)
                    camera.stop()
                    self._cameras.pop(camera_id, None)
                else:
                    # Same stream: only the label may have moved, and a label
                    # does not justify dropping everyone's presence.
                    camera.set_door_region(spec.door_region)

            for camera_id, spec in desired.items():
                if camera_id in self._cameras or not spec.enabled:
                    continue
                self._open(spec)

    def _open(self, spec: CameraSpec) -> CameraSupervisor:
        config = _config_for(self.config, spec)
        camera = CameraSupervisor(
            spec=spec,
            config=config,
            emit_event=self.emit_event,
            emit_view=self.emit_view,
            scheduler=self._scheduler if self.config.recognition.enabled else None,
            matcher=self._matcher,
            recognize=self._recognize,
            view_fps=self.options.view_fps,
            max_frames=self.options.max_frames,
            loop_files=self.options.loop_files,
            recognition_executor=self._worker,
            detector_provider=self._detector_for,
            tick_gate=self._tick_gate,
            reid=self._reid,
        )
        if self._tick_gate is not None and not self._tick_gate.running:
            self._tick_gate.start()
        self._cameras[spec.camera_id] = camera
        camera.start()
        return camera

    def _detector_for(self, camera_id: str, config: EngineConfig) -> Any:
        """Detector untuk satu kamera: handle ke detector bersama, atau miliknya sendiri.

        Dipanggil dari thread kamera. Kamera pertama memuat bobot dan
        memanaskannya (di bawah kunci); kamera berikutnya langsung dapat handle.
        Detector yang tidak bisa dibagi (MockDetector) dikembalikan apa adanya.
        """
        from .. import factory
        from ..perception.shared_detector import SharedDetector, supports_sharing

        if not config.detector.share_across_cameras:
            return None
        with self._detector_lock:
            if self._shared_detector is None:
                inner = factory.build_detector(config)
                if not supports_sharing(inner):
                    return inner
                shared = SharedDetector(inner, max_batch=config.detector.max_batch,
                                        batch_wait_ms=config.detector.batch_wait_ms,
                                        wait_for_all=self._tick_gate is not None)
                if config.auto_warmup:
                    shared.warmup()
                self._shared_detector = shared.start()
                logger.info("detector bersama dimuat sekali untuk semua kamera (batch maks %d, tunggu %.0f ms, "
                            "batch_inference %s)", config.detector.max_batch, config.detector.batch_wait_ms,
                            "on" if config.detector.batch_inference else "off")
            return self._shared_detector.handle(camera_id)

    def _release_detector(self, camera_id: str) -> None:
        if self._shared_detector is not None:
            self._shared_detector.release(camera_id)

    def _on_set_roster(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Same pattern as cameras: whole set in, engine matches its state.

        Vectors are never sent — only ids and versions (§3.3) — so the answer to
        "who do I not have references for" comes back as `enrollment_needed`.
        """
        persons = {
            str(entry.get("person_id")): int(entry.get("enrollment_version", 0))
            for entry in (message.get("persons") or [])
            if entry.get("person_id") is not None
        }

        if self._store is None:
            # No reference store: the engine cannot hold vectors at all, so the
            # honest answer is that every person on the roster is missing.
            self.emit_event(
                events.enrollment_needed(time.time(), sorted(persons))
            )
            return None

        with self._emit_lock:
            diff = self._store.set_roster(persons)
            if self._matcher is not None:
                self._matcher.rebuild()

        missing = sorted(getattr(diff, "needs_enrollment", []) or [])
        if missing:
            self.emit_event(events.enrollment_needed(time.time(), missing))
        return None

    def _on_enroll(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Answer with `enroll_result` (carrying request_id), never a bare ack.

        A bare ack has no request_id, so the backend could not tell which
        request it answered and the UI waited on "pending" forever.
        """
        request_id = str(message.get("request_id") or "unknown")
        images = message.get("images") or []
        ts = events.rfc3339(time.time())
        analyze = getattr(self._recognize, "analyze_image", None)
        if analyze is None or self._store is None or self._matcher is None:
            return {
                "type": "enroll_result", "v": 1, "ts": ts,
                "request_id": request_id, "accepted": False,
                "reason": "recognizer_disabled",
                "images": [{"id": str(img.get("id", "?")), "accepted": False} for img in images],
            }

        from ..identity.enrollment import EnrollmentPolicy, ImageCandidate

        candidates = []
        for image in images:
            candidates.append(_candidate_from(image, analyze, ImageCandidate))
        person_id = str(message.get("person_id"))
        version = int(message.get("enrollment_version", 1))
        with self._emit_lock:
            policy = EnrollmentPolicy(self._matcher)
            result = policy.evaluate(person_id, version, candidates)
            policy.commit(result, self._store, candidates)
            if result.accepted:
                self._matcher.rebuild()
        return result.to_message(request_id, self.config.recognition.embedding_version, ts)

    def _on_forget_person(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Hapus semua referensi + foto orang ini; jawab dengan bukti (P14, E13).

        Dijawab `forget_result`, bukan ack: backend wajib bisa menunjukkan bahwa
        penghapusan selesai. Idempoten -- orang tanpa referensi menghasilkan 0.
        Track yang sedang hidup dengan identitas ini kehilangan identitasnya
        paling lambat saat verifikasi ulang berikutnya (matriks sudah dibangun
        ulang tanpa orang itu).
        """
        request_id = str(message.get("request_id") or "unknown")
        person_id = str(message.get("person_id") or "")
        removed = 0
        if self._store is not None and person_id:
            with self._emit_lock:
                removed = int(self._store.delete_person(person_id))
                if self._matcher is not None:
                    self._matcher.rebuild()
        logger.info("forget_person %s: %d referensi dihapus", person_id, removed)
        return {
            "type": "forget_result", "v": 1, "ts": events.rfc3339(time.time()),
            "request_id": request_id, "person_id": person_id,
            "removed_references": removed,
        }

    # -- periodic ---------------------------------------------------------

    def _tick_loop(self) -> None:
        last_snapshot = 0.0
        last_health = 0.0
        while not self._stop.wait(0.5):
            now = time.time()
            if now - last_snapshot >= self.options.snapshot_interval_seconds:
                last_snapshot = now
                self._emit_snapshot(now)
            if now - last_health >= self.options.health_interval_seconds:
                last_health = now
                self._emit_health(now)
            if self._reid is not None:
                # Jadwal harian pengosongan cache ReID (reid.daily_purge_time).
                self._reid.coordinator.maybe_purge(now)

    def _emit_snapshot(self, now: float) -> None:
        """Lets a backend realign without replaying the day (§4.5).

        It carries `pts_wallclock_offset` per camera, which is the only way a
        backend learns that a camera reconnected and its old offset is stale.
        """
        with self._state_lock:
            cameras = list(self._cameras.values())
        clocks = [clock for clock in (camera.clock() for camera in cameras) if clock]
        if not clocks:
            return
        live: List[Dict[str, Any]] = []
        for camera in cameras:
            live.extend(camera.live_tracks())
        self.emit_event(events.snapshot(now, clocks, live))

    def _emit_health(self, now: float) -> None:
        with self._state_lock:
            cameras = list(self._cameras.values())

        states = {camera.spec.camera_id: _protocol_state(camera) for camera in cameras}
        degraded: List[str] = []
        models_loaded = self._recognize is not None
        if not models_loaded:
            degraded.append("recognizer_not_wired")
        for camera in cameras:
            health = camera.health()
            degraded.extend(
                f"{camera.spec.camera_id}:{item}"
                for item in health.get("degraded_components", [])
                if item != "recognizer_not_wired"
            )

        metrics = self._scheduler.metrics(0.0) if self.config.recognition.enabled else {}
        worker_depth = 0
        if self._worker is not None:
            worker = self._worker.snapshot_metrics()
            worker_depth = int(worker.get("queue_depth", 0))
            if not self._worker.running:
                degraded.append("recognition_worker_stopped")
            # INFO, bukan DEBUG: satu-satunya bukti rekognisi berjalan saat roster
            # masih kosong (belum ada track.identified). Sekali per laporan health.
            logger.info(
                "rekognisi: diproses %d, ditolak-penuh %d, basi %d, gagal %d, rata2 %.0f ms, antre %d",
                int(worker["processed"]), int(worker["rejected_full"]), int(worker["dropped_stale"]),
                int(worker["failed"]), worker["avg_recognize_ms"], int(worker["queue_depth"]),
            )
        if self._reid is not None:
            if not self._reid.worker.running:
                degraded.append("reid_worker_stopped")
            core = self._reid.coordinator.snapshot_metrics()
            rw = self._reid.worker.snapshot_metrics()
            logger.info(
                "ReID: embedding %d (gagal %d), ANON %d, cocok galeri %d, selesai %d, dicabut %d; "
                "worker %d crop/%d batch, basi %d, ditolak-penuh %d, rata2 %.0f ms/batch",
                core["embeddings"], core["embed_failed"], core["anon_groups"], core["reid_matches"],
                core["resolutions"], core["revoked"], int(rw["processed"]), int(rw["batches"]),
                int(rw["dropped_stale"]), int(rw["rejected_full"]), rw["avg_batch_ms"],
            )
        shared = self._shared_detector
        if shared is not None:
            d = shared.metrics.as_dict()
            logger.info(
                "detector bersama: %d kamera, %d gambar dalam %d panggilan (rata2 %.2f/panggilan, maks %d), "
                "%.0f ms/gambar", shared.active_cameras, int(d["images"]), int(d["batches"]),
                d["mean_batch"], int(d["largest_batch"]), d["ms_per_image"],
            )
        api_metrics = self.api.metrics
        drop_rate = _drop_rate(api_metrics)

        self.emit_event(
            events.engine_health(
                now,
                models_loaded=models_loaded,
                queue_depth=int(metrics.get("queue_depth", 0.0)) + worker_depth,
                drop_rate=drop_rate,
                cameras=states,
                degraded_components=sorted(set(degraded)) or None,
                outbox_depth=int(api_metrics.get("outbox_depth", 0)),
                disk_free_mb=self._disk_free_mb(),
                camera_metrics={
                    camera.spec.camera_id: m
                    for camera in cameras
                    for m in [camera.metrics()] if m
                } or None,
            )
        )

    def _disk_free_mb(self) -> Optional[float]:
        """Ruang kosong di disk outbox (E10). None bila outbox di memori."""
        if not self.options.outbox_path:
            return None
        import shutil
        try:
            folder = os.path.dirname(os.path.abspath(self.options.outbox_path))
            return round(shutil.disk_usage(folder).free / (1024 * 1024), 1)
        except OSError:
            return None

    # -- inspection -------------------------------------------------------

    @property
    def cameras(self) -> Dict[str, CameraSupervisor]:
        with self._state_lock:
            return dict(self._cameras)

    def wait_until_idle(self, timeout: float = 30.0) -> bool:
        """For tests and finite sources: every camera has run out of frames."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._state_lock:
                cameras = list(self._cameras.values())
            if cameras and not any(camera.alive for camera in cameras):
                return True
            time.sleep(0.05)
        return False


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _specs_from(cameras: Sequence[Dict[str, Any]]) -> List[CameraSpec]:
    specs = []
    for entry in cameras:
        camera_id = entry.get("camera_id")
        uri = entry.get("uri")
        if not camera_id or not uri:
            raise ValueError("tiap kamera butuh `camera_id` dan `uri`")
        region = entry.get("door_region")
        if region is not None:
            values = [float(v) for v in region]
            if len(values) != 4 or not all(0.0 <= v <= 1.0 for v in values):
                # Refused here rather than at first use: a region in pixels
                # would silently label every box `interior`, and every gap would
                # then look like a tracking failure rather than a departure.
                raise ValueError(
                    f"door_region kamera `{camera_id}` harus empat angka "
                    f"ternormalisasi 0-1 (ENGINE_PROTOCOL.md §3.2)"
                )
            region = values
        specs.append(
            CameraSpec(
                camera_id=str(camera_id),
                uri=str(uri),
                door_region=region,
                enabled=bool(entry.get("enabled", True)),
            )
        )
    return specs


def _config_for(base: EngineConfig, spec: CameraSpec) -> EngineConfig:
    """This camera's config: the shared one with its own source.

    `source_type` is inferred from the URI rather than carried in the message,
    because the protocol has no field for it and should not: the backend knows
    where a camera is, not how this engine decodes it.
    """
    import dataclasses

    uri = spec.uri
    lowered = uri.lower()
    if lowered.startswith(("rtsp://", "rtsps://", "rtmp://", "http://", "https://", "udp://")):
        source_type = "video_file"          # PyAV takes both; see factory.build_source
    elif lowered == "mock":
        source_type = "mock"
    else:
        source_type = "video_file"
    return dataclasses.replace(base, source_uri=uri, source_type=source_type)


def _protocol_state(camera: CameraSupervisor) -> str:
    """The three words `engine.health` is allowed to use about a camera."""
    if camera.state == "failed":
        return "failed"
    if camera.state == "online" and camera.alive and not getattr(camera, "lag_degraded", False):
        return "online"
    return "degraded"


def _drop_rate(metrics: Dict[str, float]) -> float:
    """Share of view frames dropped. Zero when nothing has been sent yet.

    View drops are the honest thing to report here: the engine never drops a
    domain event (§6.2), so a non-zero number in this field means the dashboard
    is behind, not that anything was lost.
    """
    dropped = metrics.get("dropped_views", 0.0)
    sent = metrics.get("sent_events", 0.0)
    total = dropped + sent
    return round(dropped / total, 4) if total else 0.0


def _resolve_path(path: str) -> str:
    from pathlib import Path

    candidate = Path(path)
    if candidate.is_absolute():
        return str(candidate)
    return str(Path(__file__).resolve().parents[2] / candidate)


def _build_identity(config: EngineConfig):
    """recognizer + reference store + matcher, from `recognition.*` config."""
    from ..identity import MatrixMatcher
    from ..identity.face_onnx import build_recognizer
    from ..store.references import SqliteReferenceStore

    rec = config.recognition
    recognizer = build_recognizer(rec)
    store = SqliteReferenceStore(_resolve_path(rec.reference_db_path), rec.embedding_version)
    kwargs = {}
    if rec.match_threshold is not None:
        kwargs["threshold"] = rec.match_threshold
    if rec.match_margin is not None:
        kwargs["margin"] = rec.match_margin
    matcher = MatrixMatcher(store, **kwargs)
    return recognizer, store, matcher


def _candidate_from(image: Dict[str, Any], analyze: Callable[..., Any], candidate_cls: Any) -> Any:
    import base64

    import cv2
    import numpy as np

    image_id = str(image.get("id", "?"))
    try:
        raw = base64.b64decode(str(image.get("jpeg_b64", "")), validate=False)
        bgr = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:  # noqa: BLE001
        bgr, raw = None, b""
    if bgr is None:
        return candidate_cls(image_id=image_id, face_count=0, jpeg=raw)
    analysis = analyze(bgr)
    return candidate_cls(
        image_id=image_id,
        face_count=analysis.face_count,
        embedding=analysis.embedding,
        jpeg=raw,
        face_width=analysis.face_width,
        face_height=analysis.face_height,
        sharpness=analysis.sharpness,
        brightness=analysis.brightness,
        contrast=analysis.contrast,
        detector_confidence=analysis.detector_confidence,
        landmarks=analysis.landmarks,
        camera_id=image.get("camera_id"),
        captured_at=image.get("captured_at"),
    )


def _model_names(config: EngineConfig, recognizer_wired: bool) -> Dict[str, str]:
    """What `hello_ack` tells the backend it is talking to.

    `unset` where nothing is wired, rather than a plausible model name: the
    backend stores this next to the embeddings it will later have to decide are
    comparable (§7.3), and a name that was never loaded is worse than a blank.
    """
    return {
        "detector": config.detector.model_path,
        "embedder": (config.recognition.face_embedder_model or "custom") if recognizer_wired else "unset",
        "embedding_version": config.recognition.embedding_version if recognizer_wired else "unset",
    }
