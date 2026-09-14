from __future__ import annotations

from typing import Dict, List, Optional, Protocol, Tuple, runtime_checkable
import numpy as np

from ....vision_core.contracts.tracking import Track
from .face import FaceDetection, FaceEmbedding
from .identity import IdentityMatch, TrackIdentityState


@runtime_checkable
class FaceDetector(Protocol):
    """Interface for face detection models (SCRFD, RetinaFace, OpenCV YuNet)."""

    def detect(self, image: np.ndarray) -> List[FaceDetection]:
        """Detects faces and 5-point landmarks in an image (e.g. cropped person or full frame)."""
        ...


@runtime_checkable
class FaceAligner(Protocol):
    """Interface for face alignment routines."""

    def align(self, image: np.ndarray, detection: FaceDetection) -> np.ndarray:
        """Aligns detected face to canonical ArcFace format (e.g. 112x112)."""
        ...


@runtime_checkable
class FaceEmbedder(Protocol):
    """Interface for facial feature extraction models (GLINTR100, ArcFace, MobileFace)."""

    def embed(self, aligned_face: np.ndarray) -> FaceEmbedding:
        """Extracts 512-D normalized embedding from an aligned face crop."""
        ...


@runtime_checkable
class FaceMatcher(Protocol):
    """Interface for matching embedding vectors against registered references."""

    def match(
        self,
        query: FaceEmbedding,
        references: Dict[str, List[np.ndarray]],
    ) -> IdentityMatch:
        """Finds closest matching identity among reference vectors."""
        ...


@runtime_checkable
class IdentityRepository(Protocol):
    """Interface for loading and saving employee reference profiles and embeddings."""

    def load_active_references(self) -> Dict[str, List[np.ndarray]]:
        """Returns map of active employee_id -> list of reference embedding arrays."""
        ...


@runtime_checkable
class RecognitionPolicy(Protocol):
    """Interface for determining when to trigger face recognition on a track."""

    def should_recognize(
        self,
        track: Track,
        state: Optional[TrackIdentityState],
        current_time: float,
    ) -> bool:
        """Evaluates whether the track should undergo face recognition."""
        ...
