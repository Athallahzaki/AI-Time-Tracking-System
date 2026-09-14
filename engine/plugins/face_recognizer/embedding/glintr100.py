from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Union
import cv2
import numpy as np

from ..contracts.face import FaceEmbedding

logger = logging.getLogger(__name__)


class GLINTR100Embedder:
    """
    ONNX Runtime feature extractor for GLINTR100 / ArcFace face recognition models.
    Produces 512-dimensional, L2-normalized identity embeddings.
    """

    def __init__(
        self,
        model_path: Union[str, Path] = "models/embedder/glintr100.onnx",
        dimension: int = 512,
        providers: Optional[List[str]] = None,
    ) -> None:
        self._model_path = Path(model_path)
        self._dimension = dimension
        self._requested_providers = providers or ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self._providers = self._resolve_providers(self._requested_providers)

        self._session = None
        self._input_name = None
        self._init_session()

    @staticmethod
    def _resolve_providers(requested: List[str]) -> List[str]:
        try:
            import onnxruntime as ort
            available = ort.get_available_providers()
            filtered = [p for p in requested if p in available]
            return filtered if filtered else ["CPUExecutionProvider"]
        except Exception:
            return ["CPUExecutionProvider"]

    def _init_session(self) -> None:
        if not self._model_path.exists():
            logger.warning(f"GLINTR100 model not found at {self._model_path}. Embedder will fail if called.")
            return

        try:
            import onnxruntime as ort
            self._session = ort.InferenceSession(
                str(self._model_path),
                providers=self._providers,
            )
            inputs = self._session.get_inputs()
            self._input_name = inputs[0].name
            logger.info(f"Loaded GLINTR100 ONNX model from {self._model_path} with providers: {self._providers}")
        except Exception as e:
            logger.warning(f"Failed to initialize ONNX session for GLINTR100: {e}")
            self._session = None

    def embed(self, aligned_face: np.ndarray) -> FaceEmbedding:
        """
        Extracts 512-D normalized embedding vector from a 112x112 aligned face.
        """
        if self._session is None:
            raise RuntimeError(f"GLINTR100 ONNX session not initialized or model file missing ({self._model_path}).")

        # Preprocessing: BGR -> RGB, normalization (x - 127.5)/127.5, HWC -> CHW -> NCHW
        if aligned_face.shape[:2] != (112, 112):
            aligned_face = cv2.resize(aligned_face, (112, 112))

        rgb = cv2.cvtColor(aligned_face, cv2.COLOR_BGR2RGB)
        tensor = (rgb.astype(np.float32) - 127.5) / 127.5
        tensor = np.transpose(tensor, (2, 0, 1))  # (3, 112, 112)
        tensor = np.expand_dims(tensor, axis=0)   # (1, 3, 112, 112)

        outputs = self._session.run(None, {self._input_name: tensor})
        raw_vec = np.asarray(outputs[0], dtype=np.float32).reshape(-1)

        # L2-normalize vector
        norm = np.linalg.norm(raw_vec)
        if norm > 0:
            norm_vec = raw_vec / norm
        else:
            norm_vec = raw_vec

        return FaceEmbedding(vector=norm_vec, dimension=self._dimension)

    @property
    def dimension(self) -> int:
        return self._dimension
