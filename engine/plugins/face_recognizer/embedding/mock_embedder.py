from __future__ import annotations

import numpy as np
from ..contracts.face import FaceEmbedding


class MockFaceEmbedder:
    """Mock embedder returning deterministic or preset unit vectors."""

    def __init__(self, dimension: int = 512, preset_vector: np.ndarray = None) -> None:
        self.dimension = dimension
        self.preset_vector = preset_vector

    def embed(self, aligned_face: np.ndarray) -> FaceEmbedding:
        if self.preset_vector is not None:
            vec = self.preset_vector
        else:
            # Deterministic vector based on mean pixel color
            mean_val = float(np.mean(aligned_face)) if aligned_face is not None else 1.0
            vec = np.ones(self.dimension, dtype=np.float32) * (mean_val / 255.0)

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        else:
            vec[0] = 1.0

        return FaceEmbedding(vector=vec, dimension=self.dimension)
