from __future__ import annotations

from typing import Dict, List, Optional, Protocol, runtime_checkable

import numpy as np

from ....vision_core.contracts.tracking import Track
from .face import FaceDetection, FaceEmbedding
from .identity import IdentityMatch, TrackIdentityState
from .recognition import RecognitionResult


@runtime_checkable
class FaceDetector(Protocol):
    """Interface for face detection models."""

    def detect(self, image: np.ndarray) -> List[FaceDetection]:
        ...


@runtime_checkable
class FaceAligner(Protocol):
    """Interface for face alignment routines."""

    def align(
        self,
        image: np.ndarray,
        detection: FaceDetection,
    ) -> np.ndarray:
        ...


@runtime_checkable
class FaceEmbedder(Protocol):
    """Interface for facial feature extraction models."""

    def embed(
        self,
        aligned_face: np.ndarray,
    ) -> FaceEmbedding:
        ...


@runtime_checkable
class FaceMatcher(Protocol):
    """Interface for matching embedding vectors against registered references."""

    def match(
        self,
        query: FaceEmbedding,
        references: Dict[str, List[np.ndarray]],
    ) -> IdentityMatch:
        ...


@runtime_checkable
class FaceRecognizer(Protocol):
    """
    High-level stateless face-recognition service.

    Input is an already prepared image.
    The recognizer does not know where the image came from.
    """

    def recognize(
        self,
        image: np.ndarray,
    ) -> RecognitionResult:
        ...


@runtime_checkable
class IdentityRepository(Protocol):
    """Interface for loading registered identity references."""

    def load_active_references(
        self,
    ) -> Dict[str, List[np.ndarray]]:
        ...


@runtime_checkable
class RecognitionPolicy(Protocol):
    """
    Determines whether recognition should be performed
    for a tracked object.
    """

    def should_recognize(
        self,
        track: Track,
        state: Optional[TrackIdentityState],
        current_time: float,
    ) -> bool:
        ...

@runtime_checkable
class EnrollmentRepository(Protocol):
    """Interface for registering and managing identities."""

    def register_employee(
        self,
        employee_id: str,
        name: str,
        embeddings: List[np.ndarray],
        active: bool = True,
    ) -> None:
        ...

    def set_active(
        self,
        employee_id: str,
        active: bool,
    ) -> None:
        ...

    def delete_employee(
        self,
        employee_id: str,
    ) -> bool:
        ...