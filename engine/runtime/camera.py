"""
One camera, end to end: frames in, protocol messages out.

This is the piece that was missing. `ingest/`, `perception/`, `pipeline/`,
`identity/`, `presence/` and `api/` were each complete and each tested, and
nothing ran them together against a real source — `fake_engine` stood in for all
of it, which is exactly what it was built to do and exactly why the gap was easy
not to notice.

## Why one supervisor per camera, and what is shared

§5.1 divides the engine into a shared inference plane and a per-camera plane,
and §2.3 adds the reason it matters: one camera dying must not end anybody
else's presence. So each camera gets its own thread, its own `VisionEngine`, its
own zone labeller, its own identity arbiter and its own presence assembler. A
crash in one is a `camera.failed` event and four cameras that never noticed.

What is shared, and therefore what needs a lock, is short: the outbox and its
sequence (one monotonic `seq` for the whole engine, §6.5), the reference matrix
(read-mostly, rebuilt when the roster changes), and the recognition scheduler —
shared *because* its per-camera quota only means something when one queue sees
every camera (§5.2).

**The arbiter is deliberately per camera.** Identity dedup in §5.3 is per camera
("two tracks must not both claim the same employee on one camera") and
cross-camera fusion is §5.4, which the plan puts at step 17. Per camera today
means no lock on the hot path; when fusion lands, this becomes one shared
arbiter and that change is where the locking question belongs — not before,
guarding something nothing is contending for yet.

## The epoch, wired all the way through

B4 made the ingest layer re-anchor its PTS→wallclock offset on every reconnect
and expose it as a number. This is where that number finally goes somewhere: on
a frame whose `stream_epoch` has moved, the supervisor first ends every open
track with `camera_lost` — the stream dropped, and §2.3 is unambiguous that
nobody went home — and then re-announces the camera with the new offset, which
is what `PtsClock.reconnect` needs to keep `at()` honest. Miss it and only the
cameras that dropped report intervals in the wrong year, which is the single
most confusing shape a bug in this system can take.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..api import events
from ..config import EngineConfig
from ..identity import IdentityArbiter, Priority, RecognitionScheduler
from ..presence.assembler import PresenceAssembler
from ..presence.binding import EngineBinding
from ..presence.zones import ZONE_INTERIOR
from ..pipeline.zoning import TrackZoner, ZonePriorityQueue
from ..ports.frame import Frame
from ..ports.tracking import Track, TrackState

logger = logging.getLogger("engine.runtime.camera")

Emit = Callable[[Dict[str, Any]], None]

# Perceptual constants. Not one of them is a company rule: how often a live
# claim is restated, how long someone may be present and nameless before that is
# worth saying out loud, and how fast overlay boxes are worth sending.
HEARTBEAT_INTERVAL_SECONDS = 30.0
UNIDENTIFIED_AFTER_SECONDS = 120.0
DEFAULT_VIEW_FPS = 10.0

# How far below the expected rate a camera may run before it is called degraded.
DEGRADED_FPS_FRACTION = 0.5


@dataclass
class CameraSpec:
    """What `set_cameras` says about one camera (ENGINE_PROTOCOL.md §3.2)."""

    camera_id: str
    uri: str
    door_region: Optional[Sequence[float]] = None
    enabled: bool = True

    def same_stream_as(self, other: "CameraSpec") -> bool:
        """Whether reconciliation can leave this camera running untouched.

        `door_region` deliberately does not count: it is a label applied to
        boxes, so it can be swapped on a running camera without reopening
        anything. The URI cannot.
        """
        return self.uri == other.uri and self.enabled == other.enabled


@dataclass
class CameraStats:
    frames: int = 0
    epochs: int = 0
    last_pts: float = 0.0
    started_wallclock: float = 0.0
    measured_fps: float = 0.0
    state: str = "starting"
    error: Optional[str] = None
    attempts_by_uuid: Dict[str, int] = field(default_factory=dict)
    evidence_by_uuid: Dict[str, int] = field(default_factory=dict)


class CameraSupervisor:
    """Runs one camera's pipeline on its own thread and emits its messages."""

    def __init__(
        self,
        spec: CameraSpec,
        config: EngineConfig,
        emit_event: Emit,
        emit_view: Emit,
        scheduler: Optional[RecognitionScheduler] = None,
        matcher: Any = None,
        recognize: Optional[Callable[[Track, Frame], Any]] = None,
        view_fps: float = DEFAULT_VIEW_FPS,
        heartbeat_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
        unidentified_after_seconds: float = UNIDENTIFIED_AFTER_SECONDS,
        max_frames: Optional[int] = None,
    ) -> None:
        self.spec = spec
        self._config = config
        self._emit_event = emit_event
        self._emit_view = emit_view
        self._scheduler = scheduler
        self._matcher = matcher
        self._recognize = recognize
        self._view_interval = (1.0 / view_fps) if view_fps > 0 else None
        self._heartbeat_seconds = heartbeat_seconds
        self._unidentified_after = unidentified_after_seconds
        self._max_frames = max_frames

        self.stats = CameraStats()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

        self._engine: Any = None
        self._source: Any = None
        self._zoner: Optional[TrackZoner] = None
        self._queue: Optional[ZonePriorityQueue] = None
        self._binding: Optional[EngineBinding] = None
        self._assembler: Optional[PresenceAssembler] = None

        self._epoch: Optional[int] = None
        self._last_view_pts: float = -1e9
        self._last_heartbeat: Dict[str, float] = {}
        self._track_born_pts: Dict[str, float] = {}
        self._unidentified_reported: set = set()
        self._live: Dict[str, Dict[str, Any]] = {}

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name=f"camera-{self.spec.camera_id}", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def state(self) -> str:
        return self.stats.state

    def set_door_region(self, region: Optional[Sequence[float]]) -> None:
        """Applied to a running camera: a zone is a label, not a stream."""
        self.spec = CameraSpec(
            self.spec.camera_id, self.spec.uri, region, self.spec.enabled
        )
        # One labeller object, handed to both the frame loop and the assembler
        # when this camera was built, so setting the region once moves both.
        if self._zoner is not None:
            self._zoner.labeller.set_region(self.spec.camera_id, region)

    # -- the loop ---------------------------------------------------------

    def _run(self) -> None:
        camera_id = self.spec.camera_id
        try:
            self._build()
        except Exception as error:  # noqa: BLE001 — reported, not swallowed
            self.stats.state = "failed"
            self.stats.error = repr(error)
            logger.exception("[%s] gagal dibuka", camera_id)
            # §2.3: a camera that never opened is a camera problem, and the
            # backend has to hear it as one rather than infer it from silence.
            self._emit_event(
                events.camera_failed(
                    camera_id, time.time(), reason=_failure_reason(error),
                    retry_in_seconds=5.0,
                )
            )
            return

        self.stats.state = "online"
        self.stats.started_wallclock = time.time()

        try:
            while not self._stop.is_set():
                frame, tracks = self._engine.step()
                if frame is None:
                    break
                self._on_frame(frame, tracks)
                if self._max_frames is not None and self.stats.frames >= self._max_frames:
                    break
        except Exception as error:  # noqa: BLE001
            self.stats.state = "failed"
            self.stats.error = repr(error)
            logger.exception("[%s] berhenti karena kesalahan", camera_id)
            self._close_open_tracks(reason="camera_lost")
            self._emit_event(
                events.camera_failed(
                    camera_id, time.time(), reason=_failure_reason(error),
                    retry_in_seconds=5.0,
                )
            )
            return
        finally:
            self._shutdown()

    def _build(self) -> None:
        from .. import factory

        camera_id = self.spec.camera_id
        config = self._config

        self._zoner = TrackZoner(
            door_regions=(
                {camera_id: self.spec.door_region} if self.spec.door_region else {}
            ),
            edge_margin=config.zones.edge_margin,
        )

        self._assembler = PresenceAssembler(
            emit=self._emit_event, zones=self._zoner.labeller
        )
        self._binding = EngineBinding(
            arbiter=IdentityArbiter(matcher=self._matcher or _empty_matcher()),
            assembler=self._assembler,
            scheduler=self._scheduler,
            recognize=self._recognize,
        )

        if self._scheduler is not None:
            self._queue = ZonePriorityQueue(
                scheduler=self._scheduler,
                zoner=self._zoner,
                max_requests_per_frame=config.recognition.max_requests_per_frame,
            )
            # Consumer and key together, from the same object — see UUIDS in
            # pipeline/zoning.py for what happens when they come apart.
            self._queue.set_consumer(self._count_attempt)

        # Local recordings need a wall-clock gate: otherwise a fast GPU can
        # report PTS 30 while the direct player is still showing second 10.
        # Network sources already arrive in realtime; benchmark pacing remains
        # independently controlled by engine.bench.
        wrap_source = None
        if config.source_type == "video_file":
            lowered_uri = str(config.source_uri).lower()
            is_network = lowered_uri.startswith(
                ("rtsp://", "rtsps://", "rtmp://", "http://", "https://", "udp://")
            )
            if not is_network:
                from ..ingest import PlaybackSource

                wrap_source = lambda inner, _fps: PlaybackSource(inner)

        engine, source, source_fps = factory.build_engine(
            config,
            source_id=camera_id,
            max_frames=self._max_frames,
            wrap_source=wrap_source,
        )
        engine._zoner = self._zoner
        engine._recognition_queue = self._queue
        engine.add_listener(self._binding)

        self._engine = engine
        self._source = source
        self.stats.measured_fps = source_fps
        engine.start()

        self._announce(source_fps, wallclock=self._offset_of(source))

    def _announce(self, fps: float, wallclock: float) -> None:
        """`camera.online` carries the offset the stream was actually anchored with."""
        self._assembler.camera_online(
            self.spec.camera_id,
            wallclock_now=wallclock,
            fps=fps,
            door_region=self.spec.door_region,
        )

    def _offset_of(self, source: Any) -> float:
        """
        The PTS→wallclock offset, asked of the source rather than sampled here.

        `time.time()` at this moment is only right for a stream whose first frame
        arrived at this moment. After a reconnect it is not, and B4 exposed
        `wallclock_offset` precisely so this layer does not have to guess
        (ARCHITECTURE.md §6.6, ENGINE_PROTOCOL.md §4.5).
        """
        timeline = getattr(source, "timeline", None)
        offset = getattr(timeline, "wallclock_offset", None) if timeline else None
        return float(offset) if offset is not None else time.time()

    def _on_frame(self, frame: Frame, tracks: Sequence[Track]) -> None:
        self.stats.frames += 1
        pts = frame.metadata.pts
        if pts is None:
            return
        self.stats.last_pts = pts

        epoch = frame.metadata.stream_epoch
        if self._epoch is None:
            self._epoch = epoch
        elif epoch != self._epoch:
            self._on_reconnect(frame, epoch)

        self._remember_live(frame, tracks, pts)
        self._heartbeats(pts)
        self._unidentified(pts)
        self._maybe_view(frame, tracks, pts)

    def _on_reconnect(self, frame: Frame, epoch: int) -> None:
        """A new epoch is a new timeline, and the old tracks did not walk out."""
        camera_id = self.spec.camera_id
        self.stats.epochs += 1
        logger.warning(
            "[%s] stream epoch %s -> %s: menutup track dengan camera_lost lalu "
            "menetapkan ulang offset",
            camera_id, self._epoch, epoch,
        )
        # camera_failed ends every open track on this camera with `camera_lost`
        # (§2.3). It happened: the stream dropped, even if it came straight back.
        self._assembler.camera_failed(
            camera_id, wallclock_now=time.time(),
            pts=self.stats.last_pts, reason="stream_reconnected", retry_in_seconds=0.0,
        )
        self._live.clear()
        self._last_heartbeat.clear()
        self._track_born_pts.clear()
        self._unidentified_reported.clear()
        self._epoch = epoch
        self._announce(
            self.stats.measured_fps,
            wallclock=frame.metadata.pts_wallclock_offset or time.time(),
        )

    def _remember_live(self, frame: Frame, tracks: Sequence[Track], pts: float) -> None:
        seen = set()
        for track in tracks:
            if track.state not in (TrackState.NEW, TrackState.TRACKED):
                continue
            uuid = track.attributes.get("track_uuid")
            if not uuid:
                continue
            seen.add(uuid)
            self._track_born_pts.setdefault(uuid, pts)
            identity = track.attributes.get("identity_state")
            self._live[uuid] = {
                "track_uuid": uuid,
                "camera_id": self.spec.camera_id,
                "stream_epoch": frame.metadata.stream_epoch,
                "identity_state": identity,
                "person_id": getattr(identity, "person_id", None),
                "identity_source": getattr(identity, "identity_source", None),
                "since_pts": self._track_born_pts[uuid],
                "zone": track.attributes.get("zone", ZONE_INTERIOR),
                "bbox": _normalized(track, frame),
            }
        for uuid in [u for u in self._live if u not in seen]:
            self._live.pop(uuid, None)
            self._track_born_pts.pop(uuid, None)
            self._last_heartbeat.pop(uuid, None)
            self._unidentified_reported.discard(uuid)

    def _heartbeats(self, pts: float) -> None:
        """Periodic proof a claim is still standing, and how it is being held.

        §5.3: an identity freshly read off a face and one the tracker has been
        carrying for ten minutes are not equally reliable, and the backend can
        only treat them differently if it is told which it has.
        """
        clock = self._assembler.clock_for(self.spec.camera_id)
        for uuid, entry in self._live.items():
            if entry["person_id"] is None:
                continue
            last = self._last_heartbeat.get(uuid)
            if last is not None and (pts - last) < self._heartbeat_seconds:
                continue
            self._last_heartbeat[uuid] = pts
            identity = self._identity_of(uuid)
            self._emit_event(
                events.track_heartbeat(
                    clock, uuid, pts=pts, person_id=entry["person_id"],
                    identity_source=entry["identity_source"] or "tracking",
                    confidence=getattr(identity, "confidence", 0.0),
                )
            )

    def _unidentified(self, pts: float) -> None:
        """§11.1: somebody present and nameless for a long time is a signal.

        Not noise, and not an alert either — the engine reports and stops there.
        At a corner camera the likeliest explanation is an employee facing away,
        and probably the one the backend currently believes is on a break.
        """
        for uuid, entry in self._live.items():
            if entry["person_id"] is not None or uuid in self._unidentified_reported:
                continue
            duration = pts - self._track_born_pts.get(uuid, pts)
            if duration < self._unidentified_after:
                continue
            self._unidentified_reported.add(uuid)
            attempts = self.stats.attempts_by_uuid.get(uuid, 0)
            self._emit_event(
                events.person_unidentified_present(
                    self.spec.camera_id, time.time(), uuid,
                    duration_seconds=round(duration, 3), attempts=attempts,
                    reason=(
                        "no_face_detected"
                        if self.stats.evidence_by_uuid.get(uuid, 0) == 0
                        else "below_threshold"
                    ),
                )
            )

    def _maybe_view(self, frame: Frame, tracks: Sequence[Track], pts: float) -> None:
        """Overlay boxes, throttled in PTS rather than wall time.

        Throttling in PTS matters more than it looks: a throughput benchmark
        replays an hour of video in a minute, and a wall-clock throttle would
        send one frame per real second of a run that covers thousands. Best
        effort either way — §6.2 says the engine drops these rather than wait.
        """
        if self._view_interval is None:
            return
        if (pts - self._last_view_pts) < self._view_interval:
            return
        self._last_view_pts = pts

        boxes = []
        for track in tracks:
            uuid = track.attributes.get("track_uuid")
            if not uuid:
                continue
            identity = track.attributes.get("identity_state")
            box: Dict[str, Any] = {
                "track_uuid": uuid,
                "bbox": list(_normalized(track, frame)),
                "person_id": getattr(identity, "person_id", None),
                # Relative media time lets a direct MP4 player select the box
                # belonging to video.currentTime, even when inference is faster
                # than realtime.
                "session_elapsed": max(
                    0.0, pts - self._track_born_pts.get(uuid, pts)
                ),
            }
            source = getattr(identity, "identity_source", None)
            if source:
                box["identity_source"] = source
            boxes.append(box)

        # Empty frames are significant: without them the browser would keep the
        # previous person's box over later frames that contain nobody.
        clock = self._assembler.clock_for(self.spec.camera_id)
        self._emit_view(events.view_frame(clock, pts, boxes))

    # -- recognition bookkeeping -----------------------------------------

    def _count_attempt(self, request: Any) -> None:
        """Wraps the binding so `attempts` in §4.3 is a real count, not a guess."""
        uuid = getattr(request, "track_uuid", "")
        self.stats.attempts_by_uuid[uuid] = self.stats.attempts_by_uuid.get(uuid, 0) + 1
        before = self._binding.metrics.evidence_submitted
        self._binding(request)
        if self._binding.metrics.evidence_submitted > before:
            self.stats.evidence_by_uuid[uuid] = (
                self.stats.evidence_by_uuid.get(uuid, 0) + 1
            )

    def _identity_of(self, uuid: str) -> Any:
        entry = self._live.get(uuid) or {}
        return entry.get("identity_state")

    # -- shutdown ---------------------------------------------------------

    def _shutdown(self) -> None:
        if self.stats.state != "failed":
            self.stats.state = "stopped"
        self._close_open_tracks(reason="engine_shutdown")
        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception:  # noqa: BLE001
                logger.exception("[%s] gagal berhenti rapi", self.spec.camera_id)

    def _close_open_tracks(self, reason: str) -> None:
        """Nobody is left open. An interval with no end is a presence that
        never finished, and the backend would carry it forward for ever."""
        if self._assembler is None:
            return
        for uuid, entry in list(self._live.items()):
            try:
                self._assembler.track_ended(
                    uuid, pts=self.stats.last_pts, reason=reason,
                    zone=entry.get("zone", ZONE_INTERIOR), end_source="forced",
                )
            except Exception:  # noqa: BLE001
                logger.exception("[%s] gagal menutup %s", self.spec.camera_id, uuid)
        self._live.clear()

    # -- reporting --------------------------------------------------------

    def live_tracks(self) -> List[Dict[str, Any]]:
        """For `snapshot` (§4.5). Only the fields that message declares."""
        out = []
        for entry in self._live.values():
            item = {
                "track_uuid": entry["track_uuid"],
                "camera_id": entry["camera_id"],
                "stream_epoch": entry["stream_epoch"],
                "person_id": entry["person_id"],
                "since_pts": round(entry["since_pts"], 4),
            }
            if entry["identity_source"]:
                item["identity_source"] = entry["identity_source"]
            out.append(item)
        return out

    def clock(self) -> Optional[Any]:
        if self._assembler is None:
            return None
        try:
            return self._assembler.clock_for(self.spec.camera_id)
        except KeyError:
            return None

    def health(self) -> Dict[str, Any]:
        binding = self._binding.health() if self._binding is not None else {}
        return {
            "camera_id": self.spec.camera_id,
            "state": self.stats.state,
            "frames": self.stats.frames,
            "epochs": self.stats.epochs,
            "last_pts": round(self.stats.last_pts, 3),
            "error": self.stats.error,
            **binding,
        }


