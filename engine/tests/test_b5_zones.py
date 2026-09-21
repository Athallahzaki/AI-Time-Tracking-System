"""
Acceptance tests for B5 — `door_region` and queue priority.

The step's completion criterion in WORKPLAN.md is one line, "a new track at the
door is served first", and it hides two claims worth separating. One is that the
order is right, which is what most of this file is about. The other is that
nothing else moved: B5 puts two new stages into the frame loop, and §16 only
works if the numbers B1 committed still mean the same thing afterwards. So the
last section asserts the loop is unchanged when the two new pieces are absent,
and that they are absent by default.

What is NOT tested here, because it belongs to Engine A and is already covered:
the zone rule itself (`tests/test_presence.py`) and the scheduler's own policy
(`tests/test_admission.py`). B5 is wiring, and wiring is tested by whether the
two ends meet.
"""

from __future__ import annotations

import numpy as np
import pytest

from engine.config import ConfigBoundaryError, RecognitionConfig, ZoneConfig, load_config
from engine.identity import IdentityState, Priority, RecognitionScheduler, TrackIdentity
from engine.pipeline.zoning import TrackZoner, ZonePriorityQueue
from engine.ports.frame import Frame, FrameMetadata
from engine.ports.geometry import BoundingBox
from engine.ports.tracking import Track, TrackState

DOOR = {"cam0": [0.60, 0.10, 0.95, 0.60]}


def _frame(width: int = 1000, height: int = 1000, pts: float = 0.0,
           camera_id: str = "cam0") -> Frame:
    return Frame(
        image=np.zeros((height, width, 3), dtype=np.uint8),
        metadata=FrameMetadata(
            frame_id=1, source_id=camera_id, fps=25.0,
            width=width, height=height, pts=pts, pts_source="container",
        ),
    )


def _track(track_id: int, box, state: TrackState = TrackState.TRACKED) -> Track:
    return Track(track_id=track_id, bbox=BoundingBox(*box), state=state)


# --------------------------------------------------------------------------
# Labelling, in pixels in and normalized out
# --------------------------------------------------------------------------

def test_a_track_in_the_door_region_is_labelled_door():
    zoner = TrackZoner(door_regions=DOOR)
    frame = _frame()
    # Centre at (0.75, 0.35): inside the region above.
    track = _track(1, (700, 250, 800, 450))
    zoner.label(frame, [track])
    assert track.attributes["zone"] == "door"


def test_a_track_in_the_middle_of_the_room_is_labelled_interior():
    zoner = TrackZoner(door_regions=DOOR)
    track = _track(1, (400, 400, 500, 600))
    zoner.label(_frame(), [track])
    assert track.attributes["zone"] == "interior"


def test_the_conversion_to_normalized_uses_the_frame_not_a_remembered_size():
    """
    The same person, the same place in the room, two resolutions. If the
    labeller cached a width, the second frame's boxes would land somewhere else
    while still producing a zone that looks like evidence (§6.7.2).
    """
    zoner = TrackZoner(door_regions=DOOR)
    big = _track(1, (1400, 500, 1600, 900))
    zoner.label(_frame(width=2000, height=2000), [big])
    small = _track(2, (700, 250, 800, 450))
    zoner.label(_frame(width=1000, height=1000), [small])
    assert big.attributes["zone"] == small.attributes["zone"] == "door"


def test_a_camera_with_no_door_region_never_reports_door():
    """
    The default leans to the suspicious side on purpose. Guessing `door` for an
    unconfigured camera marks every gap as a real departure, and that is the
    direction of error the layer above cannot detect.
    """
    zoner = TrackZoner(door_regions={})
    track = _track(1, (700, 250, 800, 450))
    zoner.label(_frame(), [track])
    assert track.attributes["zone"] == "interior"


def test_the_frame_edge_is_its_own_zone():
    """Neither `door` (no evidence of a doorway) nor `interior` (the
    disappearance has a geometric explanation)."""
    zoner = TrackZoner(door_regions=DOOR)
    track = _track(1, (0, 400, 60, 700))
    zoner.label(_frame(), [track])
    assert track.attributes["zone"] == "frame_edge"


