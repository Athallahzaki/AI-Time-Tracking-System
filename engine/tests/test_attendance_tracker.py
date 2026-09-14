import numpy as np

from engine.app.attendance_tracker import AttendanceTracker, PresenceStatus
from engine.app.config import AttendanceConfig
from engine.app.events import (
    PersonConfirmedEvent,
    PersonDepartedEvent,
    PersonEnteredEvent,
    SessionLimitReachedEvent,
    SessionWarningEvent,
)
from engine.vision_core.contracts.frame import Frame, FrameMetadata
from engine.vision_core.contracts.geometry import BoundingBox
from engine.vision_core.contracts.tracking import Track, TrackState


def make_frame(timestamp: float, frame_id: int = 1) -> Frame:
    image = np.zeros((240, 320, 3), dtype=np.uint8)

    return Frame(
        image=image,
        metadata=FrameMetadata(
            frame_id=frame_id,
            timestamp=timestamp,
        ),
    )


def make_track(
    track_id: int,
    timestamp: float,
    identity: str | None = None,
    state: TrackState = TrackState.TRACKED,
) -> Track:
    attributes = {}

    if identity is not None:
        attributes["identity"] = identity

    return Track(
        track_id=track_id,
        bbox=BoundingBox(
            x1=50,
            y1=40,
            x2=120,
            y2=180,
        ),
        state=state,
        first_seen_timestamp=timestamp,
        last_seen_timestamp=timestamp,
        attributes=attributes,
    )


def test_new_track_creates_passing_session_and_emits_entered():
    tracker = AttendanceTracker(
        AttendanceConfig(
            min_present_seconds=60.0,
            warning_minutes=25.0,
            max_session_minutes=30.0,
            max_missing_seconds=10.0,
        )
    )

    events = []
    tracker.add_event_handler(events.append)

    track = make_track(
        1,
        100.0,
        identity="EMP_001",
    )

    tracker.on_tracks_updated(
        [track],
        make_frame(100.0),
    )

    session = tracker.get_session("EMP_001")

    assert session is not None
    assert session.status == PresenceStatus.PASSING
    assert session.employee_id == "EMP_001"
    assert session.active_track_id == 1

    assert track.attributes["presence_status"] == "PASSING"
    assert track.attributes["session_elapsed"] == 0.0

    assert sum(
        isinstance(event, PersonEnteredEvent)
        for event in events
    ) == 1


def test_session_progresses_through_confirmed_warning_and_limit_once():
    tracker = AttendanceTracker(
        AttendanceConfig(
            min_present_seconds=60.0,
            warning_minutes=25.0,
            max_session_minutes=30.0,
            max_missing_seconds=10.0,
        )
    )

    events = []
    tracker.add_event_handler(events.append)

    tracker.on_tracks_updated(
        [make_track(1, 100.0, identity="EMP_001")],
        make_frame(100.0, 1),
    )

    tracker.on_tracks_updated(
        [make_track(1, 160.0, identity="EMP_001")],
        make_frame(160.0, 2),
    )

    tracker.on_tracks_updated(
        [make_track(1, 1600.0, identity="EMP_001")],
        make_frame(1600.0, 3),
    )

    tracker.on_tracks_updated(
        [make_track(1, 1900.0, identity="EMP_001")],
        make_frame(1900.0, 4),
    )

    session = tracker.get_session("EMP_001")

    assert session is not None
    assert session.status == PresenceStatus.LIMIT
    assert session.confirmed_emitted is True
    assert session.warning_emitted is True
    assert session.limit_emitted is True

    assert sum(
        isinstance(event, PersonConfirmedEvent)
        for event in events
    ) == 1

    assert sum(
        isinstance(event, SessionWarningEvent)
        for event in events
    ) == 1

    assert sum(
        isinstance(event, SessionLimitReachedEvent)
        for event in events
    ) == 1


def test_repeated_updates_do_not_repeat_milestone_events():
    tracker = AttendanceTracker(
        AttendanceConfig(
            min_present_seconds=60.0,
            warning_minutes=2.0,
            max_session_minutes=4.0,
        )
    )

    events = []
    tracker.add_event_handler(events.append)

    timestamps = [100.0, 160.0, 220.0, 230.0]

    for index, timestamp in enumerate(
        timestamps,
        start=1,
    ):
        tracker.on_tracks_updated(
            [make_track(
                1,
                timestamp,
                identity="EMP_001",
            )],
            make_frame(
                timestamp,
                index,
            ),
        )

    assert sum(
        isinstance(event, PersonConfirmedEvent)
        for event in events
    ) == 1

    assert sum(
        isinstance(event, SessionWarningEvent)
        for event in events
    ) == 1

    assert sum(
        isinstance(event, SessionLimitReachedEvent)
        for event in events
    ) == 0


def test_identity_upgrade_preserves_anonymous_session():
    tracker = AttendanceTracker(
        AttendanceConfig(
            min_present_seconds=60.0,
            max_missing_seconds=10.0,
        )
    )

    events = []
    tracker.add_event_handler(events.append)

    tracker.on_tracks_updated(
        [make_track(7, 100.0)],
        make_frame(100.0, 1),
    )

    anonymous_session = tracker.get_session("track_7")

    assert anonymous_session is not None

    tracker.on_tracks_updated(
        [make_track(
            7,
            130.0,
            identity="EMP_007",
        )],
        make_frame(130.0, 2),
    )

    upgraded = tracker.get_session("EMP_007")

    assert upgraded is anonymous_session
    assert upgraded.employee_id == "EMP_007"
    assert upgraded.session_id == "EMP_007"
    assert upgraded.first_seen == 100.0
    assert upgraded.last_seen == 130.0

    assert tracker.get_session("track_7") is None
    assert tracker._track_to_key[7] == "EMP_007"


def test_temporary_missing_does_not_close_session():
    tracker = AttendanceTracker(
        AttendanceConfig(
            min_present_seconds=60.0,
            max_missing_seconds=10.0,
        )
    )

    events = []
    tracker.add_event_handler(events.append)

    tracker.on_tracks_updated(
        [make_track(
            3,
            100.0,
            identity="EMP_003",
        )],
        make_frame(100.0, 1),
    )

    tracker.on_tracks_updated(
        [],
        make_frame(105.0, 2),
    )

    session = tracker.get_session("EMP_003")

    assert session is not None
    assert session.last_seen == 100.0

    assert not any(
        isinstance(event, PersonDepartedEvent)
        for event in events
    )


def test_departure_closes_session_and_cleans_track_mapping():
    tracker = AttendanceTracker(
        AttendanceConfig(
            min_present_seconds=60.0,
            max_missing_seconds=10.0,
        )
    )

    events = []
    tracker.add_event_handler(events.append)

    tracker.on_tracks_updated(
        [make_track(
            4,
            100.0,
            identity="EMP_004",
        )],
        make_frame(100.0, 1),
    )

    tracker.on_tracks_updated(
        [],
        make_frame(111.0, 2),
    )

    assert tracker.get_session("EMP_004") is None
    assert 4 not in tracker._track_to_key

    departed = [
        event
        for event in events
        if isinstance(event, PersonDepartedEvent)
    ]

    assert len(departed) == 1
    assert departed[0].employee_id == "EMP_004"
    assert departed[0].track_id == 4
    assert departed[0].total_session_seconds == 0.0