from __future__ import annotations

import numpy as np

from ..ports.tracking import Track


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

        x1 = int(track.bbox.x1)
        y1 = int(track.bbox.y1)
        x2 = int(track.bbox.x2)
        y2 = int(track.bbox.y2)

        # Clamp coordinates to the original frame.
        x1 = max(0, min(x1, width))
        y1 = max(0, min(y1, height))
        x2 = max(0, min(x2, width))
        y2 = max(0, min(y2, height))

        # Invalid or empty bounding box after clipping.
        if x2 <= x1 or y2 <= y1:
            return None

        # `image[y1:y2, x1:x2]` is a numpy VIEW into the frame buffer, not a
        # copy. That is safe only while everything is synchronous. The moment a
        # crop is queued (ARCHITECTURE.md §5.2), the capture thread overwrites
        # that buffer before the worker reads it, and what gets embedded is a
        # slice of an entirely different frame — no error, just accuracy nobody
        # can explain. Copying here costs nothing measurable today and removes
        # the trap before step 18 arrives.
        crop = image[y1:y2, x1:x2].copy()

        if crop.size == 0:
            return None

        return crop