def test_a_frame_with_no_size_leaves_the_zone_unset_rather_than_guessing():
    """
    A frame that cannot say how big it is cannot be normalized against, and
    `interior` would be a guess wearing the clothes of a measurement. Left unset,
    with a warning naming the track — the same reasoning as §9 item 9: a
    plausible default is the failure mode, not the fix.
    """
    zoner = TrackZoner(door_regions=DOOR)
    frame = Frame(
        image=np.zeros((0, 0, 3), dtype=np.uint8),
        metadata=FrameMetadata(frame_id=1, source_id="cam0", width=0, height=0,
                               pts=0.0),
    )
    track = _track(1, (700, 250, 800, 450))
    zoner.label(frame, [track])
    assert "zone" not in track.attributes


# --------------------------------------------------------------------------
# The exit zone, which has to survive the track
# --------------------------------------------------------------------------

def test_the_last_zone_is_remembered_after_the_track_is_gone():
    """
    `track.ended` must carry `exit_zone` (ENGINE_PROTOCOL.md §7) and by then the
    tracker has stopped reporting the track: there is no box left to label.
    """
    zoner = TrackZoner(door_regions=DOOR)
    track = _track(7, (400, 400, 500, 600))
    zoner.label(_frame(pts=1.0), [track])
    assert zoner.zone_of(7) == "interior"

    walking_out = _track(7, (700, 250, 800, 450))
    zoner.label(_frame(pts=2.0), [walking_out])
    assert zoner.zone_of(7) == "door", "the LAST zone is the exit zone, not the first"
    assert zoner.entry_zone_of(7) == "interior"

    zoner.forget(7)
    assert zoner.zone_of(7) == "interior", "a forgotten track falls back, not raises"


def test_the_removed_event_carries_the_exit_zone():
    """
    The whole §4.2 argument in one assertion: the layer above must be able to
    tell a track that ended at the door from one that ended mid-room, and a track
    id plus a duration cannot.
    """
    from engine.config import EngineConfig
    from engine.perception import MockDetector, MockTracker
    from engine.pipeline.engine import VisionEngine
    from engine.pipeline.events import TrackRemovedEvent

    class OneTrackThenNothing:
        """Two frames with a track at the door, then frames with none."""

        def __init__(self) -> None:
            self.calls = 0
            self.is_running = True

        def start(self) -> None:
            pass

        def stop(self) -> None:
            self.is_running = False

        def read(self):
            self.calls += 1
            if self.calls > 4:
                self.is_running = False
                return None
            return _frame(pts=float(self.calls))

    class DoorTracker:
        def __init__(self, source) -> None:
            self._source = source

        def update(self, detections, frame):
            if self._source.calls <= 2:
                return [_track(3, (700, 250, 800, 450))]
            return []

    source = OneTrackThenNothing()
    removed = []
    engine = VisionEngine(
        source=source,
        detector=MockDetector(),
        tracker=DoorTracker(source),
        config=EngineConfig(source_type="mock"),
        zoner=TrackZoner(door_regions=DOOR),
    )
    engine.add_event_handler(
        lambda event: removed.append(event)
        if isinstance(event, TrackRemovedEvent)
        else None
    )
    engine.start()
    while engine.step()[0] is not None:
        pass
    engine.stop()

    assert len(removed) == 1
    assert removed[0].exit_zone == "door"
    assert removed[0].camera_id == "cam0"


# --------------------------------------------------------------------------
# Priority: the door goes first
# --------------------------------------------------------------------------

def _pending(track_uuid: str) -> TrackIdentity:
    return TrackIdentity(track_uuid=track_uuid, state=IdentityState.PENDING)


def test_a_track_born_at_the_door_is_served_before_an_older_interior_track():
    """
    B5's completion criterion. The interior track is queued FIRST and is older,
    so arrival order and age both favour it — which is exactly the situation
    where a FIFO queue wastes the one moment a frontal face was available (§3.2).
    """
    scheduler = RecognitionScheduler(max_age_seconds=100.0)
    zoner = TrackZoner(door_regions=DOOR)
    queue = ZonePriorityQueue(scheduler, zoner, max_requests_per_frame=1)

    handed = []
    queue.set_consumer(handed.append)

    interior = _track(1, (400, 400, 500, 600))
    door = _track(2, (700, 250, 800, 450))

    frame = _frame(pts=10.0)
    zoner.label(frame, [interior, door])
    queue.step(frame, [interior, door])

    assert [r.track_uuid for r in handed] == ["cam0-t2"]
    assert handed[0].priority is Priority.DOOR_NEW


