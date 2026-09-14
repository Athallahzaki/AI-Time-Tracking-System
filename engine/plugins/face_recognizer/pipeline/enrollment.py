from __future__ import annotations

from typing import List

import numpy as np

from ..contracts.face import FaceEmbedding
from ..contracts.interfaces import (
    FaceAligner,
    FaceDetector,
    FaceEmbedder,
    EnrollmentRepository,
)


class EnrollmentError(Exception):
    """Raised when an identity cannot be enrolled safely."""


class EnrollmentService:
    """
    Converts reference face images into identity embeddings
    and persists them through the enrollment repository.
    """

    def __init__(
        self,
        detector: FaceDetector,
        aligner: FaceAligner,
        embedder: FaceEmbedder,
        repository: EnrollmentRepository,
    ) -> None:
        self._detector = detector
        self._aligner = aligner
        self._embedder = embedder
        self._repository = repository

    def enroll(
        self,
        employee_id: str,
        name: str,
        images: List[np.ndarray],
        active: bool = True,
    ) -> None:
        if not employee_id.strip():
            raise ValueError("employee_id must not be empty.")

        if not name.strip():
            raise ValueError("name must not be empty.")

        if not images:
            raise ValueError("At least one reference image is required.")

        embeddings: List[np.ndarray] = []

        for index, image in enumerate(images):
            embedding = self._process_reference_image(
                image=image,
                image_index=index,
            )
            embeddings.append(np.asarray(embedding))

        self._repository.register_employee(
            employee_id=employee_id,
            name=name,
            embeddings=embeddings,
            active=active,
        )

    def _process_reference_image(
        self,
        image: np.ndarray,
        image_index: int,
    ) -> FaceEmbedding:
        if image is None or image.size == 0:
            raise EnrollmentError(
                f"Reference image {image_index} is empty."
            )

        detections = self._detector.detect(image)

        if not detections:
            raise EnrollmentError(
                f"No face detected in reference image {image_index}."
            )

        if len(detections) > 1:
            raise EnrollmentError(
                f"Multiple faces detected in reference image {image_index}."
            )

        detection = detections[0]

        aligned_face = self._aligner.align(
            image,
            detection,
        )

        if aligned_face is None or aligned_face.size == 0:
            raise EnrollmentError(
                f"Face alignment failed for reference image {image_index}."
            )

        return self._embedder.embed(aligned_face)