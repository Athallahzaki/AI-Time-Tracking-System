from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Union
import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingStore:
    """NumPy-based persistence for registered employee reference embeddings."""

    def __init__(self, directory: Union[str, Path] = "data/embeddings", embedding_dimension: int = 512) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._dim = embedding_dimension

    def _get_path(self, employee_id: str) -> Path:
        return self._dir / f"{employee_id}.npy"

    def exists(self, employee_id: str) -> bool:
        return self._get_path(employee_id).exists()

    def save(self, employee_id: str, embeddings: List[np.ndarray]) -> None:
        """Saves a stack of reference embedding vectors (Shape: N, 512)."""
        if not embeddings:
            return

        cleaned = []
        for emb in embeddings:
            vec = np.asarray(emb, dtype=np.float32).reshape(-1)
            if vec.size != self._dim:
                raise ValueError(f"Expected {self._dim}-D vector, got {vec.size}")
            # Ensure normalized
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            cleaned.append(vec)

        stacked = np.stack(cleaned, axis=0)
        np.save(self._get_path(employee_id), stacked)

    def load(self, employee_id: str) -> List[np.ndarray]:
        path = self._get_path(employee_id)
        if not path.exists():
            return []
        try:
            arr = np.load(path)
            if arr.ndim == 1:
                return [arr.astype(np.float32)]
            elif arr.ndim == 2:
                return [arr[i].astype(np.float32) for i in range(arr.shape[0])]
            return []
        except Exception as e:
            logger.error(f"Failed to load embeddings for {employee_id}: {e}")
            return []

    def delete(self, employee_id: str) -> bool:
        path = self._get_path(employee_id)
        if path.exists():
            path.unlink()
            return True
        return False