def test_nothing_is_handed_out_without_a_consumer():
    """
    There is no recognition worker until §5.2. A queue that popped into nothing
    would report requests as served and hide that no face was ever looked at.
    """
    scheduler = RecognitionScheduler(max_age_seconds=100.0)
    zoner = TrackZoner(door_regions=DOOR)
    queue = ZonePriorityQueue(scheduler, zoner)

    frame = _frame(pts=1.0)
    track = _track(1, (700, 250, 800, 450))
    zoner.label(frame, [track])
    assert queue.step(frame, [track]) == []
    assert queue.metrics(1.0)["queue_depth"] == 1.0
    assert queue.metrics(1.0)["has_consumer"] is False


def test_a_source_without_pts_does_not_run_the_queue():
    """
    Request ages are measured in PTS (§6.6). A mock source has no timeline, and
    timing a queue against a fabricated clock produces queue numbers that
    describe the fabrication.
    """
    scheduler = RecognitionScheduler()
    zoner = TrackZoner(door_regions=DOOR)
    queue = ZonePriorityQueue(scheduler, zoner)

    frame = Frame(
        image=np.zeros((100, 100, 3), dtype=np.uint8),
        metadata=FrameMetadata(frame_id=1, source_id="cam0", width=100, height=100),
    )
    track = _track(1, (60, 10, 80, 50))
    assert queue.step(frame, [track]) == []
    assert queue.metrics(0.0)["queue_depth"] == 0.0


def test_a_lost_track_is_not_queued():
    scheduler = RecognitionScheduler(max_age_seconds=100.0)
    zoner = TrackZoner(door_regions=DOOR)
    queue = ZonePriorityQueue(scheduler, zoner)
    frame = _frame(pts=1.0)
    lost = _track(1, (700, 250, 800, 450), state=TrackState.LOST)
    zoner.label(frame, [lost])
    queue.step(frame, [lost])
    assert queue.metrics(1.0)["queue_depth"] == 0.0


