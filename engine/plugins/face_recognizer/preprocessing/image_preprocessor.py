from __future__ import annotations

import numpy as np


class DefaultImagePreprocessor:
    """Default preprocessing for person images.

    Model-specific preprocessing remains inside the corresponding
    FaceEmbedder implementation.
    """

    def preprocess(self, image: np.ndarray) -> np.ndarray:
        if image is None or image.size == 0:
            raise ValueError("Cannot preprocess an empty image.")

        return image