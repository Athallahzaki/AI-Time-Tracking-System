import numpy as np

from engine.plugins.face_recognizer.contracts.face import (
    FaceDetection,
    FaceEmbedding,
)
from engine.plugins.face_recognizer.contracts.identity import IdentityMatch
from engine.plugins.face_recognizer.contracts.interfaces import FaceRecognizer
from engine.plugins.face_recognizer.contracts.recognition import RecognitionStatus
from engine.plugins.face_recognizer.pipeline.recognizer import (
    FaceRecognitionService,
)


class FakeFaceDetector:
    def __init__(self, detections):
        self.detections = detections

    def detect(self, image):
        return self.detections


class FakeFaceAligner:
    def align(self, image, detection):
        return image


class FakeFaceEmbedder:
    def embed(self, aligned_face):
        return FaceEmbedding(
            vector=np.ones(512, dtype=np.float32),
            dimension=512,
        )


class FakeFaceMatcher:
    def __init__(self, result):
        self.result = result
        self.received_query = None
        self.received_references = None

    def match(self, query, references):
        self.received_query = query
        self.received_references = references
        return self.result


class FakeIdentityRepository:
    def __init__(self, references=None):
        self.references = references or {
            "EMP001": [
                np.ones(512, dtype=np.float32),
            ]
        }

    def load_active_references(self):
        return self.references


def make_service(
    detector=None,
    matcher=None,
    repository=None,
):
    return FaceRecognitionService(
        detector=detector or FakeFaceDetector([]),
        aligner=FakeFaceAligner(),
        embedder=FakeFaceEmbedder(),
        matcher=matcher or FakeFaceMatcher(
            IdentityMatch(
                identity=None,
                similarity=0.0,
            )
        ),
        repository=repository or FakeIdentityRepository(),
    )


def make_face(x1=10, y1=10, x2=100, y2=100):
    return FaceDetection(
        bbox=(x1, y1, x2, y2),
        confidence=0.95,
        landmarks=None,
    )


def test_no_face_returns_no_face():
    service = make_service(
        detector=FakeFaceDetector([]),
    )

    image = np.zeros((200, 200, 3), dtype=np.uint8)

    result = service.recognize(image)

    assert result.status == RecognitionStatus.NO_FACE
    assert result.identity_id is None


def test_recognized_face_returns_identity():
    matcher = FakeFaceMatcher(
        IdentityMatch(
            identity="EMP001",
            similarity=0.92,
        )
    )

    service = make_service(
        detector=FakeFaceDetector([make_face()]),
        matcher=matcher,
    )

    image = np.zeros((200, 200, 3), dtype=np.uint8)

    result = service.recognize(image)

    assert result.status == RecognitionStatus.RECOGNIZED
    assert result.identity_id == "EMP001"
    assert result.similarity == 0.92
    assert result.is_recognized


def test_unknown_face_returns_unknown():
    matcher = FakeFaceMatcher(
        IdentityMatch(
            identity=None,
            similarity=0.18,
        )
    )

    service = make_service(
        detector=FakeFaceDetector([make_face()]),
        matcher=matcher,
    )

    image = np.zeros((200, 200, 3), dtype=np.uint8)

    result = service.recognize(image)

    assert result.status == RecognitionStatus.UNKNOWN
    assert result.identity_id is None
    assert result.similarity == 0.18
    assert not result.is_recognized


def test_largest_face_is_used():
    small_face = make_face(
        x1=10,
        y1=10,
        x2=30,
        y2=30,
    )

    large_face = make_face(
        x1=10,
        y1=10,
        x2=100,
        y2=100,
    )

    class InspectAligner:
        def __init__(self):
            self.received_detection = None

        def align(self, image, detection):
            self.received_detection = detection
            return image

    aligner = InspectAligner()

    matcher = FakeFaceMatcher(
        IdentityMatch(
            identity="EMP001",
            similarity=0.95,
        )
    )

    service = FaceRecognitionService(
        detector=FakeFaceDetector(
            [small_face, large_face]
        ),
        aligner=aligner,
        embedder=FakeFaceEmbedder(),
        matcher=matcher,
        repository=FakeIdentityRepository(),
    )

    image = np.zeros((200, 200, 3), dtype=np.uint8)

    service.recognize(image)

    assert aligner.received_detection is large_face


def test_repository_is_used_for_matching():
    repository = FakeIdentityRepository(
        references={
            "EMP_A": [
                np.ones(512, dtype=np.float32),
            ],
            "EMP_B": [
                np.zeros(512, dtype=np.float32),
            ],
        }
    )

    matcher = FakeFaceMatcher(
        IdentityMatch(
            identity="EMP_A",
            similarity=0.91,
        )
    )

    service = make_service(
        detector=FakeFaceDetector([make_face()]),
        matcher=matcher,
        repository=repository,
    )

    image = np.zeros((200, 200, 3), dtype=np.uint8)

    service.recognize(image)

    assert matcher.received_references == repository.references
    assert matcher.received_query is not None


def test_recognition_error_returns_error_result():
    class BrokenDetector:
        def detect(self, image):
            raise RuntimeError("detector failed")

    service = make_service(
        detector=BrokenDetector(),
    )

    image = np.zeros((200, 200, 3), dtype=np.uint8)

    result = service.recognize(image)

    assert result.status == RecognitionStatus.ERROR
    assert result.identity_id is None


def test_service_implements_face_recognizer_protocol():
    service = make_service()

    assert isinstance(service, FaceRecognizer)