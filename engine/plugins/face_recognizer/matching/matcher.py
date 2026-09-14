from __future__ import annotations

import logging
from typing import Dict, List, Optional
import numpy as np

from ..contracts.face import FaceEmbedding
from ..contracts.identity import IdentityMatch
from .similarity import cosine_similarity

logger = logging.getLogger(__name__)


class FaceMatcher:
    """
    Matches query face embeddings against active employee reference embeddings.
    Applies configurable similarity thresholds and returns structured IdentityMatch results.
    """

    def __init__(self, threshold: float = 0.37) -> None:
        if not (-1.0 <= threshold <= 1.0):
            raise ValueError(f"Similarity threshold must be in range [-1.0, 1.0], got {threshold}")
        self._threshold = float(threshold)

    def match(
        self,
        query: FaceEmbedding,
        references: Dict[str, List[np.ndarray]],
    ) -> IdentityMatch:
        """
        Matches query embedding against employee references.
        """
        if not references:
            return IdentityMatch(identity=None, similarity=-1.0)

        q_vec = query.vector
        best_identity: Optional[str] = None
        best_similarity = -1.0

        for employee_id, embs in references.items():
            if not embs:
                continue

            for ref_vec in embs:
                sim = cosine_similarity(q_vec, ref_vec)
                if sim > best_similarity:
                    best_similarity = sim
                    best_identity = employee_id

        if best_identity is None or best_similarity < self._threshold:
            return IdentityMatch(identity=None, similarity=best_similarity)

        return IdentityMatch(identity=best_identity, similarity=best_similarity)

    @property
    def threshold(self) -> float:
        return self._threshold
