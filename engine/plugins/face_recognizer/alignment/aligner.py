from __future__ import annotations

import logging
from typing import Tuple
import cv2
import numpy as np

from ..contracts.face import FaceDetection

logger = logging.getLogger(__name__)

# Standard ArcFace landmark template for canonical 112x112 face alignment
ARC_FACE_TEMPLATE = np.array(
    [
        [38.2946, 51.6963],  # Left eye
        [73.5318, 51.5014],  # Right eye
        [56.0252, 71.7366],  # Nose tip
        [41.5493, 92.3655],  # Left mouth corner
        [70.7299, 92.2041],  # Right mouth corner
    ],
    dtype=np.float32,
)


class FaceAligner:
    """
    Standard 5-point affine transformation aligner.
    Transforms raw face crops into canonical ArcFace format (112x112).
    """

    def __init__(self, output_size: Tuple[int, int] = (112, 112)) -> None:
        self._output_size = output_size
        self._template = self._build_template(output_size)

    def align(self, image: np.ndarray, detection: FaceDetection) -> np.ndarray:
        """
        Aligns a detected face from the provided image using 5 facial landmarks.
        """
        if image is None or image.size == 0:
            raise ValueError("Input image is empty or None.")

        landmarks = detection.landmarks.to_numpy()
        transform = self._estimate_transform(landmarks)

        width, height = self._output_size
        aligned = cv2.warpAffine(
            image,
            transform,
            (width, height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
        )
        return aligned

    def _estimate_transform(self, landmarks: np.ndarray) -> np.ndarray:
        """Estimates affine similarity transformation matrix."""
        transform, _ = cv2.estimateAffinePartial2D(
            landmarks,
            self._template,
            method=cv2.LMEDS,
        )

        if transform is None:
            # Fallback to standard least squares if LMEDS fails
            transform, _ = cv2.estimateAffinePartial2D(
                landmarks,
                self._template,
            )

        if transform is None:
            raise RuntimeError("Failed to compute affine transform for face alignment.")

        return transform.astype(np.float32)

    @staticmethod
    def _build_template(output_size: Tuple[int, int]) -> np.ndarray:
        width, height = output_size
        if width == 112 and height == 112:
            return ARC_FACE_TEMPLATE.copy()

        scale_x = width / 112.0
        scale_y = height / 112.0
        template = ARC_FACE_TEMPLATE.copy()
        template[:, 0] *= scale_x
        template[:, 1] *= scale_y
        return template

    @property
    def output_size(self) -> Tuple[int, int]:
        return self._output_size
