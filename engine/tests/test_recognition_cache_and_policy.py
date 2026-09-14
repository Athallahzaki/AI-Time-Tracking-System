from engine.vision_core.contracts.geometry import BoundingBox
from engine.vision_core.contracts.tracking import Track

from engine.plugins.face_recognizer.contracts.identity import (
    IdentityMatch,
    RecognitionState,
)
from engine.plugins.face_recognizer.contracts.recognition import (
    RecognitionStatus,
)
from engine.plugins.face_recognizer.cache.recognition_cache import (
    RecognitionCache,
)
from engine.plugins.face_recognizer.policy.recognition_policy import (
    StandardRecognitionPolicy,
)


def test_recognition_cache_lifecycle():
    cache = RecognitionCache(ttl_seconds=10.0)

    # 1. New track initializes in PENDING state
    state = cache.get_or_create(
        track_id=1,
        current_time=100.0,
    )

    assert state.state == RecognitionState.PENDING
    assert state.last_status is None
    assert state.identity is None

    # 2. Match success -> CONFIRMED + RECOGNIZED
    match = IdentityMatch(
        identity="EMP001",
        similarity=0.88,
    )

    state, changed = cache.update_with_match(
        track_id=1,
        match=match,
        current_time=100.5,
    )

    assert state.state == RecognitionState.CONFIRMED
    assert state.last_status == RecognitionStatus.RECOGNIZED
    assert state.identity == "EMP001"
    assert state.similarity == 0.88
    assert state.consecutive_matches == 1
    assert changed is False

    # 3. Identity change detection
    match_switch = IdentityMatch(
        identity="EMP002",
        similarity=0.91,
    )

    state, changed = cache.update_with_match(
        track_id=1,
        match=match_switch,
        current_time=101.0,
    )

    assert state.state == RecognitionState.CONFIRMED
    assert state.last_status == RecognitionStatus.RECOGNIZED
    assert state.identity == "EMP002"
    assert state.similarity == 0.91
    assert changed is True
    assert state.consecutive_matches == 1

    # 4. TTL expiration check
    assert (
        cache.is_expired(
            track_id=1,
            current_time=105.0,
        )
        is False
    )

    assert (
        cache.is_expired(
            track_id=1,
            current_time=112.0,
        )
        is True
    )

    # 5. Eviction on track removal
    cache.evict(1)

    assert cache.get(1) is None


def test_recognition_cache_unknown_and_no_face():
    cache = RecognitionCache()

    # Unrecognized face match
    match_unknown = IdentityMatch(
        identity=None,
        similarity=0.25,
    )

    state, changed = cache.update_with_match(
        track_id=2,
        match=match_unknown,
        current_time=100.0,
    )

    assert changed is False
    assert state.state == RecognitionState.RETRY
    assert state.last_status == RecognitionStatus.UNKNOWN
    assert state.similarity == 0.25
    assert state.retry_count == 1
    assert state.identity is None

    # No face detected
    state = cache.record_no_face(
        track_id=2,
        current_time=100.5,
    )

    assert state.state == RecognitionState.RETRY
    assert state.last_status == RecognitionStatus.NO_FACE
    assert state.retry_count == 2


def test_recognition_policy_evaluation():
    policy = StandardRecognitionPolicy(
        min_person_width=40,
        min_person_height=80,
        min_confirmations=2,
        unknown_retry_interval_sec=1.0,
        max_unknown_retries=3,
        backoff_retry_interval_sec=5.0,
        recognition_ttl_sec=30.0,
    )

    # 1. Quality reject: tiny box
    tiny_box = BoundingBox(
        x1=0,
        y1=0,
        x2=20,
        y2=30,
    )

    track_tiny = Track(
        track_id=1,
        bbox=tiny_box,
    )

    assert (
        policy.should_recognize(
            track_tiny,
            None,
            current_time=100.0,
        )
        is False
    )

    # 2. Valid box + no state -> recognize immediately
    valid_box = BoundingBox(
        x1=0,
        y1=0,
        x2=50,
        y2=100,
    )

    track_valid = Track(
        track_id=1,
        bbox=valid_box,
    )

    assert (
        policy.should_recognize(
            track_valid,
            None,
            current_time=100.0,
        )
        is True
    )

    # 3. First recognized result -> fast confirmation
    cache = RecognitionCache()

    match = IdentityMatch(
        identity="EMP001",
        similarity=0.85,
    )

    state, _ = cache.update_with_match(
        track_id=1,
        match=match,
        current_time=100.0,
    )

    assert state.state == RecognitionState.CONFIRMED
    assert state.last_status == RecognitionStatus.RECOGNIZED
    assert state.consecutive_matches == 1

    assert (
        policy.should_recognize(
            track_valid,
            state,
            current_time=100.2,
        )
        is True
    )

    # 4. Two confirmations -> don't recognize immediately
    state, _ = cache.update_with_match(
        track_id=1,
        match=match,
        current_time=100.2,
    )

    assert state.state == RecognitionState.CONFIRMED
    assert state.last_status == RecognitionStatus.RECOGNIZED
    assert state.consecutive_matches == 2

    assert (
        policy.should_recognize(
            track_valid,
            state,
            current_time=105.0,
        )
        is False
    )

    # 5. After recognition TTL -> refresh
    assert (
        policy.should_recognize(
            track_valid,
            state,
            current_time=135.0,
        )
        is True
    )

    # 6. UNKNOWN retry throttling
    state_unknown, _ = cache.update_with_match(
        track_id=2,
        match=IdentityMatch(
            identity=None,
            similarity=0.2,
        ),
        current_time=100.0,
    )

    assert state_unknown.state == RecognitionState.RETRY
    assert state_unknown.last_status == RecognitionStatus.UNKNOWN

    assert (
        policy.should_recognize(
            track_valid,
            state_unknown,
            current_time=100.5,
        )
        is False
    )

    assert (
        policy.should_recognize(
            track_valid,
            state_unknown,
            current_time=101.5,
        )
        is True
    )