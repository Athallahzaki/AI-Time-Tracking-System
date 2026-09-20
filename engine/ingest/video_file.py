from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional, Tuple, Union
import cv2

from .base import BaseFrameSource
from .timeline import PTS_DERIVED, derived_pts
from ..ports.frame import Frame, FrameMetadata

logger = logging.getLogger(__name__)


class VideoFileSource(BaseFrameSource):
    """
    Sequential video file reader.
    Supports real-time playback pacing (matching original video FPS)
    or unthrottled maximum-speed processing (ideal for batch benchmarks).
    """

    def __init__(
        self,
        filepath: Union[str, Path],
        source_id: str = "video_file",
        realtime_pacing: bool = True,
        loop: bool = False,
    ) -> None:
        super().__init__(source_id=source_id)
        self._filepath = str(filepath)
        self._realtime_pacing = realtime_pacing
        self._loop = loop

        self._cap: Optional[cv2.VideoCapture] = None
        self._fps: float = 30.0
        self._width: int = 0
        self._height: int = 0
        self._total_frames: int = 0
        self._last_frame_time: float = 0.0

    def start(self) -> None:
        if self._is_running:
            return

        self._cap = cv2.VideoCapture(self._filepath)
        if not self._cap.isOpened():
            raise FileNotFoundError(f"Could not open video file: {self._filepath}")

        fps = self._cap.get(cv2.CAP_PROP_FPS)
        self._fps = fps if (fps and fps > 0) else 30.0
        self._width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._total_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))

        self._frame_count = 0
        self._is_running = True
        self._last_frame_time = time.perf_counter()
        logger.info(
            f"[{self._source_id}] Opened video file '{self._filepath}': {self._width}x{self._height} "
            f"@ {self._fps:.1f} FPS, total frames: {self._total_frames}"
        )

    def read(self) -> Optional[Frame]:
        if not self._is_running or self._cap is None:
            return None

        # Real-time frame rate throttling
        if self._realtime_pacing and self._fps > 0:
            target_interval = 1.0 / self._fps
            elapsed = time.perf_counter() - self._last_frame_time
            if elapsed < target_interval:
                time.sleep(target_interval - elapsed)
            self._last_frame_time = time.perf_counter()

        ret, img = self._cap.read()
        if not ret or img is None:
            if self._loop:
                logger.info(f"[{self._source_id}] Looping video back to start.")
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, img = self._cap.read()
                if not ret or img is None:
                    return None
            else:
                logger.info(f"[{self._source_id}] Reached end of video.")
                return None

        self._frame_count += 1
        # cv2.VideoCapture discards the container PTS (§5.5), so the only
        # timeline available here is an assumed one. It is labelled as assumed:
        # exact for a constant-rate file, and quietly wrong for a variable-rate
        # recording, which is what phones produce. PyAVSource is the way out.
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
        if not self._is_running:
            return

        self._is_running = False
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        logger.info(f"[{self._source_id}] Video file source stopped.")

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def resolution(self) -> Tuple[int, int]:
        return (self._width, self._height)

    @property
    def total_frames(self) -> int:
        return self._total_frames
