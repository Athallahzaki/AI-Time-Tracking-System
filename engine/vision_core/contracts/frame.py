from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict
import numpy as np


@dataclass(frozen=True)
class FrameMetadata:
    """Metadata associated with an ingested frame."""
    frame_id: int
    timestamp: float = field(default_factory=time.time)
    source_id: str = "default"
    fps: float = 0.0
    width: int = 0
    height: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Frame:
    """
    Encapsulates raw image buffer and associated metadata.
    Avoids unnecessary copies by passing the underlying ndarray.
    """
    image: np.ndarray
    metadata: FrameMetadata

    @property
    def frame_id(self) -> int:
        return self.metadata.frame_id

    @property
    def timestamp(self) -> float:
        return self.metadata.timestamp

    @property
    def shape(self) -> tuple[int, ...]:
        return self.image.shape

    @property
    def height(self) -> int:
        return self.image.shape[0]

    @property
    def width(self) -> int:
        return self.image.shape[1]
