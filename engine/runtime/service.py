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
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..api import EngineApi, events
from ..api.outbox import Outbox
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
    ) -> None:
        self.options = options or RuntimeOptions()
        self.config = config or load_config(self.options.config_path)
        self.api = api or EngineApi(
            outbox=Outbox(),
            engine_version=self.options.engine_version,
            models=_model_names(self.config, recognize is not None),
        )
        self._matcher = matcher
        self._recognize = recognize
        self._store = reference_store

        self._scheduler = _LockedScheduler(
            RecognitionScheduler(**self.config.recognition.scheduler_kwargs())
        )
        self._cameras: Dict[str, CameraSupervisor] = {}
        self._emit_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._stop = threading.Event()
        self._ticker: Optional[threading.Thread] = None

        self.api.on_control("set_cameras", self._on_set_cameras)
        self.api.on_control("set_roster", self._on_set_roster)
        self.api.on_control("enroll", self._on_enroll)

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
        self._stop.set()
        with self._state_lock:
            cameras = list(self._cameras.values())
            self._cameras.clear()
        for camera in cameras:
            camera.stop()
        self.api.close()

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

            for camera_id, camera in current.items():
                spec = desired.get(camera_id)
                if spec is None or not spec.enabled:
                    logger.info("[%s] tidak ada di daftar; ditutup", camera_id)
                    camera.stop()
                    self._cameras.pop(camera_id, None)
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
        )
        self._cameras[spec.camera_id] = camera
        camera.start()
        return camera

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
        """Declined, with the reason, until an embedder exists.

        Accepting an enrolment and storing nothing is the worst shape of §9 item
        9: the UI says done, the reference never exists, and the person is
        unrecognisable for months with no error anywhere.
        """
        return {
            "type": "ack", "v": 1, "ts": events.rfc3339(time.time()),
            "in_reply_to": "enroll", "accepted": False,
            "reason": (
                "engine ini berjalan tanpa embedder, jadi tidak ada yang bisa "
                "dihitung dari gambar. Enrollment aktif setelah model identitas "
                "terpasang (ARCHITECTURE.md §10, langkah 15)."
            ),
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
        api_metrics = self.api.metrics
        drop_rate = _drop_rate(api_metrics)

        self.emit_event(
            events.engine_health(
                now,
                models_loaded=models_loaded,
                queue_depth=int(metrics.get("queue_depth", 0.0)),
                drop_rate=drop_rate,
                cameras=states,
                degraded_components=sorted(set(degraded)) or None,
            )
        )

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
    if camera.state == "online" and camera.alive:
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


def _model_names(config: EngineConfig, recognizer_wired: bool) -> Dict[str, str]:
    """What `hello_ack` tells the backend it is talking to.

    `unset` where nothing is wired, rather than a plausible model name: the
    backend stores this next to the embeddings it will later have to decide are
    comparable (§7.3), and a name that was never loaded is worse than a blank.
    """
    return {
        "detector": config.detector.model_path,
        "embedder": "auraface-ir100" if recognizer_wired else "unset",
        "embedding_version": "auraface-v1" if recognizer_wired else "unset",
    }
