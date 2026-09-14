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
from ..contracts.preprocessing import ImagePreprocessor as IImagePreprocessor
from ..contracts.preprocessing import PersonCropper as IPersonCropper
from ..preprocessing import (
    BoundingBoxPersonCropper,
    DefaultImagePreprocessor,
)
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
        recognizer: Optional[IFaceRecognizer] = None,
        cache: Optional[RecognitionCache] = None,
        policy: Optional[IRecognitionPolicy] = None,
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

        self._event_handlers: List[Callable[[PluginEvent], None]] = []

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

    def on_tracks_updated(self, tracks: List[Track], frame: Frame) -> None:
        """
        Consumes active tracks from vision_core each processing cycle.
        Executes facial recognition according to policy and cache state.
        """
        now = frame.timestamp
        active_track_ids = set()

        for track in tracks:
            if not track.is_active:
                continue

            active_track_ids.add(track.track_id)
            cached_state = self._cache.get(track.track_id)

            # Evaluate policy
            if self._policy.should_recognize(track, cached_state, current_time=now):
                self._process_recognition(track, frame, now)
            else:
                # Use existing cache state if present
                pass

            # Annotate track attributes cleanly
            final_state = self._cache.get(track.track_id)
            if final_state is not None:
                track.attributes["identity"] = final_state.identity
                track.attributes["recognition_status"] = final_state.state.value
                track.attributes["similarity"] = final_state.similarity

        # Evict stale tracks that disappeared
        self._cache.cleanup_stale_tracks(active_track_ids)

    def _process_recognition(
        self,
        track: Track,
        frame: Frame,
        current_time: float,
    ) -> None:
        """Run one recognition attempt for a tracked person."""

        person_crop = self._person_cropper.crop(
            image=frame.image,
            track=track,
        )

        if person_crop is None:
            result = RecognitionResult(
                status=RecognitionStatus.ERROR,
            )
            self._apply_recognition_result(
                track,
                result,
                current_time,
            )
            return

        prepared_image = self._image_preprocessor.preprocess(person_crop)

        result = self._recognizer.recognize(prepared_image)

        self._apply_recognition_result(
            track,
            result,
            current_time,
        )

    def _apply_recognition_result(
        self,
        track: Track,
        result: RecognitionResult,
        current_time: float,
    ) -> None:
        """Translate recognition result into cache state and plugin events."""

        if result.status == RecognitionStatus.RECOGNIZED:
            from ..contracts.identity import IdentityMatch

            previous_state = self._cache.get(track.track_id)

            old_identity = (
                previous_state.identity
                if previous_state is not None
                else None
            )

            match = IdentityMatch(
                identity=result.identity_id,
                similarity=result.similarity,
            )

            state, identity_changed = self._cache.update_with_match(
                track_id=track.track_id,
                match=match,
                current_time=current_time,
            )

            if identity_changed:
                self._emit_event(
                    IdentityChangedEvent(
                        track_id=track.track_id,
                        old_identity=old_identity,
                        new_identity=result.identity_id,
                        similarity=result.similarity,
                    )
                )

            self._emit_event(
                FaceRecognizedEvent(
                    track_id=track.track_id,
                    employee_id=result.identity_id,
                    similarity=result.similarity,
                    track=track,
                )
            )

            return

        if result.status == RecognitionStatus.UNKNOWN:
            self._cache.record_no_face(
                track.track_id,
                current_time=current_time,
            )

            self._emit_event(
                PersonUnknownEvent(
                    track_id=track.track_id,
                    similarity=result.similarity,
                    track=track,
                )
            )

            return

        if result.status == RecognitionStatus.NO_FACE:
            self._cache.record_no_face(
                track.track_id,
                current_time=current_time,
            )

            return

        if result.status == RecognitionStatus.ERROR:
            self._cache.record_no_face(
                track.track_id,
                current_time=current_time,
            )

            return

    def on_track_lost(self, track: Track) -> None:
        """Invoked when vision_core removes a track."""
        if track.state == TrackState.REMOVED:
            evicted = self._cache.evict(track.track_id)
            if evicted and evicted.identity:
                logger.info(f"[Plugin] Evicted track #{track.track_id} (Employee: {evicted.identity}) from recognition cache.")

    @property
    def cache(self) -> RecognitionCache:
        return self._cache

    @property
    def repository(self) -> IIdentityRepository:
        return self._repository
