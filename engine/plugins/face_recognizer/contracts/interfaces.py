from __future__ import annotations

from typing import Dict, List, Optional, Protocol, Sequence, runtime_checkable

import numpy as np

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
    """Interface for face alignment."""

    def align(
        self,
        image: np.ndarray,
        detection: FaceDetection,
    ) -> np.ndarray:
        ...


@runtime_checkable
class FaceEmbedder(Protocol):
    """Interface for facial feature extraction."""

    def embed(
        self,
        aligned_face: np.ndarray,
    ) -> FaceEmbedding:
        ...


@runtime_checkable
class FaceMatcher(Protocol):
    """Interface for comparing an embedding against registered references."""

    def match(
        self,
        query: FaceEmbedding,
        references: Dict[str, List[np.ndarray]],
    ) -> IdentityMatch:
        ...


@runtime_checkable
class IdentityRepository(Protocol):
    """Persistence boundary for registered identity embeddings."""

    def load_active_references(
        self,
    ) -> Dict[str, List[np.ndarray]]:
        ...


@runtime_checkable
class RecognitionPolicy(Protocol):
    """
    Determines whether a track should undergo recognition.

    This is a state/orchestration concern rather than a face-model concern.
    """

    def should_recognize(
        self,
        track_id: int,
        state: Optional[TrackIdentityState],
        current_time: float,
    ) -> bool:
        ...

@runtime_checkable
class FaceRecognizer(Protocol):
    """
    Stateless high-level face recognition service.

    Input is an already prepared image.
    It does not know Track, YOLO, FrameSource, or cache state.
    """

    def recognize(
        self,
        image: np.ndarray,
    ) -> RecognitionResult:
        ...