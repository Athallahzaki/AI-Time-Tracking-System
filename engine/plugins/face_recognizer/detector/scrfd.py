from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np

from ....vision_core.contracts.geometry import BoundingBox
from ..contracts.face import FaceDetection, FaceLandmarks

logger = logging.getLogger(__name__)


class SCRFDDetector:
    """
    Adapter for SCRFD ONNX face detector models via InsightFace / ONNXRuntime.
    Extracts face bounding boxes and 5 facial keypoints.
    """

    def __init__(
        self,
        model_path: Union[str, Path] = "models/detector/scrfd_10g_bnkps.onnx",
        confidence_threshold: float = 0.5,
        input_size: Tuple[int, int] = (640, 640),
        providers: Optional[List[str]] = None,
    ) -> None:
        self._model_path = Path(model_path)
        self._confidence_threshold = confidence_threshold
        self._input_size = input_size
        self._requested_providers = providers or ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self._providers = self._resolve_providers(self._requested_providers)
        self._model = None

        self._init_model()

    @staticmethod
    def _resolve_providers(requested: List[str]) -> List[str]:
        try:
            import onnxruntime as ort
            available = ort.get_available_providers()
            filtered = [p for p in requested if p in available]
            return filtered if filtered else ["CPUExecutionProvider"]
        except Exception:
            return ["CPUExecutionProvider"]

    def _init_model(self) -> None:
        if not self._model_path.exists():
            logger.warning(f"SCRFD model not found at {self._model_path}. Detector will fail if called.")
            return

        try:
            from insightface.model_zoo import get_model
            ctx_id = 0 if "CUDAExecutionProvider" in self._providers else -1
            self._model = get_model(str(self._model_path), providers=self._providers)
            self._model.prepare(ctx_id=ctx_id, input_size=self._input_size)
            logger.info(f"Loaded SCRFD detector from {self._model_path} with providers: {self._providers}")
        except Exception as e:
            logger.warning(f"Could not load SCRFD via insightface ({e}). Face detection will be skipped unless insightface is installed.")
            self._model = None

    def detect(self, image: np.ndarray) -> List[FaceDetection]:
        """
        Runs face detection on an input image (full frame or cropped person).
        Returns normalized FaceDetection objects with 5-point landmarks.
        """
        if image is None or image.size == 0:
            return []

        if self._model is None:
            # If model wasn't loaded, return empty detections gracefully
            return []

        h, w = image.shape[:2]
        try:
            # SCRFD forward pass
            bboxes, kpss = self._model.detect(
                image,
                max_num=0,
                metric="default",
            )
        except Exception as e:
            logger.error(f"SCRFD detection failed: {e}")
            return []

        if bboxes is None or len(bboxes) == 0:
            return []

        detections: List[FaceDetection] = []
        for i in range(len(bboxes)):
            bbox_raw = bboxes[i]
            score = float(bbox_raw[4])
            if score < self._confidence_threshold:
                continue

            x1, y1, x2, y2 = bbox_raw[:4]
            box = BoundingBox(
                x1=float(x1),
                y1=float(y1),
                x2=float(x2),
                y2=float(y2),
            ).clip(max_width=w, max_height=h)

            landmarks_raw = kpss[i] if kpss is not None else np.zeros((5, 2), dtype=np.float32)
            landmarks = FaceLandmarks(points=np.asarray(landmarks_raw, dtype=np.float32))

            detections.append(
                FaceDetection(
                    bbox=box,
                    confidence=score,
                    landmarks=landmarks,
                )
            )

        return detections
