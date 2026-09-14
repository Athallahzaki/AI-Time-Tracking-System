"""
face_recognizer plugin: Domain-specific face recognition extension for vision_core.
Decoupled into detector, aligner, embedder, matcher, storage, cache, and policy.
"""

from .contracts import (
    FaceLandmarks,
    FaceDetection,
    FaceEmbedding,
    RecognitionStatus,
    IdentityMatch,
    TrackIdentityState,
    FaceDetector,
    FaceAligner as IFaceAligner,
    FaceEmbedder,
    FaceMatcher as IFaceMatcher,
    IdentityRepository,
    RecognitionPolicy,
    PluginEvent,
    FaceRecognizedEvent,
    PersonUnknownEvent,
    IdentityChangedEvent,
    RecognitionExpiredEvent,
)
from .alignment import FaceAligner, ARC_FACE_TEMPLATE
from .detector import SCRFDDetector, MockFaceDetector
from .embedding import GLINTR100Embedder, MockFaceEmbedder
from .matching import cosine_similarity, FaceMatcher
from .storage import EmployeeStore, EmbeddingStore, EmployeeRepository
from .cache import RecognitionCache
from .policy import StandardRecognitionPolicy
from .pipeline import FaceRecognizerConfig, FaceRecognizerPlugin

__all__ = [
    # Contracts
    "FaceLandmarks",
    "FaceDetection",
    "FaceEmbedding",
    "RecognitionStatus",
    "IdentityMatch",
    "TrackIdentityState",
    "FaceDetector",
    "IFaceAligner",
    "FaceEmbedder",
    "IFaceMatcher",
    "IdentityRepository",
    "RecognitionPolicy",
    "PluginEvent",
    "FaceRecognizedEvent",
    "PersonUnknownEvent",
    "IdentityChangedEvent",
    "RecognitionExpiredEvent",
    # Implementations
    "FaceAligner",
    "ARC_FACE_TEMPLATE",
    "SCRFDDetector",
    "MockFaceDetector",
    "GLINTR100Embedder",
    "MockFaceEmbedder",
    "cosine_similarity",
    "FaceMatcher",
    "EmployeeStore",
    "EmbeddingStore",
    "EmployeeRepository",
    "RecognitionCache",
    "StandardRecognitionPolicy",
    "FaceRecognizerConfig",
    "FaceRecognizerPlugin",
]
