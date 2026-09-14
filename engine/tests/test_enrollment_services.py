import numpy as np
import pytest

from engine.plugins.face_recognizer.pipeline.enrollment import (
    EnrollmentError,
    EnrollmentService,
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
    def __init__(self, embedding=None):
        self.embedding = embedding or np.ones(
            512,
            dtype=np.float32,
        )

    def embed(self, aligned_face):
        return self.embedding


class FakeEnrollmentRepository:
    def __init__(self):
        self.calls = []

    def register_employee(
        self,
        employee_id,
        name,
        embeddings,
        active=True,
    ):
        self.calls.append(
            {
                "employee_id": employee_id,
                "name": name,
                "embeddings": embeddings,
                "active": active,
            }
        )

    def set_active(self, employee_id, active):
        pass

    def delete_employee(self, employee_id):
        return False


class FakeFaceDetection:
    pass


def make_service(detections):
    repository = FakeEnrollmentRepository()

    service = EnrollmentService(
        detector=FakeFaceDetector(detections),
        aligner=FakeFaceAligner(),
        embedder=FakeFaceEmbedder(),
        repository=repository,
    )

    return service, repository


def test_enrollment_registers_identity():
    service, repository = make_service(
        [FakeFaceDetection()]
    )

    image = np.zeros(
        (112, 112, 3),
        dtype=np.uint8,
    )

    service.enroll(
        employee_id="EMP001",
        name="Alice",
        images=[image],
    )

    assert len(repository.calls) == 1

    call = repository.calls[0]

    assert call["employee_id"] == "EMP001"
    assert call["name"] == "Alice"
    assert call["active"] is True
    assert len(call["embeddings"]) == 1
    assert call["embeddings"][0].shape == (512,)


def test_enrollment_accepts_multiple_reference_images():
    service, repository = make_service(
        [FakeFaceDetection()]
    )

    images = [
        np.zeros((112, 112, 3), dtype=np.uint8),
        np.ones((112, 112, 3), dtype=np.uint8),
        np.full(
            (112, 112, 3),
            127,
            dtype=np.uint8,
        ),
    ]

    service.enroll(
        employee_id="EMP001",
        name="Alice",
        images=images,
    )

    assert len(repository.calls) == 1
    assert len(repository.calls[0]["embeddings"]) == 3


def test_enrollment_rejects_empty_image():
    service, repository = make_service(
        [FakeFaceDetection()]
    )

    with pytest.raises(EnrollmentError):
        service.enroll(
            employee_id="EMP001",
            name="Alice",
            images=[
                np.empty((0, 0, 3), dtype=np.uint8)
            ],
        )

    assert repository.calls == []


def test_enrollment_rejects_no_face():
    service, repository = make_service([])

    image = np.zeros(
        (112, 112, 3),
        dtype=np.uint8,
    )

    with pytest.raises(EnrollmentError):
        service.enroll(
            employee_id="EMP001",
            name="Alice",
            images=[image],
        )

    assert repository.calls == []


def test_enrollment_rejects_multiple_faces():
    service, repository = make_service(
        [
            FakeFaceDetection(),
            FakeFaceDetection(),
        ]
    )

    image = np.zeros(
        (112, 112, 3),
        dtype=np.uint8,
    )

    with pytest.raises(EnrollmentError):
        service.enroll(
            employee_id="EMP001",
            name="Alice",
            images=[image],
        )

    assert repository.calls == []


def test_enrollment_rejects_empty_employee_id():
    service, repository = make_service(
        [FakeFaceDetection()]
    )

    image = np.zeros(
        (112, 112, 3),
        dtype=np.uint8,
    )

    with pytest.raises(ValueError):
        service.enroll(
            employee_id="",
            name="Alice",
            images=[image],
        )

    assert repository.calls == []


def test_enrollment_rejects_empty_name():
    service, repository = make_service(
        [FakeFaceDetection()]
    )

    image = np.zeros(
        (112, 112, 3),
        dtype=np.uint8,
    )

    with pytest.raises(ValueError):
        service.enroll(
            employee_id="EMP001",
            name="",
            images=[image],
        )

    assert repository.calls == []


def test_enrollment_rejects_no_images():
    service, repository = make_service(
        [FakeFaceDetection()]
    )

    with pytest.raises(ValueError):
        service.enroll(
            employee_id="EMP001",
            name="Alice",
            images=[],
        )

    assert repository.calls == []