from __future__ import annotations

import numpy as np

from ....vision_core.contracts.tracking import Track


class BoundingBoxPersonCropper:
    """Extracts a person crop from a frame using the track bounding box."""

    def crop(
        self,
        image: np.ndarray,
        track: Track,
    ) -> np.ndarray | None:
        if image is None or image.size == 0:
            return None

        height, width = image.shape[:2]

        x1, y1, x2, y2 = track.bbox.to_int_tuple()

        # Clamp coordinates to the original frame.
        x1 = max(0, min(x1, width))
        y1 = max(0, min(y1, height))
        x2 = max(0, min(x2, width))
        y2 = max(0, min(y2, height))

        # Invalid or empty bounding box.
        if x2 <= x1 or y2 <= y1:
            return None

        crop = image[y1:y2, x1:x2]

        if crop.size == 0:
            return None

        return crop