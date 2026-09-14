import pytest
import numpy as np

from ..plugins.face_recognizer.contracts.recognition import RecognitionResult, RecognitionStatus
from engine.vision_core.contracts.geometry import BoundingBox
from engine.vision_core.contracts.tracking import Track, TrackState
from engine.vision_core.contracts.frame import Frame, FrameMetadata
from engine.plugins.face_recognizer.contracts.face import FaceDetection, FaceEmbedding, FaceLandmarks
from engine.plugins.face_recognizer.alignment.aligner import FaceAligner
from engine.plugins.face_recognizer.matching.similarity import cosine_similarity
from engine.plugins.face_recognizer.matching.matcher import FaceMatcher
from engine.plugins.face_recognizer.detector.mock_detector import MockFaceDetector
from engine.plugins.face_recognizer.embedding.mock_embedder import MockFaceEmbedder
from engine.plugins.face_recognizer.pipeline.plugin import FaceRecognizerPlugin


def test_face_alignment():
    aligner = FaceAligner(output_size=(112, 112))
    img = np.zeros((200, 200, 3), dtype=np.uint8)

    # 5 dummy landmarks
    landmarks = np.array(
        [
            [70.0, 70.0],
            [130.0, 70.0],
            [100.0, 100.0],
            [80.0, 130.0],
            [120.0, 130.0],
        ],
        dtype=np.float32,
    )
    det = FaceDetection(
        bbox=BoundingBox(50, 50, 150, 150),
        confidence=0.99,
        landmarks=FaceLandmarks(points=landmarks),
    )

    aligned = aligner.align(img, det)
    assert aligned.shape == (112, 112, 3)


def test_cosine_similarity_and_matcher():
    matcher = FaceMatcher(threshold=0.50)

    # Generate reference embedding for EMP001
    v1 = np.zeros(512, dtype=np.float32)
    v1[0] = 1.0  # Unit vector along axis 0

    references = {"EMP001": [v1]}

    # Query 1: Exactly matching vector
    q_exact = FaceEmbedding(vector=v1.copy(), dimension=512)
    match = matcher.match(q_exact, references)
    assert match.is_match is True
    assert match.identity == "EMP001"
    assert match.similarity == pytest.approx(1.0)

    # Query 2: Orthogonal vector (similarity 0.0 < threshold 0.50)
    v_ortho = np.zeros(512, dtype=np.float32)
    v_ortho[1] = 1.0
    q_ortho = FaceEmbedding(vector=v_ortho, dimension=512)
    match_ortho = matcher.match(q_ortho, references)
    assert match_ortho.is_match is False
    assert match_ortho.identity is None
    assert match_ortho.similarity == pytest.approx(0.0)


def test_face_recognizer_plugin_track_listener():
    # Setup mock components
    detector = MockFaceDetector(return_detection=True)
    embedder = MockFaceEmbedder(dimension=512)
    matcher = FaceMatcher(threshold=0.30)

    plugin = FaceRecognizerPlugin(
        detector=detector,
        embedder=embedder,
        matcher=matcher,
    )

    # Seed reference embedding matching the mock embedder output
    dummy_img = np.zeros((300, 200, 3), dtype=np.uint8)
    dummy_img[:, :] = (100, 100, 100)

    ref_emb = embedder.embed(dummy_img).vector

    plugin.repository.register_employee(
        "EMP_TEST",
        "Test Employee",
        [ref_emb],
    )

    # Create Frame and Track
    frame = Frame(
        image=dummy_img,
        metadata=FrameMetadata(
            frame_id=1,
            timestamp=100.0,
        ),
    )

    track = Track(
        track_id=10,
        bbox=BoundingBox(
            x1=10,
            y1=10,
            x2=150,
            y2=250,
        ),
        state=TrackState.TRACKED,
    )

    # Invoke plugin listener
    plugin.on_tracks_updated([track], frame)

    # Verify track decoration
    assert track.attributes["identity"] == "EMP_TEST"
    assert track.attributes["recognition_status"] == "CONFIRMED"
    assert track.attributes["similarity"] > 0.9


class MockPersonCropper:
    def __init__(self, crop):
        self.crop_result = crop
        self.called = False
        self.received_image = None
        self.received_track = None

    def crop(self, image, track):
        self.called = True
        self.received_image = image
        self.received_track = track
        return self.crop_result


class MockImagePreprocessor:
    def __init__(self, result):
        self.result = result
        self.called = False
        self.received_image = None

    def preprocess(self, image):
        self.called = True
        self.received_image = image
        return self.result


class MockRecognizer:
    def __init__(self, result):
        self.result = result
        self.called = False
        self.received_image = None

    def recognize(self, image):
        self.called = True
        self.received_image = image
        return self.result


def test_plugin_uses_cropper_preprocessor_and_recognizer():
    frame_image = np.zeros((200, 100, 3), dtype=np.uint8)
    person_crop = np.ones((80, 40, 3), dtype=np.uint8)
    prepared_image = np.full((112, 112, 3), 7, dtype=np.uint8)

    person_cropper = MockPersonCropper(person_crop)
    preprocessor = MockImagePreprocessor(prepared_image)

    recognizer = MockRecognizer(
        RecognitionResult(
            status=RecognitionStatus.NO_FACE,
        )
    )

    plugin = FaceRecognizerPlugin(
        recognizer=recognizer,
        person_cropper=person_cropper,
        image_preprocessor=preprocessor,
    )

    track = Track(
        track_id=1,
        bbox=BoundingBox(
            x1=10,
            y1=20,
            x2=60,
            y2=120,
        ),
    )

    frame = Frame(image=frame_image)

    plugin._process_recognition(
        track=track,
        frame=frame,
        current_time=100.0,
    )

    assert person_cropper.called
    assert person_cropper.received_image is frame_image
    assert person_cropper.received_track is track

    assert preprocessor.called
    assert preprocessor.received_image is person_crop

    assert recognizer.called
    assert recognizer.received_image is prepared_image


def test_plugin_handles_failed_person_crop():
    frame_image = np.zeros((200, 100, 3), dtype=np.uint8)

    person_cropper = MockPersonCropper(None)

    preprocessor = MockImagePreprocessor(
        np.ones((112, 112, 3), dtype=np.uint8)
    )

    recognizer = MockRecognizer(
        RecognitionResult(
            status=RecognitionStatus.RECOGNIZED,
            identity_id="employee-1",
            similarity=0.95,
        )
    )

    plugin = FaceRecognizerPlugin(
        recognizer=recognizer,
        person_cropper=person_cropper,
        image_preprocessor=preprocessor,
    )

    track = Track(
        track_id=1,
        bbox=BoundingBox(
            x1=10,
            y1=20,
            x2=60,
            y2=120,
        ),
    )

    frame = Frame(image=frame_image)

    plugin._process_recognition(
        track=track,
        frame=frame,
        current_time=100.0,
    )

    assert person_cropper.called
    assert not preprocessor.called
    assert not recognizer.called