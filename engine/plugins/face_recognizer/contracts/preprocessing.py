from __future__ import annotations

from typing import Protocol

import numpy as np

from ....vision_core.contracts.tracking import Track


class PersonCropper(Protocol):
    """Extracts a person image from a full frame using a track bounding box."""

    def crop(
        self,
        image: np.ndarray,
        track: Track,
    ) -> np.ndarray | None:
        ...


class ImagePreprocessor(Protocol):
    """Prepares a person image before it is passed to face recognition."""

    def preprocess(
        self,
        image: np.ndarray,
    ) -> np.ndarray:
        ...