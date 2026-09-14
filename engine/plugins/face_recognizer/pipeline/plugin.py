from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional
import numpy as np

from ....vision_core.contracts.frame import Frame
from ....vision_core.contracts.tracking import Track, TrackState
from ..alignment.aligner import FaceAligner
from ..cache.recognition_cache import RecognitionCache
from ..contracts.events import (
    FaceRecognizedEvent,
    IdentityChangedEvent,
    PersonUnknownEvent,
    PluginEvent,
    RecognitionExpiredEvent,
)
from ..contracts.identity import IdentityMatch, TrackIdentityState
from ..contracts.interfaces import (
    FaceAligner as IFaceAligner,
    FaceDetector as IFaceDetector,
    FaceEmbedder as IFaceEmbedder,
    FaceMatcher as IFaceMatcher,
    FaceRecognizer as IFaceRecognizer,
    IdentityRepository as IIdentityRepository,
    RecognitionPolicy as IRecognitionPolicy,
)
from ..contracts.recognition import (
    RecognitionResult,
    RecognitionStatus,
)
from ..contracts.preprocessing import (
    ImagePreprocessor as IImagePreprocessor,
    PersonCropper as IPersonCropper,
)
from ..preprocessing import (
    BoundingBoxPersonCropper,
    DefaultImagePreprocessor,
)
from .orchestrator import RecognitionOrchestrator
from .recognizer import FaceRecognitionService
from ..detector.scrfd import SCRFDDetector
from ..embedding.glintr100 import GLINTR100Embedder
from ..matching.matcher import FaceMatcher
from ..policy.recognition_policy import StandardRecognitionPolicy
from ..storage.repository import EmployeeRepository
from .config import FaceRecognizerConfig

logger = logging.getLogger(__name__)


class FaceRecognizerPlugin:
    """
    Decoupled Face Recognition Plugin that subscribes to Track updates from vision_core.
    Coordinates recognition policy, state caching, cropping, face detection,
    alignment, embedding extraction, identity matching, and event dispatch.
    """

    def __init__(
        self,
        config: Optional[FaceRecognizerConfig] = None,
        detector: Optional[IFaceDetector] = None,
        aligner: Optional[IFaceAligner] = None,
        embedder: Optional[IFaceEmbedder] = None,
        matcher: Optional[IFaceMatcher] = None,
        repository: Optional[IIdentityRepository] = None,
        cache: Optional[RecognitionCache] = None,
        policy: Optional[IRecognitionPolicy] = None,
        recognizer: Optional[IFaceRecognizer] = None,
        person_cropper: Optional[IPersonCropper] = None,
        image_preprocessor: Optional[IImagePreprocessor] = None,
    ) -> None:
        self._config = config or FaceRecognizerConfig()

        # Injected or default components
        self._detector = detector or SCRFDDetector(
            model_path=self._config.detector_model_path,
            confidence_threshold=self._config.detector_confidence_threshold,
            input_size=self._config.detector_input_size,
            providers=self._config.providers,
        )
        self._aligner = aligner or FaceAligner(
            output_size=self._config.alignment_output_size,
        )
        self._embedder = embedder or GLINTR100Embedder(
            model_path=self._config.embedder_model_path,
            dimension=self._config.embedding_dimension,
            providers=self._config.providers,
        )
        self._matcher = matcher or FaceMatcher(
            threshold=self._config.similarity_threshold,
        )
        self._repository = repository or EmployeeRepository(
            employees_dir=self._config.employees_dir,
            embeddings_dir=self._config.embeddings_dir,
            embedding_dimension=self._config.embedding_dimension,
        )
        self._recognizer = recognizer or FaceRecognitionService(
            detector=self._detector,
            aligner=self._aligner,
            embedder=self._embedder,
            matcher=self._matcher,
            repository=self._repository,
        )
        self._cache = cache or RecognitionCache(
            ttl_seconds=self._config.cache_ttl_seconds,
        )
        self._policy = policy or StandardRecognitionPolicy(
            min_person_width=self._config.min_person_crop_width,
            min_person_height=self._config.min_person_crop_height,
            min_confirmations=self._config.min_confirmations,
            unknown_retry_interval_sec=self._config.unknown_retry_interval_sec,
            max_unknown_retries=self._config.max_unknown_retries,
            backoff_retry_interval_sec=self._config.backoff_retry_interval_sec,
            recognition_ttl_sec=self._config.cache_ttl_seconds,
        )

        self._person_cropper = person_cropper or BoundingBoxPersonCropper()
        self._image_preprocessor = image_preprocessor or DefaultImagePreprocessor()

        self._orchestrator = RecognitionOrchestrator(
            recognizer=self._recognizer,
            person_cropper=self._person_cropper,
            image_preprocessor=self._image_preprocessor,
            policy=self._policy,
            cache=self._cache,
            event_handler=self._emit_event,
        )

        self._event_handlers: List[Callable[[PluginEvent], None]] = []

    @property
    def repository(self) -> IIdentityRepository:
        return self._repository

    def add_event_handler(self, handler: Callable[[PluginEvent], None]) -> FaceRecognizerPlugin:
        """Registers a callback for face recognition events."""
        if handler not in self._event_handlers:
            self._event_handlers.append(handler)
        return self

    def _emit_event(self, event: PluginEvent) -> None:
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Error in face recognition event handler: {e}")

    def on_tracks_updated(
        self,
        tracks: List[Track],
        frame: Frame,
    ) -> None:
        """
        Consumes active tracks from vision_core each processing cycle.

        Recognition workflow is delegated to RecognitionOrchestrator.
        """

        now = frame.timestamp

        for track in tracks:
            if not track.is_active:
                continue

            self._orchestrator.process(
                track=track,
                frame=frame,
                current_time=now,
            )

            final_state = self._cache.get(
                track.track_id,
            )

            if final_state is not None:
                track.attributes["identity"] = (
                    final_state.identity
                )

                track.attributes["recognition_status"] = (
                    final_state.state.value
                )

                track.attributes["similarity"] = (
                    final_state.similarity
                )


    def on_track_lost(
        self,
        track: Track,
    ) -> None:
        """
        Called once when a track transitions into LOST.

        Recognition state is intentionally retained while the
        track is temporarily occluded.
        """
        logger.debug(
            "[Plugin] Track #%s temporarily lost; "
            "recognition cache retained.",
            track.track_id,
        )


    def on_track_removed(
        self,
        track: Track,
    ) -> None:
        """
        Called when a track is permanently removed from
        tracker output.
        """
        evicted = self._cache.evict(
            track.track_id,
        )

        if evicted and evicted.identity:
            logger.info(
                "[Plugin] Evicted track #%s "
                "(Employee: %s) from recognition cache.",
                track.track_id,
                evicted.identity,
            )
