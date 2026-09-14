from __future__ import annotations

import logging
from typing import Dict, List

import numpy as np

from ..contracts.face import FaceDetection
from ..contracts.interfaces import (
    FaceAligner,
    FaceDetector,
    FaceEmbedder,
    FaceMatcher,
    IdentityRepository,
)
from ..contracts.recognition import RecognitionResult, RecognitionStatus

logger = logging.getLogger(__name__)


class FaceRecognitionService:
    """
    Stateless face-recognition pipeline.

    Input:
        An already prepared image containing a person.

    Output:
        RecognitionResult describing this recognition attempt.

    This service does not know:
        - Track
        - Track ID
        - YOLO
        - tracker
        - recognition cache
        - attendance
        - camera / RTSP
    """

    def __init__(
        self,
        detector: FaceDetector,
        aligner: FaceAligner,
        embedder: FaceEmbedder,
        matcher: FaceMatcher,
        repository: IdentityRepository,
    ) -> None:
        self._detector = detector
        self._aligner = aligner
        self._embedder = embedder
        self._matcher = matcher
        self._repository = repository

    def recognize(
        self,
        image: np.ndarray,
    ) -> RecognitionResult:
        """
        Perform one complete face-recognition attempt.
        """

        try:
            face_detections = self._detector.detect(image)

            if not face_detections:
                return RecognitionResult(
                    status=RecognitionStatus.NO_FACE,
                )

            primary_face = max(
                face_detections,
                key=lambda face: face.area,
            )

            aligned_face = self._aligner.align(
                image,
                primary_face,
            )

            embedding = self._embedder.embed(
                aligned_face,
            )

            references = self._repository.load_active_references()

            match = self._matcher.match(
                embedding,
                references,
            )

            if match.is_match:
                return RecognitionResult(
                    status=RecognitionStatus.RECOGNIZED,
                    identity_id=match.identity,
                    similarity=match.similarity,
                )

            return RecognitionResult(
                status=RecognitionStatus.UNKNOWN,
                similarity=match.similarity,
            )

        except Exception:
            logger.exception(
                "Face recognition failed."
            )

            return RecognitionResult(
                status=RecognitionStatus.ERROR,
            )