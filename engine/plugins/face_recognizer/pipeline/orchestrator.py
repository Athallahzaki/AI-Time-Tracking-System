from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from ..cache.recognition_cache import RecognitionCache
from ..contracts.events import (
    FaceRecognizedEvent,
    IdentityChangedEvent,
    PersonUnknownEvent,
)
from ..contracts.identity import IdentityMatch
from ..contracts.preprocessing import (
    ImagePreprocessor,
    PersonCropper,
)
from ..contracts.interfaces import (
    FaceRecognizer,
    RecognitionPolicy,
)
from ..contracts.recognition import RecognitionResult, RecognitionStatus
from ....vision_core.contracts.frame import Frame
from ....vision_core.contracts.tracking import Track

logger = logging.getLogger(__name__)


class RecognitionOrchestrator:
    """
    Coordinates the full recognition workflow for one tracked person.

    Owns:
    - recognition policy
    - person crop
    - image preprocessing
    - face recognition
    - recognition cache
    - recognition state updates
    - recognition events

    Does not own:
    - video input
    - tracking
    - model implementation details
    - attendance/business logic
    """

    def __init__(
        self,
        recognizer: FaceRecognizer,
        person_cropper: PersonCropper,
        image_preprocessor: ImagePreprocessor,
        policy: RecognitionPolicy,
        cache: RecognitionCache,
    ) -> None:
        self._recognizer = recognizer
        self._person_cropper = person_cropper
        self._image_preprocessor = image_preprocessor
        self._policy = policy
        self._cache = cache

    def process(
        self,
        track: Track,
        frame: Frame,
        current_time: float,
    ) -> RecognitionResult | None:
        """
        Process one recognition attempt for a track.

        Returns None when policy decides that recognition should not
        be attempted at this moment.
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
        state = self._cache.get(track.track_id)

        if result.status == RecognitionStatus.RECOGNIZED:
            previous_identity = state.identity if state is not None else None

            match = IdentityMatch(
                identity=result.identity_id,
                similarity=result.similarity,
            )

            updated_state, identity_changed = (
                self._cache.update_with_match(
                    track_id=track.track_id,
                    match=match,
                    current_time=current_time,
                )
            )

            if identity_changed:
                self._emit(
                    IdentityChangedEvent(
                        track_id=track.track_id,
                        old_identity=previous_identity,
                        new_identity=updated_state.identity,
                        similarity=updated_state.similarity,
                    )
                )

            self._emit(
                FaceRecognizedEvent(
                    track_id=track.track_id,
                    employee_id=updated_state.identity,
                    similarity=updated_state.similarity,
                    track=track,
                )
            )

        elif result.status == RecognitionStatus.UNKNOWN:
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

        elif result.status in (
            RecognitionStatus.NO_FACE,
            RecognitionStatus.ERROR,
        ):
            self._cache.record_no_face(
                track_id=track.track_id,
                current_time=current_time,
            )

    def _emit(self, event: object) -> None:
        """
        Temporary event boundary.

        Event dispatch will be injected explicitly once the existing
        plugin event mechanism is moved out of FaceRecognizerPlugin.
        """
        logger.debug("Recognition event generated: %r", event)