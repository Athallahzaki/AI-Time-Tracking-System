from __future__ import annotations

import time
from typing import Optional, Tuple
import numpy as np

from .base import BaseFrameSource
from .timeline import PTS_DERIVED, derived_pts
from ..ports.frame import Frame, FrameMetadata


class MockFrameSource(BaseFrameSource):
    """
    Synthetic frame generator for automated testing and CI.
    Generates test pattern frames with configurable resolution and frame counts.
    """

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        fps: float = 30.0,
        max_frames: Optional[int] = None,
        source_id: str = "mock_source",
    ) -> None:
        super().__init__(source_id=source_id)
        self._width = width
        self._height = height
        self._fps = fps
        self._max_frames = max_frames
        self._frame_count = 0

    def start(self) -> None:
        self._is_running = True
        self._frame_count = 0

    def read(self) -> Optional[Frame]:
        if not self._is_running:
            return None

        if self._max_frames is not None and self._frame_count >= self._max_frames:
            return None

        self._frame_count += 1
        # Create a synthetic 3-channel test frame
        img = np.zeros((self._height, self._width, 3), dtype=np.uint8)
        # Add a moving color block
        x_offset = (self._frame_count * 5) % max(1, self._width - 100)
        img[50:150, x_offset:x_offset + 80] = (0, 255, 128)

        metadata = FrameMetadata(
            frame_id=self._frame_count,
            timestamp=time.time(),
            source_id=self._source_id,
            fps=self._fps,
            width=self._width,
            height=self._height,
            pts=derived_pts(self._frame_count, self._fps),
            pts_source=PTS_DERIVED,
            stream_epoch=0,
        )
        return Frame(image=img, metadata=metadata)

    def stop(self) -> None:
        self._is_running = False

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def resolution(self) -> Tuple[int, int]:
        return (self._width, self._height)
