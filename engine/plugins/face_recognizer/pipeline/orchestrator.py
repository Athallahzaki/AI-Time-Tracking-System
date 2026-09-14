from __future__ import annotations

import logging
from typing import Callable, Optional

from ....vision_core.contracts.frame import Frame
from ....vision_core.contracts.tracking import Track
from ..cache.recognition_cache import RecognitionCache
from ..contracts.events import (
    FaceRecognizedEvent,
    IdentityChangedEvent,
    PersonUnknownEvent,
    PluginEvent,
)
from ..contracts.identity import IdentityMatch
from ..contracts.interfaces import (
    FaceRecognizer,
    RecognitionPolicy,
)
from ..contracts.preprocessing import (
    ImagePreprocessor,
    PersonCropper,
)
from ..contracts.recognition import (
    RecognitionResult,
    RecognitionStatus,
)

logger = logging.getLogger(__name__)


class RecognitionOrchestrator:
    """
    Coordinates the complete recognition workflow for one tracked person.

    Responsibilities:
    - recognition policy
    - person cropping
    - image preprocessing
    - face recognition
    - recognition cache updates
    - recognition event generation

    Does not know:
    - RTSP/video source
    - YOLO detector
    - tracker implementation
    - attendance/business logic
    """

    def __init__(
        self,
        recognizer: FaceRecognizer,
        person_cropper: PersonCropper,
        image_preprocessor: ImagePreprocessor,
        policy: RecognitionPolicy,
        cache: RecognitionCache,
        event_handler: Optional[Callable[[PluginEvent], None]] = None,
    ) -> None:
        self._recognizer = recognizer
        self._person_cropper = person_cropper
        self._image_preprocessor = image_preprocessor
        self._policy = policy
        self._cache = cache
        self._event_handler = event_handler

    def process(
        self,
        track: Track,
        frame: Frame,
        current_time: float,
    ) -> RecognitionResult | None:
        """
        Process one recognition attempt for a tracked person.

        Returns:
            RecognitionResult when recognition is attempted.
            None when recognition policy denies the attempt.
        """

        state = self._cache.get(track.track_id)

        if not self._policy.should_recognize(
            track=track,
            state=state,
            current_time=current_time,
        ):
            return None

        person_crop = self._person_cropper.crop(
            image=frame.image,
            track=track,
        )

        if person_crop is None:
            result = RecognitionResult(
                status=RecognitionStatus.ERROR,
            )

            self._apply_result(
                track=track,
                result=result,
                current_time=current_time,
            )

            return result

        prepared_image = self._image_preprocessor.preprocess(
            person_crop,
        )

        result = self._recognizer.recognize(
            prepared_image,
        )

        self._apply_result(
            track=track,
            result=result,
            current_time=current_time,
        )

        return result

    def _apply_result(
        self,
        track: Track,
        result: RecognitionResult,
        current_time: float,
    ) -> None:
        """
        Translate RecognitionResult into cache state and events.
        """

        if result.status == RecognitionStatus.RECOGNIZED:
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
                self._emit(
                    IdentityChangedEvent(
                        track_id=track.track_id,
                        old_identity=old_identity,
                        new_identity=state.identity,
                        similarity=state.similarity,
                    )
                )

            self._emit(
                FaceRecognizedEvent(
                    track_id=track.track_id,
                    employee_id=state.identity,
                    similarity=state.similarity,
                    track=track,
                )
            )

            return

        if result.status == RecognitionStatus.UNKNOWN:
            self._cache.record_no_face(
                track_id=track.track_id,
                current_time=current_time,
            )

            self._emit(
                PersonUnknownEvent(
                    track_id=track.track_id,
                    similarity=result.similarity,
                    track=track,
                )
            )

            return

        if result.status in (
            RecognitionStatus.NO_FACE,
            RecognitionStatus.ERROR,
        ):
            self._cache.record_no_face(
                track_id=track.track_id,
                current_time=current_time,
            )

            return

    def _emit(self, event: PluginEvent) -> None:
        """
        Forward event to the external event handler.

        The orchestrator does not own event subscriptions. It only
        forwards generated events to its boundary callback.
        """

        if self._event_handler is None:
            return

        try:
            self._event_handler(event)
        except Exception:
            logger.exception(
                "Recognition event handler failed."
            )