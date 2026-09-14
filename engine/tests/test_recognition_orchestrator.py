import numpy as np

from engine.plugins.face_recognizer.cache.recognition_cache import (
    RecognitionCache,
)
from engine.plugins.face_recognizer.contracts.events import (
    FaceRecognizedEvent,
    PersonUnknownEvent,
)
from engine.plugins.face_recognizer.contracts.identity import (
    RecognitionState,
)
from engine.plugins.face_recognizer.contracts.recognition import (
    RecognitionResult,
    RecognitionStatus,
)
from engine.plugins.face_recognizer.pipeline.orchestrator import (
    RecognitionOrchestrator,
)
from engine.vision_core.contracts.frame import (
    Frame,
    FrameMetadata,
)
from engine.vision_core.contracts.geometry import (
    BoundingBox,
)
from engine.vision_core.contracts.tracking import (
    Track,
)


class FakeRecognitionPolicy:
    def __init__(self, should_recognize=True):
        self.should_recognize_result = should_recognize
        self.called = False
        self.received_track = None
        self.received_state = None
        self.received_time = None

    def should_recognize(
        self,
        track,
        state,
        current_time,
    ):
        self.called = True
        self.received_track = track
        self.received_state = state
        self.received_time = current_time

        return self.should_recognize_result


class FakePersonCropper:
    def __init__(self, result):
        self.result = result
        self.called = False
        self.received_image = None
        self.received_track = None

    def crop(self, image, track):
        self.called = True
        self.received_image = image
        self.received_track = track

        return self.result


class FakeImagePreprocessor:
    def __init__(self, result):
        self.result = result
        self.called = False
        self.received_image = None

    def preprocess(self, image):
        self.called = True
        self.received_image = image

        return self.result


class FakeFaceRecognizer:
    def __init__(self, result):
        self.result = result
        self.called = False
        self.received_image = None

    def recognize(self, image):
        self.called = True
        self.received_image = image

        return self.result


def make_track(track_id=1):
    return Track(
        track_id=track_id,
        bbox=BoundingBox(
            x1=10,
            y1=20,
            x2=60,
            y2=120,
        ),
    )


def make_frame():
    image = np.zeros(
        (200, 100, 3),
        dtype=np.uint8,
    )

    return Frame(
        image=image,
        metadata=FrameMetadata(
            frame_id=1,
            timestamp=100.0,
        ),
    )


def make_orchestrator(
    *,
    policy,
    cropper,
    preprocessor,
    recognizer,
    cache=None,
    event_handler=None,
):
    if cache is None:
        cache = RecognitionCache(
            ttl_seconds=60.0,
        )

    return RecognitionOrchestrator(
        recognizer=recognizer,
        person_cropper=cropper,
        image_preprocessor=preprocessor,
        policy=policy,
        cache=cache,
        event_handler=event_handler,
    ), cache


def test_orchestrator_runs_recognition_workflow():
    frame = make_frame()
    track = make_track()

    person_crop = np.ones(
        (80, 40, 3),
        dtype=np.uint8,
    )

    prepared_image = np.full(
        (112, 112, 3),
        7,
        dtype=np.uint8,
    )

    policy = FakeRecognitionPolicy(
        should_recognize=True,
    )

    cropper = FakePersonCropper(
        result=person_crop,
    )

    preprocessor = FakeImagePreprocessor(
        result=prepared_image,
    )

    recognizer = FakeFaceRecognizer(
        result=RecognitionResult(
            status=RecognitionStatus.RECOGNIZED,
            identity_id="EMP001",
            similarity=0.95,
        ),
    )

    orchestrator, cache = make_orchestrator(
        policy=policy,
        cropper=cropper,
        preprocessor=preprocessor,
        recognizer=recognizer,
    )

    result = orchestrator.process(
        track=track,
        frame=frame,
        current_time=100.0,
    )

    assert result is not None
    assert result.status == RecognitionStatus.RECOGNIZED
    assert result.identity_id == "EMP001"
    assert result.similarity == 0.95

    assert policy.called
    assert policy.received_track is track
    assert policy.received_state is None
    assert policy.received_time == 100.0

    assert cropper.called
    assert cropper.received_image is frame.image
    assert cropper.received_track is track

    assert preprocessor.called
    assert preprocessor.received_image is person_crop

    assert recognizer.called
    assert recognizer.received_image is prepared_image

    state = cache.get(track.track_id)

    assert state is not None
    assert state.identity == "EMP001"
    assert state.similarity == 0.95
    assert state.state == RecognitionState.CONFIRMED
    assert state.consecutive_matches == 1