def test_a_removed_track_is_dropped_from_the_queue():
    """
    Otherwise the in-flight set and the per-camera quota fill up with tracks that
    no longer exist, and the camera goes quietly blind — no error, just fewer
    recognitions per second than the quota promises.
    """
    scheduler = RecognitionScheduler(max_age_seconds=100.0)
    zoner = TrackZoner(door_regions=DOOR)
    queue = ZonePriorityQueue(scheduler, zoner)
    frame = _frame(pts=1.0)
    track = _track(5, (700, 250, 800, 450))
    zoner.label(frame, [track])
    queue.step(frame, [track])
    assert queue.metrics(1.0)["queue_depth"] == 1.0

    queue.forget(5, "cam0")
    assert queue.metrics(1.0)["queue_depth"] == 0.0


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def test_a_door_region_in_pixels_is_refused_at_load_time(tmp_path):
    """
    Not at first use. A malformed region discovered mid-run has already wasted
    the recording it was supposed to label.
    """
    path = tmp_path / "c.yaml"
    path.write_text(
        "core:\n  source_type: mock\nzones:\n  door_regions:\n"
        "    cam0: [100, 50, 400, 300]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="ternormalisasi|normal"):
        load_config(path)


def test_a_reversed_door_region_is_refused():
    with pytest.raises(ValueError, match="cam0"):
        ZoneConfig(door_regions={"cam0": [0.9, 0.1, 0.2, 0.5]})


def test_an_unknown_zones_key_is_refused(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("zones:\n  doors: {}\n", encoding="utf-8")
    with pytest.raises(ConfigBoundaryError, match="zones.doors"):
        load_config(path)


def test_the_shipped_config_keeps_the_queue_off():
    """
    §16. B1's baseline was measured with no queue in the loop; a default that
    turned it on would move every number the later steps are compared against,
    in the commit that introduced the comparison.
    """
    config = load_config()
    assert config.recognition.enabled is False
    assert config.zones.door_regions == {}


def test_unset_scheduler_values_do_not_become_zero():
    """
    `None` means "use the constant in identity/admission.py". Passing zeros here
    would give every one of those numbers a second home, and one day a second
    value — with the config file winning and the docstring explaining the other.
    """
    assert RecognitionConfig().scheduler_kwargs() == {}
    assert RecognitionConfig(per_camera_quota=2).scheduler_kwargs() == {
        "per_camera_quota": 2
    }
    with pytest.raises(ValueError):
        RecognitionConfig(max_age_seconds=0.0)


def test_the_factory_builds_a_zoner_always_and_a_queue_only_when_asked():
    import dataclasses

    from engine.config import EngineConfig
    from engine.factory import build_recognition_queue, build_zoner

    config = EngineConfig(source_type="mock")
    zoner = build_zoner(config)
    assert build_recognition_queue(config, zoner) is None

    enabled = dataclasses.replace(
        config, recognition=RecognitionConfig(enabled=True)
    )
    assert build_recognition_queue(enabled, build_zoner(enabled)) is not None


# --------------------------------------------------------------------------
# And nothing else moved (§16)
# --------------------------------------------------------------------------

def test_the_loop_without_a_zoner_behaves_exactly_as_before():
    """
    Both new stages are optional and off by default in `VisionEngine.__init__`.
    A benchmark comparing a post-B5 run with the committed B1 baseline has to be
    comparing the same loop, and the way to guarantee that is for the loop to be
    literally unchanged when the pieces are absent.
    """
    from engine.config import EngineConfig
    from engine.perception import MockDetector, MockTracker
    from engine.pipeline.engine import VisionEngine

    def run(**kwargs):
        from engine.ingest import MockFrameSource

        engine = VisionEngine(
            source=MockFrameSource(max_frames=20),
            detector=MockDetector(),
            tracker=MockTracker(),
            config=EngineConfig(source_type="mock"),
            **kwargs,
        )
        engine.start()
        boxes = []
        while True:
            frame, tracks = engine.step()
            if frame is None:
                break
            boxes.append([t.bbox.to_xyxy() for t in tracks])
        engine.stop()
        return boxes

    assert run() == run(zoner=TrackZoner(door_regions=DOOR))


def test_zone_exits_says_so_when_no_door_region_was_configured():
    """
    100% of tracks ending in `interior` looks alarming and means nothing if no
    region was ever drawn. A caveat that lives only in the docstring is a caveat
    nobody reads next to the number.
    """
    from engine.bench import metrics as M
    from engine.bench.tracklog import TrackSegment

    segments = [
        TrackSegment("cam0", 1, 0.0, [0.1, 0.1, 0.2, 0.5], 0, "interior"),
        TrackSegment("cam0", 2, 5.0, [0.7, 0.2, 0.8, 0.6], 0, "door"),
    ]
    without = M.zone_exits(segments, None, door_configured=False)
    assert "no door_region was configured" in without["caveat"]
    assert without["endings_by_zone"] == {"door": 1, "interior": 1}
    assert without["while_person_present"]["value"] is None

    with_region = M.zone_exits(segments, None, door_configured=True)
    assert "caveat" not in with_region


def test_zone_exits_counts_events_and_refuses_to_call_them_minutes():
    """
    §13.8's cheap form needs presence intervals only — no track map — and what it
    yields is a COUNT. The go/no-go in gonogo.yaml is in minutes, and turning a
    broken ending into minutes needs to know whose track it was.
    """
    from engine.bench import metrics as M
    from engine.bench.annotation import load_annotation
    from engine.bench.tracklog import TrackSegment

    import textwrap

    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "a.yaml"
        path.write_text(
            textwrap.dedent(
                """
                recording:
                  file: room.mp4
                  duration_seconds: 100
                  camera_id: cam0
                persons:
                  - id: "1"
                    presence:
                      - enter: 0
                        exit: 60
                """
            ).strip(),
            encoding="utf-8",
        )
        annotation = load_annotation(path)

    segments = [
        # ends mid-room while person 1 is demonstrably present: suspicious
        TrackSegment("cam0", 1, 0.0, [0.1, 0.1, 0.2, 0.5], 0, "interior"),
        # ends at the door while present: an ordinary departure
        TrackSegment("cam0", 2, 5.0, [0.7, 0.2, 0.8, 0.6], 0, "door"),
        # ends mid-room after everyone has left: not evidence of anything
        TrackSegment("cam0", 3, 80.0, [0.4, 0.4, 0.5, 0.6], 0, "interior"),
    ]
    for segment, end in zip(segments, (30.0, 40.0, 90.0)):
        segment.end_pts = end

    result = M.zone_exits(segments, annotation, door_configured=True)
    present = result["while_person_present"]
    assert present["endings"] == 2
    assert present["endings_in_interior"] == 1
    assert "NOT the go/no-go number" in present["note"]
