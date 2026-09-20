"""
Acceptance tests for the integration step: the real engine, on a socket, with N
cameras.

These are the tests nothing else could cover. `test_api.py` proves the socket,
`test_presence.py` proves the assembler, `test_binding.py` proves the binding,
and every one of them is satisfied by a layer that is never actually run by
anything. What was missing is the claim the milestone is written in terms of —
that a real pipeline produces protocol-conformant messages for several cameras
at once, and keeps producing the right ones when a stream drops.

What is deliberately NOT here: anything importing `backend/`. §6.8 forbids it
and a test that broke the rule to check the rule would be a poor trade. The
cross-track check lives in `scripts/integration_smoke.py`, which belongs to
neither side and drives the backend's real client against this runtime.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from typing import Any, Dict, List, Optional

import numpy as np
import pytest

from contracts.validator import ConformanceChecker, SchemaValidator
from engine.config import load_config
from engine.identity import Evidence, InMemoryReferenceStore, MatrixMatcher
from engine.ports.frame import Frame, FrameMetadata
from engine.runtime import EngineRuntime, RuntimeOptions
from engine.runtime.camera import CameraSpec, CameraSupervisor

DOOR = [0.0, 0.0, 0.40, 0.40]


def _config(**changes: Any):
    base = dataclasses.replace(
        load_config(), source_type="mock", auto_warmup=False, strict_mode=True
    )
    return dataclasses.replace(base, **changes) if changes else base


def _collector(numbered: bool = True):
    """Stands in for the outbox. `numbered=False` for the view channel.

    The view channel has no `seq` and the schema enforces it (§5): those
    messages are droppable by design, and a sequence number on a stream with
    holes in it would be an invitation to treat the holes as data loss.
    """
    messages: List[Dict[str, Any]] = []
    lock = threading.Lock()

    def emit(message: Dict[str, Any]) -> Dict[str, Any]:
        with lock:
            message = dict(message)
            if numbered:
                message.setdefault("seq", len(messages) + 1)
            messages.append(message)
            return message

    return messages, emit


def _run_camera(spec: CameraSpec, frames: int = 40, **kwargs: Any):
    messages, emit = _collector()
    views, emit_view = _collector(numbered=False)
    camera = CameraSupervisor(
        spec=spec, config=_config(), emit_event=emit, emit_view=emit_view,
        max_frames=frames, **kwargs,
    )
    camera.start()
    deadline = time.time() + 30
    while camera.alive and time.time() < deadline:
        time.sleep(0.02)
    camera.stop()
    return camera, messages, views


def _types(messages: List[Dict[str, Any]]) -> List[str]:
    return [message["type"] for message in messages]


# --------------------------------------------------------------------------
# One camera, the whole way through
# --------------------------------------------------------------------------

def test_a_camera_announces_itself_and_closes_what_it_opened():
    camera, messages, _ = _run_camera(CameraSpec("r1", "mock", DOOR))

    kinds = _types(messages)
    assert kinds[0] == "camera.online"
    assert kinds.count("track.started") == kinds.count("track.ended") >= 1
    assert camera.stats.frames > 0


def test_a_track_alive_at_shutdown_is_ended_rather_than_left_open():
    """
    An interval with no end is a presence that never finished, and the backend
    carries it forward for ever — the person is still at work at midnight.
    """
    _, messages, _ = _run_camera(CameraSpec("r1", "mock", DOOR), frames=20)
    ended = [m for m in messages if m["type"] == "track.ended"]
    assert ended, "the run ended with a live track and said nothing about it"
    assert ended[-1]["reason"] == "engine_shutdown"
    assert "exit_zone" in ended[-1]


def test_the_offset_comes_from_the_stream_not_from_the_wall_clock():
    """
    B4 exposed `wallclock_offset` so this layer would stop sampling its own
    clock. On a file the two are indistinguishable; after a reconnect they are
    not, and only the camera that dropped reports the wrong year.
    """
    class FakeTimeline:
        wallclock_offset = 1_700_000_000.0

    class FakeSource:
        timeline = FakeTimeline()

    camera = CameraSupervisor(
        spec=CameraSpec("r1", "mock"), config=_config(),
        emit_event=lambda m: m, emit_view=lambda m: m,
    )
    assert camera._offset_of(FakeSource()) == pytest.approx(1_700_000_000.0)
    # A source with no timeline (the mock) may fall back, but only then.
    assert camera._offset_of(object()) > 1_600_000_000.0


def test_boxes_on_the_view_channel_are_normalized():
    _, _, views = _run_camera(CameraSpec("r1", "mock", DOOR), frames=30, view_fps=1000.0)
    assert views, "no view frames were emitted"
    for message in views:
        for box in message["boxes"]:
            assert all(0.0 <= value <= 1.0 for value in box["bbox"]), box


def test_a_camera_that_cannot_open_says_so_instead_of_going_quiet():
    """
    §2.3: silence from a camera is indistinguishable from an empty room, and the
    backend would eventually mark a room full of people as having gone home.
    """
    config = dataclasses.replace(_config(), source_type="video_file")
    messages, emit = _collector()
    camera = CameraSupervisor(
        spec=CameraSpec("r9", "/definitely/not/a/file.mp4"),
        config=config, emit_event=emit, emit_view=lambda m: m,
    )
    camera.start()
    deadline = time.time() + 20
    while camera.alive and time.time() < deadline:
        time.sleep(0.02)
    camera.stop()

    failed = [m for m in messages if m["type"] == "camera.failed"]
    assert failed, f"expected camera.failed, got {_types(messages)}"
    assert failed[0]["reason"] in {"not_found", "open_failed", "connection_refused"}
    assert camera.state == "failed"


# --------------------------------------------------------------------------
# The reconnect, which is where the epoch earns its keep
# --------------------------------------------------------------------------

class _ReconnectingSource:
    """A mock source whose stream epoch bumps halfway through."""

    def __init__(self, frames: int = 40, bump_at: int = 20) -> None:
        self._frames = frames
        self._bump_at = bump_at
        self._count = 0
        self.is_running = True
        self.fps = 10.0
        self.resolution = (320, 240)
        self.total_frames = frames

    def start(self) -> None:
        self.is_running = True

    def stop(self) -> None:
        self.is_running = False

    def read(self):
        if self._count >= self._frames:
            self.is_running = False
            return None
        self._count += 1
        epoch = 0 if self._count <= self._bump_at else 1
        # After the reconnect PTS restarts from its own base, exactly as RTP
        # does — which is the whole reason durations must not cross an epoch.
        pts = (self._count - 1) / 10.0 if epoch == 0 else (self._count - self._bump_at - 1) / 10.0
        return Frame(
            image=np.zeros((240, 320, 3), dtype=np.uint8),
            metadata=FrameMetadata(
                frame_id=self._count, source_id="r1", fps=10.0, width=320, height=240,
                pts=pts, pts_source="container", stream_epoch=epoch,
                wallclock=1_700_000_000.0 + pts,
                pts_wallclock_offset=1_700_000_000.0 + (0.0 if epoch == 0 else 100.0),
            ),
        )


def test_a_reconnect_ends_the_open_tracks_and_re_announces_the_camera(monkeypatch):
    """
    The stream dropped. Nobody went home (§2.3), the PTS timeline restarted, and
    a duration measured across that boundary is not a wrong number — it is a
    meaningless one that prints perfectly.
    """
    from engine import factory

    source = _ReconnectingSource()
    real_build = factory.build_engine

    def build(config, **kwargs):
        engine, _, fps = real_build(config, **kwargs)
        engine._source = source
        return engine, source, fps

    monkeypatch.setattr("engine.factory.build_engine", build)

    messages, emit = _collector()
    camera = CameraSupervisor(
        spec=CameraSpec("r1", "mock", DOOR), config=_config(),
        emit_event=emit, emit_view=lambda m: m,
    )
    camera.start()
    deadline = time.time() + 30
    while camera.alive and time.time() < deadline:
        time.sleep(0.02)
    camera.stop()

    kinds = _types(messages)
    assert kinds.count("camera.online") == 2, f"no re-announcement: {kinds}"
    assert "camera.failed" in kinds, "the drop itself was never reported"

    lost = [m for m in messages if m["type"] == "track.ended" and m["reason"] == "camera_lost"]
    assert lost, "open tracks survived a reconnect as if nothing happened"

    online = [m for m in messages if m["type"] == "camera.online"]
    assert online[1]["pts_wallclock_offset"] != online[0]["pts_wallclock_offset"], (
        "the offset was not re-established, so every timestamp after the "
        "reconnect is wrong by the difference of two random bases (§6.6)"
    )
    assert online[1]["stream_epoch"] == online[0]["stream_epoch"] + 1
    assert camera.stats.epochs == 1


# --------------------------------------------------------------------------
# Declarative reconciliation
# --------------------------------------------------------------------------

def _runtime(**options: Any) -> EngineRuntime:
    return EngineRuntime(
        config=_config(),
        options=RuntimeOptions(tcp=("127.0.0.1", 0), max_frames=200, **options),
    )


def test_set_cameras_opens_closes_and_leaves_alone():
    runtime = _runtime()
    try:
        runtime._reconcile({
            "r1": CameraSpec("r1", "mock", DOOR),
            "r2": CameraSpec("r2", "mock", DOOR),
        })
        assert set(runtime.cameras) == {"r1", "r2"}
        first = runtime.cameras["r1"]

        # r1 unchanged, r2 gone, r3 new: the untouched camera must be the same
        # object, because reopening it would end everyone's presence in that
        # room for no reason at all.
        runtime._reconcile({
            "r1": CameraSpec("r1", "mock", DOOR),
            "r3": CameraSpec("r3", "mock", DOOR),
        })
        assert set(runtime.cameras) == {"r1", "r3"}
        assert runtime.cameras["r1"] is first
    finally:
        runtime.close()


def test_a_new_door_region_does_not_reopen_the_stream():
    """A zone is a label applied to boxes. Dropping the stream to change a label
    would turn a configuration tweak into a room full of false gaps."""
    runtime = _runtime()
    try:
        runtime._reconcile({"r1": CameraSpec("r1", "mock", DOOR)})
        camera = runtime.cameras["r1"]
        runtime._reconcile({"r1": CameraSpec("r1", "mock", [0.5, 0.5, 0.9, 0.9])})
        assert runtime.cameras["r1"] is camera
        assert list(camera.spec.door_region) == [0.5, 0.5, 0.9, 0.9]
    finally:
        runtime.close()


def test_a_changed_uri_does_reopen_it():
    runtime = _runtime()
    try:
        runtime._reconcile({"r1": CameraSpec("r1", "mock")})
        first = runtime.cameras["r1"]
        runtime._reconcile({"r1": CameraSpec("r1", "mock2")})
        assert runtime.cameras["r1"] is not first
    finally:
        runtime.close()


def test_a_door_region_in_pixels_is_refused_with_a_reason():
    runtime = _runtime()
    try:
        reply = runtime._on_set_cameras({
            "type": "set_cameras", "v": 1, "ts": "x",
            "cameras": [{"camera_id": "r1", "uri": "mock",
                         "door_region": [100, 50, 400, 300]}],
        })
        assert reply is not None and reply["accepted"] is False
        assert "ternormalisasi" in reply["reason"]
        assert not runtime.cameras, "a refused command must not half-apply"
    finally:
        runtime.close()


def test_set_cameras_is_acked_immediately_not_when_the_stream_opens():
    """Opening RTSP can take five seconds and can fail. A backend that waited
    would hang at startup (§6.3)."""
    runtime = _runtime()
    try:
        started = time.time()
        reply = runtime._on_set_cameras({
            "type": "set_cameras", "v": 1, "ts": "x",
            "cameras": [{"camera_id": c, "uri": "mock"} for c in ("r1", "r2", "r3")],
        })
        assert reply is None, "None means the api writes the default accepted ack"
        assert time.time() - started < 0.5
    finally:
        runtime.close()


def test_enrollment_is_declined_out_loud_while_there_is_no_embedder():
    """Accepting an enrolment and storing nothing is §9 item 9 at its most
    expensive: the UI says done and the person is unrecognisable for months."""
    runtime = _runtime()
    try:
        reply = runtime._on_enroll({"type": "enroll", "request_id": "e-1"})
        assert reply["accepted"] is False
        assert "embedder" in reply["reason"]
    finally:
        runtime.close()


# --------------------------------------------------------------------------
# The output the whole system exists for
# --------------------------------------------------------------------------

def test_a_recognised_person_produces_a_conformant_presence_interval():
    """
    §4.2's main output, from the real pipeline rather than from `fake_engine`.

    The recognizer here is a stub — there is no embedder in this environment and
    §10's models are a later step — but everything after it is the real thing:
    the arbiter confirms from spread-out evidence, the assembler builds the
    interval, and the message is checked against the frozen schema rather than
    against my idea of it.
    """
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    store = InMemoryReferenceStore({"4471": [vector]}, embedding_version="stub-v1")
    matcher = MatrixMatcher(store)
    matcher.rebuild()

    # Each observation is a different look at the same person, not the same
    # array handed over three times: `EvidenceWindow` rejects anything more than
    # 0.985 similar to what it already holds, and it is right to — two frames of
    # somebody sitting still are one observation counted twice (§9 item 3). A
    # stub that ignored that would confirm an identity the real pipeline never
    # would.
    rng = np.random.default_rng(20260920)

    def recognize(track, frame):
        # sigma is not a free parameter: at 0.25 the noise norm across 512
        # dimensions swamps the signal and cosine similarity to the reference
        # falls to 0.15, well under any sane threshold — the stub would then be
        # testing that an unrecognisable face is not recognised. At 0.02 it sits
        # at 0.92 to the reference and 0.86 between observations: a match, and
        # not a duplicate.
        noisy = vector + rng.normal(0.0, 0.02, size=512).astype(np.float32)
        noisy /= np.linalg.norm(noisy)
        return Evidence(
            embedding=noisy, pts=frame.metadata.pts or 0.0,
            quality=0.9, embedding_version="stub-v1",
        )

    # The retry interval is left at its default on purpose. Forcing it down to
    # 50 ms — the first attempt at making this test quick — produced five pieces
    # of evidence spanning 0.27 s, and the arbiter correctly refused to confirm
    # anything: §5.3 requires evidence spread over at least half a second,
    # because two frames of somebody sitting still are one observation counted
    # twice (§9 item 3). The safeguard was working and the test was wrong. So
    # the run is given enough frames for real spread instead.
    config = dataclasses.replace(
        _config(), recognition=dataclasses.replace(
            _config().recognition, enabled=True, max_requests_per_frame=2,
        ),
    )
    messages, emit = _collector()
    from engine.identity import RecognitionScheduler

    camera = CameraSupervisor(
        spec=CameraSpec("r1", "mock", DOOR), config=config,
        emit_event=emit, emit_view=lambda m: m,
        scheduler=RecognitionScheduler(max_age_seconds=10.0),
        matcher=matcher, recognize=recognize, max_frames=240,
    )
    camera.start()
    deadline = time.time() + 40
    while camera.alive and time.time() < deadline:
        time.sleep(0.02)
    camera.stop()

    kinds = _types(messages)
    assert "track.identified" in kinds, f"nobody was ever identified: {set(kinds)}"
    intervals = [m for m in messages if m["type"] == "presence.interval"]
    assert intervals, f"no presence.interval was produced: {set(kinds)}"

    interval = intervals[0]
    assert interval["person_id"] == "4471"
    assert interval["camera_id"] == "r1"
    # §4.4: the interval starts when the track was born, not when the face was
    # read. Eight seconds per event is two minutes a day out of thirty.
    identified = [m for m in messages if m["type"] == "track.identified"][0]
    assert interval["start_pts"] <= identified["pts"]
    assert interval["start_pts"] == pytest.approx(identified["track_started_pts"])

    validator = SchemaValidator()
    issues = validator.validate_message(interval, expected_channel="events")
    assert not issues, issues


def test_the_whole_emitted_stream_passes_the_conformance_checker():
    """
    The check that matters at M3: not "does my code do what I meant", but "would
    this stream be accepted from any engine at all". Same checker the fixtures
    from `fake_engine` go through.
    """
    messages, emit = _collector()
    views, emit_view = _collector(numbered=False)
    camera = CameraSupervisor(
        spec=CameraSpec("r1", "mock", DOOR), config=_config(),
        emit_event=emit, emit_view=emit_view, max_frames=60,
    )
    camera.start()
    deadline = time.time() + 30
    while camera.alive and time.time() < deadline:
        time.sleep(0.02)
    camera.stop()

    validator = SchemaValidator()
    for message in messages:
        assert not validator.validate_message(message, expected_channel="events"), message
    for message in views:
        assert not validator.validate_message(message, expected_channel="view"), message

    report = ConformanceChecker().check(messages)
    assert report.ok, report.errors
