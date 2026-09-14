from engine.plugins.face_recognizer.cache.recognition_cache import (
    RecognitionCache,
)
from engine.plugins.face_recognizer.contracts.identity import (
    IdentityMatch,
    RecognitionState,
)
from engine.plugins.face_recognizer.contracts.recognition import (
    RecognitionStatus,
)


def test_record_unknown_sets_unknown_status():
    cache = RecognitionCache()

    state = cache.record_unknown(
        track_id=1,
        similarity=0.18,
        current_time=100.0,
    )

    assert state.state == RecognitionState.RETRY
    assert state.last_status == RecognitionStatus.UNKNOWN
    assert state.similarity == 0.18
    assert state.retry_count == 1


def test_record_no_face_sets_no_face_status():
    cache = RecognitionCache()

    state = cache.record_no_face(
        track_id=1,
        current_time=100.0,
    )

    assert state.state == RecognitionState.RETRY
    assert state.last_status == RecognitionStatus.NO_FACE
    assert state.retry_count == 1


def test_record_error_sets_error_status():
    cache = RecognitionCache()

    state = cache.record_error(
        track_id=1,
        current_time=100.0,
    )

    assert state.state == RecognitionState.RETRY
    assert state.last_status == RecognitionStatus.ERROR
    assert state.retry_count == 1


def test_update_with_match_sets_recognized_status():
    cache = RecognitionCache()

    state, identity_changed = cache.update_with_match(
        track_id=1,
        match=IdentityMatch(
            identity="EMP001",
            similarity=0.95,
        ),
        current_time=100.0,
    )

    assert identity_changed is False
    assert state.state == RecognitionState.CONFIRMED
    assert state.last_status == RecognitionStatus.RECOGNIZED
    assert state.identity == "EMP001"
    assert state.similarity == 0.95
    assert state.retry_count == 0