def test_orchestrator_skips_when_policy_denies_recognition():
    frame = make_frame()
    track = make_track()

    policy = FakeRecognitionPolicy(
        should_recognize=False,
    )

    cropper = FakePersonCropper(
        result=np.ones(
            (80, 40, 3),
            dtype=np.uint8,
        ),
    )

    preprocessor = FakeImagePreprocessor(
        result=np.ones(
            (112, 112, 3),
            dtype=np.uint8,
        ),
    )

    recognizer = FakeFaceRecognizer(
        result=RecognitionResult(
            status=RecognitionStatus.RECOGNIZED,
            identity_id="EMP001",
            similarity=0.95,
        ),
    )

    orchestrator, cache = make_orchestrator(
        policy=policy,
        cropper=cropper,
        preprocessor=preprocessor,
        recognizer=recognizer,
    )

    result = orchestrator.process(
        track=track,
        frame=frame,
        current_time=100.0,
    )

    assert result is None

    assert policy.called
    assert not cropper.called
    assert not preprocessor.called
    assert not recognizer.called

    assert cache.get(track.track_id) is None


def test_orchestrator_stops_when_person_crop_fails():
    frame = make_frame()
    track = make_track()

    policy = FakeRecognitionPolicy(
        should_recognize=True,
    )

    cropper = FakePersonCropper(
        result=None,
    )

    preprocessor = FakeImagePreprocessor(
        result=np.ones(
            (112, 112, 3),
            dtype=np.uint8,
        ),
    )

    recognizer = FakeFaceRecognizer(
        result=RecognitionResult(
            status=RecognitionStatus.RECOGNIZED,
            identity_id="EMP001",
            similarity=0.95,
        ),
    )

    orchestrator, cache = make_orchestrator(
        policy=policy,
        cropper=cropper,
        preprocessor=preprocessor,
        recognizer=recognizer,
    )

    result = orchestrator.process(
        track=track,
        frame=frame,
        current_time=100.0,
    )

    assert result is not None
    assert result.status == RecognitionStatus.ERROR

    assert policy.called
    assert cropper.called
    assert not preprocessor.called
    assert not recognizer.called

    state = cache.get(track.track_id)

    assert state is not None
    assert state.state == RecognitionState.RETRY
    assert state.identity is None
    assert state.retry_count == 1


def test_orchestrator_emits_face_recognized_event():
    frame = make_frame()
    track = make_track()

    events = []

    policy = FakeRecognitionPolicy(
        should_recognize=True,
    )

    cropper = FakePersonCropper(
        result=np.ones(
            (80, 40, 3),
            dtype=np.uint8,
        ),
    )

    preprocessor = FakeImagePreprocessor(
        result=np.ones(
            (112, 112, 3),
            dtype=np.uint8,
        ),
    )

    recognizer = FakeFaceRecognizer(
        result=RecognitionResult(
            status=RecognitionStatus.RECOGNIZED,
            identity_id="EMP001",
            similarity=0.95,
        ),
    )

    orchestrator, _ = make_orchestrator(
        policy=policy,
        cropper=cropper,
        preprocessor=preprocessor,
        recognizer=recognizer,
        event_handler=events.append,
    )

    result = orchestrator.process(
        track=track,
        frame=frame,
        current_time=100.0,
    )

    assert result is not None
    assert result.status == RecognitionStatus.RECOGNIZED

    assert len(events) == 1
    assert isinstance(
        events[0],
        FaceRecognizedEvent,
    )

    event = events[0]

    assert event.track_id == track.track_id
    assert event.employee_id == "EMP001"
    assert event.similarity == 0.95
    assert event.track is track


def test_orchestrator_emits_person_unknown_event():
    frame = make_frame()
    track = make_track()

    events = []

    policy = FakeRecognitionPolicy(
        should_recognize=True,
    )

    cropper = FakePersonCropper(
        result=np.ones(
            (80, 40, 3),
            dtype=np.uint8,
        ),
    )

    preprocessor = FakeImagePreprocessor(
        result=np.ones(
            (112, 112, 3),
            dtype=np.uint8,
        ),
    )

    recognizer = FakeFaceRecognizer(
        result=RecognitionResult(
            status=RecognitionStatus.UNKNOWN,
            similarity=0.18,
        ),
    )

    orchestrator, cache = make_orchestrator(
        policy=policy,
        cropper=cropper,
        preprocessor=preprocessor,
        recognizer=recognizer,
        event_handler=events.append,
    )

    result = orchestrator.process(
        track=track,
        frame=frame,
        current_time=100.0,
    )

    assert result is not None
    assert result.status == RecognitionStatus.UNKNOWN

    assert len(events) == 1
    assert isinstance(
        events[0],
        PersonUnknownEvent,
    )

    event = events[0]

    assert event.track_id == track.track_id
    assert event.similarity == 0.18
    assert event.track is track

    state = cache.get(track.track_id)

    assert state is not None
    assert state.state == RecognitionState.RETRY