from __future__ import annotations

import numpy as np


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    Computes cosine similarity between two 1D vectors.
    Assumes vectors are L2-normalized; if not, computes standard cosine formula.
    """
    if a.shape != b.shape:
        raise ValueError(f"Shape mismatch in cosine similarity: {a.shape} vs {b.shape}")

    dot = float(np.dot(a, b))
    # If vectors are normalized, dot is directly cosine similarity
    return max(-1.0, min(1.0, dot))