def _empty_matcher() -> Any:
    """A real matcher over an empty roster, rather than a stand-in arbiter.

    The first version of this file substituted a `_NullArbiter` whose
    `identity_of` always answered `None`. That answer is also how
    `presence/binding.py` asks "have I seen this track before", so every frame
    looked like a brand-new track and the engine emitted one `track.started` per
    frame per person — forty of them in a forty-frame smoke run. A stand-in that
    lies about one question will be asked a different one.

    The real arbiter over an empty store answers both questions honestly: the
    track is known, and nobody matches — `rejected_because: empty_roster`, which
    is the literal truth until `set_roster` brings references. `engine.health`
    still reports `models_loaded: false`, so nothing here hides the fact that
    this engine cannot name anyone yet.
    """
    from ..identity import InMemoryReferenceStore, MatrixMatcher

    matcher = MatrixMatcher(InMemoryReferenceStore({}, embedding_version="unset"))
    matcher.rebuild()
    return matcher


def _normalized(track: Track, frame: Frame) -> Sequence[float]:
    width = float(frame.metadata.width or 0) or float(frame.width or 1)
    height = float(frame.metadata.height or 0) or float(frame.height or 1)
    box = track.bbox
    return (
        max(0.0, min(1.0, box.x1 / width)),
        max(0.0, min(1.0, box.y1 / height)),
        max(0.0, min(1.0, box.x2 / width)),
        max(0.0, min(1.0, box.y2 / height)),
    )


def _failure_reason(error: BaseException) -> str:
    """A reason code the backend can act on, with the detail in the log.

    The vocabulary is small on purpose: `camera.failed` exists so the backend
    knows nobody went home (§2.3), not so it can diagnose FFmpeg.
    """
    text = repr(error).lower()
    if "refused" in text or "connection" in text:
        return "connection_refused"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "not found" in text or "no such file" in text:
        return "not_found"
    return "open_failed"
